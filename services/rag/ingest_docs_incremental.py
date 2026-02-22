#!/usr/bin/env python3
"""
OLake Documentation Ingestion Script - Incremental Mode.

Processes chunks ONE AT A TIME to prevent Python crashes from multiprocessing.
This is slower but much more stable, especially on macOS.

Features:
  - Single-threaded embedding (no multiprocessing)
  - One chunk at a time processing
  - Checkpoint-based crash recovery
  - Progress tracking
  - Memory efficient

Usage:
  # Full ingestion with reset
  python ingest_docs_incremental.py --reset

  # Resume from checkpoint
  python ingest_docs_incremental.py
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Disable ALL parallelism BEFORE any imports
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import Config

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHECKPOINT_DIR = os.getenv("CHECKPOINT_DIR", "./.ingest_checkpoints")
LOG_FILE = os.getenv("INGEST_LOG_FILE", "./ingest.log")
MEMORY_CHECK_INTERVAL = 50  # Check memory every N chunks

# Collection names
DOCS_COLLECTION = Config.DOCS_COLLECTION
CODE_COLLECTION = Config.CODE_COLLECTION

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(log_file: Optional[str] = None) -> logging.Logger:
    """Configure logging."""
    logger = logging.getLogger("ingest")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)

    return logger


logger = setup_logging(LOG_FILE)


# ---------------------------------------------------------------------------
# Checkpoint management
# ---------------------------------------------------------------------------

class CheckpointManager:
    """Manages checkpoint files for crash recovery."""

    def __init__(self, checkpoint_dir: str = CHECKPOINT_DIR):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _checkpoint_path(self, name: str) -> Path:
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self.checkpoint_dir / f"{safe_name}.json"

    def load(self, name: str) -> Optional[Dict]:
        """Load checkpoint."""
        path = self._checkpoint_path(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def save(self, name: str, data: Dict) -> None:
        """Save checkpoint."""
        path = self._checkpoint_path(name)
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def delete(self, name: str) -> None:
        """Delete checkpoint."""
        path = self._checkpoint_path(name)
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Memory monitoring
# ---------------------------------------------------------------------------

def get_memory_mb() -> float:
    """Get current memory usage in MB."""
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return usage / (1024 * 1024)
        return usage / 1024
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Qdrant client
# ---------------------------------------------------------------------------

def get_qdrant_client():
    """Get Qdrant client."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams,
        OptimizersConfigDiff,
    )

    url = Config.QDRANT_URL
    api_key = Config.QDRANT_API_KEY

    if url.startswith("http"):
        return QdrantClient(url=url, api_key=api_key), VectorParams, OptimizersConfigDiff
    else:
        return QdrantClient(path=url), VectorParams, OptimizersConfigDiff


def ensure_collection(client, name: str, vector_size: int, drop_first: bool = False) -> None:
    """Create collection if needed."""
    from qdrant_client.models import Distance, TextIndexParams, TokenizerType
    VectorParams, OptimizersConfigDiff = get_qdrant_client()[1:]

    if drop_first and client.collection_exists(name):
        client.delete_collection(name)
        logger.info(f"Dropped collection: {name}")

    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config={"dense": VectorParams(size=vector_size, distance=Distance.COSINE)},
            # Dense vectors only - no sparse_vectors_config
            optimizers_config=OptimizersConfigDiff(indexing_threshold=0),
        )
        logger.info(f"Created collection: {name}")

        # Create full-text index on the text field
        client.create_payload_index(
            collection_name=name,
            field_name="text",
            field_schema=TextIndexParams(
                type="text",
                tokenizer=TokenizerType.WORD,
                lowercase=True,
                min_token_len=2,
                max_token_len=50,
            ),
        )
        logger.info(f"Created full-text index on 'text' field for collection: {name}")


# ---------------------------------------------------------------------------
# Embedding (single-threaded, one at a time)
# ---------------------------------------------------------------------------

def get_embedding_model():
    """Load embedding model (cached)."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    log = logging.getLogger(__name__)
    log.info(f"Loading embedding model: {Config.EMBED_MODEL}")

    tokenizer = AutoTokenizer.from_pretrained(
        Config.EMBED_MODEL,
        local_files_only=True,
        trust_remote_code=True,
    )
    model = AutoModel.from_pretrained(
        Config.EMBED_MODEL,
        local_files_only=True,
        trust_remote_code=True,
    )
    model.eval()
    log.info("Embedding model loaded")
    return model, tokenizer


def _mean_pooling(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean pooling over token embeddings."""
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    return sum_embeddings / sum_mask


def _normalize_embeddings(embeddings: torch.Tensor) -> torch.Tensor:
    """L2 normalize embeddings."""
    return torch.nn.functional.normalize(embeddings, p=2, dim=1)


def embed_single(model_tokenizer, text: str) -> List[float]:
    """Embed a single text."""
    model, tokenizer = model_tokenizer
    prefixed = "search_document: " + text

    encoded = tokenizer(
        prefixed,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )

    with torch.no_grad():
        outputs = model(**encoded)
        token_embeddings = outputs.last_hidden_state
        pooled = _mean_pooling(token_embeddings, encoded["attention_mask"])
        normalized = _normalize_embeddings(pooled)

    return normalized.cpu().tolist()


# ---------------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------------

def ingest_incremental(
    docs_path: Path,
    reset: bool = False,
    collection: str = "both",
) -> Dict:
    """
    Ingest documents one chunk at a time.

    This is slower but prevents crashes from multiprocessing issues.
    """
    stats = {
        "total_chunks": 0,
        "docs_chunks": 0,
        "code_chunks": 0,
        "upserted_docs": 0,
        "upserted_code": 0,
        "failed": 0,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": "",
        "errors": [],
    }

    try:
        # Validate source
        if not docs_path.exists():
            raise FileNotFoundError(f"Source not found: {docs_path}")

        logger.info(f"Starting incremental ingestion from {docs_path}")
        logger.info(f"Reset: {reset}, Collection: {collection}")

        # Load chunker and parse
        from chunker import parse_file

        logger.info("Parsing document...")
        all_chunks = parse_file(docs_path)
        stats["total_chunks"] = len(all_chunks)

        docs_chunks = [c for c in all_chunks if c.chunk_type != "code"]
        code_chunks = [c for c in all_chunks if c.chunk_type == "code"]

        stats["docs_chunks"] = len(docs_chunks)
        stats["code_chunks"] = len(code_chunks)

        logger.info(f"Parsed {len(all_chunks)} chunks ({len(docs_chunks)} docs, {len(code_chunks)} code)")

        # Initialize Qdrant
        client, VectorParams, OptimizersConfigDiff = get_qdrant_client()
        from qdrant_client.models import Distance

        # Get embedding model
        embed_model = get_embedding_model()

        # Get vector size from embedder module
        from embedder import vector_size
        vector_dim = vector_size()

        # Initialize collections
        if collection in ("both", "docs"):
            ensure_collection(client, DOCS_COLLECTION, vector_dim, drop_first=reset)
        if collection in ("both", "code"):
            ensure_collection(client, CODE_COLLECTION, vector_dim, drop_first=reset)

        # Checkpoint manager
        checkpoint_mgr = CheckpointManager(CHECKPOINT_DIR)

        # Ingest docs
        if collection in ("both", "docs") and docs_chunks:
            logger.info(f"\nIngesting {len(docs_chunks)} docs chunks...")
            upserted = _ingest_chunks_incremental(
                client=client,
                collection=DOCS_COLLECTION,
                chunks=docs_chunks,
                embed_model=embed_model,
                checkpoint_mgr=checkpoint_mgr,
                checkpoint_name="docs",
                reset=reset,
            )
            stats["upserted_docs"] = upserted

        # Ingest code
        if collection in ("both", "code") and code_chunks:
            logger.info(f"\nIngesting {len(code_chunks)} code chunks...")
            upserted = _ingest_chunks_incremental(
                client=client,
                collection=CODE_COLLECTION,
                chunks=code_chunks,
                embed_model=embed_model,
                checkpoint_mgr=checkpoint_mgr,
                checkpoint_name="code",
                reset=reset,
            )
            stats["upserted_code"] = upserted

        # Success
        stats["end_time"] = datetime.now(timezone.utc).isoformat()
        logger.info("\n" + "="*60)
        logger.info("INGESTION COMPLETE")
        logger.info("="*60)
        logger.info(f"Total chunks:     {stats['total_chunks']}")
        logger.info(f"Docs upserted:    {stats['upserted_docs']}")
        logger.info(f"Code upserted:    {stats['upserted_code']}")
        logger.info(f"Failed:           {stats['failed']}")

        return {"ok": True, "stats": stats}

    except Exception as e:
        stats["end_time"] = datetime.now(timezone.utc).isoformat()
        stats["errors"].append(str(e))
        logger.error(f"Ingestion failed: {e}")
        logger.error(traceback.format_exc())
        return {"ok": False, "error": str(e), "stats": stats}


def _ingest_chunks_incremental(
    client,
    collection: str,
    chunks: List,
    embed_model,
    checkpoint_mgr: CheckpointManager,
    checkpoint_name: str,
    reset: bool = False,
) -> int:
    """Ingest chunks one at a time."""
    from qdrant_client.models import PointStruct
    import uuid

    # Load checkpoint
    checkpoint = checkpoint_mgr.load(checkpoint_name)
    start_idx = 0

    if checkpoint and not reset:
        if checkpoint.get("status") == "completed":
            logger.info(f"Already completed ({checkpoint_name}), skipping")
            return checkpoint.get("upserted", 0)
        start_idx = checkpoint.get("processed", 0)
        logger.info(f"Resuming from chunk {start_idx}/{len(chunks)}")
    else:
        checkpoint = {
            "collection": collection,
            "total": len(chunks),
            "processed": 0,
            "upserted": 0,
            "failed": 0,
            "status": "running",
            "start_time": datetime.now(timezone.utc).isoformat(),
        }

    upserted = checkpoint.get("upserted", 0)
    failed = checkpoint.get("failed", 0)

    start_time = time.time()

    for i, chunk in enumerate(chunks[start_idx:], start=start_idx):
        try:
            # Progress report
            if (i + 1) % 10 == 0 or i == len(chunks) - 1:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                logger.info(f"Progress: {i + 1}/{len(chunks)} ({(i + 1) / len(chunks) * 100:.1f}%) | Rate: {rate:.2f} chunks/s")

            # Embed chunk (one at a time)
            text = chunk.text
            dense_vector = embed_single(embed_model, text)

            # Create point
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
            payload = chunk.to_payload()

            # Dense vectors only (named vector)
            client.upsert(
                collection_name=collection,
                points=[PointStruct(id=point_id, vector={"dense": dense_vector}, payload=payload)],
            )

            upserted += 1

            # Update checkpoint
            checkpoint["processed"] = i + 1
            checkpoint["upserted"] = upserted
            checkpoint_mgr.save(checkpoint_name, checkpoint)

            # Memory check and GC
            if (i + 1) % MEMORY_CHECK_INTERVAL == 0:
                mem_mb = get_memory_mb()
                logger.debug(f"Memory usage: {mem_mb:.1f} MB")
                gc.collect()

        except Exception as e:
            failed += 1
            logger.error(f"Chunk {i} failed: {e}")
            checkpoint["failed"] = failed
            checkpoint_mgr.save(checkpoint_name, checkpoint)
            continue

    # Cleanup
    checkpoint["status"] = "completed"
    checkpoint["end_time"] = datetime.now(timezone.utc).isoformat()
    checkpoint_mgr.save(checkpoint_name, checkpoint)
    checkpoint_mgr.delete(checkpoint_name)

    logger.info(f"✓ {collection}: {upserted}/{len(chunks)} chunks upserted")
    return upserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global LOG_FILE
    parser = argparse.ArgumentParser(description="Ingest OLake docs (incremental mode)")
    parser.add_argument("--path", "-p", type=Path, default=Config.DOCS_FILE, help="Docs file path")
    parser.add_argument("--collection", "-c", choices=["docs", "code", "both"], default="both")
    parser.add_argument("--reset", "-r", action="store_true", help="Reset collections first")
    parser.add_argument("--log-file", "-l", type=str, default=LOG_FILE, help="Log file path")

    args = parser.parse_args()

    LOG_FILE = args.log_file
    logger.handlers.clear()
    setup_logging(LOG_FILE)

    result = ingest_incremental(
        docs_path=args.path,
        reset=args.reset,
        collection=args.collection,
    )

    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
