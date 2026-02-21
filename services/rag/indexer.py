"""
Qdrant index management for the RAG service.

Supports:
  - Local file path (dev): QDRANT_URL=./qdrant_db
  - Docker: QDRANT_URL=http://qdrant:6333
  - Qdrant Cloud: QDRANT_URL=https://xyz.cloud.qdrant.io + QDRANT_API_KEY
"""

from __future__ import annotations
import logging
import uuid
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    OptimizersConfigDiff,
)

from config import Config
from embedder import vector_size

log = logging.getLogger(__name__)

_VECTOR_SIZE: int | None = None


def _client() -> QdrantClient:
    """Create a Qdrant client from config. Thread-safe (clients are stateless)."""
    url = Config.QDRANT_URL
    api_key = Config.QDRANT_API_KEY

    if url.startswith("http"):
        return QdrantClient(url=url, api_key=api_key)
    # Local file path
    return QdrantClient(path=url)


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
            vectors_config=VectorParams(
                size=_vec_size(),
                distance=Distance.COSINE,
            ),
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=0,  # index immediately
            ),
        )
        log.info(f"Created collection '{name}'")


def list_collections() -> List[str]:
    """Return names of all existing Qdrant collections."""
    return [c.name for c in _client().get_collections().collections]


def collection_stats(name: str) -> dict:
    """Return basic stats about a collection."""
    client = _client()
    if not client.collection_exists(name):
        return {"exists": False}
    info = client.get_collection(name)
    return {
        "exists": True,
        "count": info.points_count,
        "vector_size": info.config.params.vectors.size,
        "distance": str(info.config.params.vectors.distance),
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
        vectors:    Parallel list of embedding vectors

    Returns:
        Number of points upserted
    """
    client = _client()
    points = []
    for chunk, vec in zip(chunks, vectors):
        # Use chunk_id as deterministic UUID so re-ingesting is idempotent
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
        payload = chunk.to_payload()          # dict with text + all metadata fields
        points.append(PointStruct(id=point_id, vector=vec, payload=payload))

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
