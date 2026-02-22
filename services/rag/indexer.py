"""
Qdrant index management for the RAG service.

Supports:
  - Local file path (dev): QDRANT_URL=./qdrant_db
  - Docker: QDRANT_URL=http://qdrant:6333
  - Qdrant Cloud: QDRANT_URL=https://xyz.cloud.qdrant.io + QDRANT_API_KEY

Dense vectors only. Full-text index on text field using TokenizerType.WORD.
"""

from __future__ import annotations
import logging
import uuid
import sys
from pathlib import Path
from typing import List

# Support both direct run and module import
try:
    from config import Config
    from embedder import vector_size
except ImportError:
    # Add services/rag to path for module imports
    rag_path = Path(__file__).parent
    sys.path.insert(0, str(rag_path))
    from config import Config
    from embedder import vector_size

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    OptimizersConfigDiff,
    TextIndexParams,
    TokenizerType,
)

log = logging.getLogger(__name__)

_VECTOR_SIZE: int | None = None
_QDRANT_CLIENT: QdrantClient | None = None


def _client() -> QdrantClient:
    """Create a Qdrant client from config. Thread-safe (clients are stateless)."""
    global _QDRANT_CLIENT
    if _QDRANT_CLIENT is not None:
        return _QDRANT_CLIENT

    url = Config.QDRANT_URL
    api_key = Config.QDRANT_API_KEY

    if url.startswith("http"):
        _QDRANT_CLIENT = QdrantClient(url=url, api_key=api_key)
    else:
        # Local file path
        _QDRANT_CLIENT = QdrantClient(path=url)
    return _QDRANT_CLIENT


def _vec_size() -> int:
    global _VECTOR_SIZE
    if _VECTOR_SIZE is None:
        _VECTOR_SIZE = vector_size()
    return _VECTOR_SIZE


# ---------------------------------------------------------------------------
# Collection management
# ---------------------------------------------------------------------------

def ensure_collection(name: str, drop_first: bool = False) -> None:
    """Create collection if it doesn't exist. Optionally recreate from scratch."""
    client = _client()

    if drop_first and client.collection_exists(name):
        client.delete_collection(name)
        log.info(f"Dropped collection '{name}'")

    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(
                    size=_vec_size(),
                    distance=Distance.COSINE,
                )
            },
            # Dense vectors only - no sparse_vectors_config
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=0,  # index immediately
            ),
        )
        log.info(f"Created collection '{name}'")

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
        log.info(f"Created full-text index on 'text' field for collection '{name}'")


def list_collections() -> List[str]:
    """Return names of all existing Qdrant collections."""
    return [c.name for c in _client().get_collections().collections]


def collection_stats(name: str) -> dict:
    """Return basic stats about a collection."""
    client = _client()
    if not client.collection_exists(name):
        return {"exists": False}
    info = client.get_collection(name)

    # Handle both dict and object formats for vectors
    vectors = info.config.params.vectors
    try:
        if isinstance(vectors, dict):
            first_vec = next(iter(vectors.values()), None)
            if first_vec:
                if isinstance(first_vec, dict):
                    vector_size = first_vec.get('size', 'N/A')
                    distance = first_vec.get('distance', 'N/A')
                else:
                    vector_size = getattr(first_vec, 'size', 'N/A')
                    distance = getattr(first_vec, 'distance', 'N/A')
            else:
                vector_size = 'N/A'
                distance = 'N/A'
        else:
            vector_size = getattr(vectors, 'size', 'N/A')
            distance = getattr(vectors, 'distance', 'N/A')
    except Exception:
        vector_size = 'N/A'
        distance = 'N/A'

    return {
        "exists": True,
        "count": info.points_count,
        "vector_size": vector_size,
        "distance": str(distance),
    }


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

def upsert_chunks(collection: str, chunks: list, vectors: List[List[float]]) -> int:
    """
    Upsert chunk documents into Qdrant.

    Args:
        collection: Collection name
        chunks:     List of Chunk dataclass instances
        vectors:    Parallel list of dense embedding vectors

    Returns:
        Number of points upserted
    """
    client = _client()
    points = []

    for chunk, vec in zip(chunks, vectors):
        # Use chunk_id as deterministic UUID so re-ingesting is idempotent
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
        payload = chunk.to_payload()  # dict with text + all metadata fields

        points.append(PointStruct(id=point_id, vector={"dense": vec}, payload=payload))

    BATCH = 64
    for i in range(0, len(points), BATCH):
        client.upsert(collection_name=collection, points=points[i : i + BATCH])
        log.info(f"  Upserted batch {i // BATCH + 1} ({len(points[i : i + BATCH])} chunks)")

    return len(points)


# ---------------------------------------------------------------------------
# Point lookup
# ---------------------------------------------------------------------------

def get_chunk(collection: str, chunk_id: str) -> dict | None:
    """Retrieve a single chunk by its chunk_id (payload field, not point ID)."""
    client = _client()
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    results = client.scroll(
        collection_name=collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="chunk_id", match=MatchValue(value=chunk_id))]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    hits, _ = results
    if hits:
        return hits[0].payload
    return None
