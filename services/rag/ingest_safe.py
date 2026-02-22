#!/usr/bin/env python3
"""
OLake Documentation Ingestion Script - Safe Single-Threaded Mode.

Uses transformers with ALL parallelism disabled.
Processes one chunk at a time to prevent any crashes.

Dense embeddings only - no sparse vectors.
"""

from __future__ import annotations

# MUST be set BEFORE any torch/transformers imports
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"

import sys
import json
import logging
import time
import gc
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams,
    OptimizersConfigDiff, PointStruct,
    TextIndexParams,
    TokenizerType,
)

import torch
from transformers import AutoModel, AutoTokenizer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding model (loaded once, single-threaded)
# ---------------------------------------------------------------------------

class SingleThreadEmbedder:
    """transformers-based embedder with mean pooling + L2 normalization."""

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5", device: str = "cpu"):
        logger.info(f"Loading embedding model: {model_name}")
        self._tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            local_files_only=True,
            trust_remote_code=True,
        )
        self._model = AutoModel.from_pretrained(
            model_name,
            local_files_only=True,
            trust_remote_code=True,
        )
        self._model.eval()
        self._model.to(device)
        self._device = device
        self._dim = 768  # nomic-embed-text-v1.5 output dimension
        logger.info(f"Embedding model loaded, dim={self._dim}")

    def _mean_pooling(self, token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """Mean pooling over token embeddings."""
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        return sum_embeddings / sum_mask

    def _normalize_embeddings(self, embeddings: torch.Tensor) -> torch.Tensor:
        """L2 normalize embeddings."""
        return torch.nn.functional.normalize(embeddings, p=2, dim=1)

    def embed(self, text: str) -> List[float]:
        prefixed = "search_document: " + text
        encoded = self._tokenizer(
            prefixed,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(self._device)

        with torch.no_grad():
            outputs = self._model(**encoded)
            token_embeddings = outputs.last_hidden_state
            pooled = self._mean_pooling(token_embeddings, encoded["attention_mask"])
            normalized = self._normalize_embeddings(pooled)

        # Extract first element from batch (shape: [1, dim] -> [dim])
        return normalized.cpu().tolist()[0]

    @property
    def dimension(self) -> int:
        return self._dim


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

class Checkpoint:
    def __init__(self, path: Path):
        self.path = path
        self.data = self.load()

    def load(self) -> Dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except:
                pass
        return {}

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2))

    def delete(self):
        if self.path.exists():
            self.path.unlink()


# ---------------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------------

def ingest(
    docs_path: Path,
    reset: bool = False,
    collection: str = "both",
) -> Dict:
    """Ingest documents one chunk at a time."""

    stats = {
        "total": 0,
        "docs": 0,
        "code": 0,
        "upserted_docs": 0,
        "upserted_code": 0,
        "failed": 0,
        "start": datetime.now(timezone.utc).isoformat(),
        "end": "",
    }

    try:
        # Validate
        if not docs_path.exists():
            raise FileNotFoundError(f"Not found: {docs_path}")

        logger.info(f"Starting ingestion: {docs_path}")
        logger.info(f"Reset: {reset}, Collection: {collection}")

        # Parse chunks
        from chunker import parse_file
        logger.info("Parsing...")
        all_chunks = parse_file(docs_path)
        stats["total"] = len(all_chunks)
        stats["docs"] = len([c for c in all_chunks if c.chunk_type != "code"])
        stats["code"] = len([c for c in all_chunks if c.chunk_type == "code"])
        logger.info(f"Parsed {stats['total']} chunks ({stats['docs']} docs, {stats['code']} code)")

        # Qdrant client
        url = Config.QDRANT_URL
        api_key = Config.QDRANT_API_KEY
        if url.startswith("http"):
            client = QdrantClient(url=url, api_key=api_key)
        else:
            client = QdrantClient(path=url)

        # Embedder
        embedder = SingleThreadEmbedder(device=Config.EMBED_DEVICE)
        vector_dim = embedder.dimension

        # Collections
        collections = []
        if collection in ("both", "docs"):
            collections.append(Config.DOCS_COLLECTION)
        if collection in ("both", "code"):
            collections.append(Config.CODE_COLLECTION)

        for coll in collections:
            if reset and client.collection_exists(coll):
                client.delete_collection(coll)
                logger.info(f"Dropped: {coll}")
            if not client.collection_exists(coll):
                client.create_collection(
                    collection_name=coll,
                    vectors_config={"dense": VectorParams(size=vector_dim, distance=Distance.COSINE)},
                    # Dense vectors only - no sparse_vectors_config
                    optimizers_config=OptimizersConfigDiff(indexing_threshold=0),
                )
                logger.info(f"Created: {coll}")

                # Create full-text index on the text field
                client.create_payload_index(
                    collection_name=coll,
                    field_name="text",
                    field_schema=TextIndexParams(
                        type="text",
                        tokenizer=TokenizerType.WORD,
                        lowercase=True,
                        min_token_len=2,
                        max_token_len=50,
                    ),
                )
                logger.info(f"Created full-text index on 'text' field for collection: {coll}")

        # Checkpoint
        checkpoint_dir = Path("./.ingest_checkpoints")
        checkpoint_dir.mkdir(exist_ok=True)

        # Ingest docs
        docs_chunks = [c for c in all_chunks if c.chunk_type != "code"]
        if docs_chunks and Config.DOCS_COLLECTION in collections:
            ckpt = Checkpoint(checkpoint_dir / "docs.json")
            if reset:
                ckpt.data = {}
            start_idx = ckpt.data.get("processed", 0)
            logger.info(f"Ingesting {len(docs_chunks)} docs chunks (from {start_idx})...")

            upserted = ckpt.data.get("upserted", 0)
            for i, chunk in enumerate(docs_chunks[start_idx:], start=start_idx):
                try:
                    # Embed (one at a time)
                    dense = embedder.embed(chunk.text)

                    # Point
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
                    payload = chunk.to_payload()

                    # Upsert (dense only, named vector)
                    client.upsert(
                        collection_name=Config.DOCS_COLLECTION,
                        points=[PointStruct(id=point_id, vector={"dense": dense}, payload=payload)],
                    )
                    upserted += 1

                    # Progress
                    if (i + 1) % 10 == 0:
                        logger.info(f"  {i + 1}/{len(docs_chunks)} ({(i+1)/len(docs_chunks)*100:.1f}%)")
                        ckpt.data = {"processed": i + 1, "upserted": upserted}
                        ckpt.save()

                    # GC
                    if (i + 1) % 20 == 0:
                        gc.collect()

                except Exception as e:
                    stats["failed"] += 1
                    logger.error(f"Chunk {i} failed: {e}")
                    continue

            stats["upserted_docs"] = upserted
            ckpt.delete()
            logger.info(f"✓ Docs: {upserted}/{len(docs_chunks)}")

        # Ingest code
        code_chunks = [c for c in all_chunks if c.chunk_type == "code"]
        if code_chunks and Config.CODE_COLLECTION in collections:
            ckpt = Checkpoint(checkpoint_dir / "code.json")
            if reset:
                ckpt.data = {}
            start_idx = ckpt.data.get("processed", 0)
            logger.info(f"Ingesting {len(code_chunks)} code chunks (from {start_idx})...")

            upserted = ckpt.data.get("upserted", 0)
            for i, chunk in enumerate(code_chunks[start_idx:], start=start_idx):
                try:
                    dense = embedder.embed(chunk.text)

                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
                    payload = chunk.to_payload()

                    client.upsert(
                        collection_name=Config.CODE_COLLECTION,
                        points=[PointStruct(id=point_id, vector={"dense": dense}, payload=payload)],
                    )
                    upserted += 1

                    if (i + 1) % 10 == 0:
                        logger.info(f"  {i + 1}/{len(code_chunks)}")
                        ckpt.data = {"processed": i + 1, "upserted": upserted}
                        ckpt.save()

                    if (i + 1) % 20 == 0:
                        gc.collect()

                except Exception as e:
                    stats["failed"] += 1
                    logger.error(f"Code chunk {i} failed: {e}")
                    continue

            stats["upserted_code"] = upserted
            ckpt.delete()
            logger.info(f"✓ Code: {upserted}/{len(code_chunks)}")

        stats["end"] = datetime.now(timezone.utc).isoformat()
        logger.info("="*50)
        logger.info(f"COMPLETE: {stats['upserted_docs'] + stats['upserted_code']}/{stats['total']} chunks")
        logger.info("="*50)

        return {"ok": True, "stats": stats}

    except Exception as e:
        import traceback
        stats["end"] = datetime.now(timezone.utc).isoformat()
        logger.error(f"Failed: {e}")
        logger.error(traceback.format_exc())
        return {"ok": False, "error": str(e), "stats": stats}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", "-p", type=Path, default=Config.DOCS_FILE)
    parser.add_argument("--collection", "-c", choices=["docs", "code", "both"], default="both")
    parser.add_argument("--reset", "-r", action="store_true")
    args = parser.parse_args()

    result = ingest(args.path, reset=args.reset, collection=args.collection)
    sys.exit(0 if result.get("ok") else 1)
