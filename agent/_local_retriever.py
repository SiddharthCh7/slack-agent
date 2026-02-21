"""
Local Qdrant Vector Retriever — dev/test fallback when the RAG HTTP service is down.

Uses the same embedding model and Qdrant database as the RAG service, but queries
directly from within the agent process. This gives proper semantic search without
requiring the separate RAG microservice to be running.

Production flow:   agent → RAG service HTTP → Qdrant
Test/dev fallback: agent → this module      → Qdrant (same data, same quality)

Supports both old-style collections (single unnamed vector) and new hybrid collections
(named "dense" + sparse "sparse" vectors).
"""

from __future__ import annotations
import logging
import os
from functools import lru_cache
from typing import List, Optional

log = logging.getLogger(__name__)

# Mirror the RAG service config via env vars
QDRANT_URL      = os.getenv("QDRANT_URL", "./qdrant_db")
QDRANT_API_KEY  = os.getenv("QDRANT_API_KEY")
EMBED_MODEL     = os.getenv("EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
DOCS_COLLECTION = os.getenv("DOCS_COLLECTION", "olake_docs")
CODE_COLLECTION = os.getenv("CODE_COLLECTION", "olake_code")

_QUERY_PREFIX = "search_query: "


@lru_cache(maxsize=1)
def _get_embed_model():
    from sentence_transformers import SentenceTransformer
    log.info(f"[LocalRetriever] Loading embedding model: {EMBED_MODEL}")
    m = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
    log.info("[LocalRetriever] Embedding model ready ✓")
    return m


@lru_cache(maxsize=1)
def _get_client():
    from qdrant_client import QdrantClient
    if QDRANT_URL.startswith("http"):
        return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    return QdrantClient(path=QDRANT_URL)


def _embed_query(text: str) -> List[float]:
    model = _get_embed_model()
    vec = model.encode(_QUERY_PREFIX + text, normalize_embeddings=True)
    return vec.tolist()


def _collection_uses_named_vectors(collection: str) -> bool:
    """Check whether the collection stores vectors under the name 'dense'."""
    try:
        client = _get_client()
        info = client.get_collection(collection)
        cfg = info.config.params.vectors
        # Named vectors: dict with keys; unnamed: VectorParams directly
        return isinstance(cfg, dict)
    except Exception:
        return False


def _vector_search(
    queries: List[str],
    collection: str,
    top_k: int,
    payload_filter=None,
) -> List[dict]:
    """
    Multi-query dense vector search with Reciprocal Rank Fusion (RRF) merge.
    Detects whether the collection uses named ("dense") or unnamed vectors.
    """
    client = _get_client()
    try:
        if not client.collection_exists(collection):
            log.warning(f"[LocalRetriever] Collection '{collection}' not found")
            return []
    except Exception:
        return []

    named = _collection_uses_named_vectors(collection)
    rrf_scores: dict[str, tuple] = {}   # chunk_id → (rrf_score, payload)

    for q in queries[:4]:                # cap to 4 queries
        vec = _embed_query(q)
        try:
            kwargs = dict(
                collection_name=collection,
                query=vec,
                query_filter=payload_filter,
                limit=top_k * 3,
                with_payload=True,
            )
            if named:
                kwargs["using"] = "dense"
            hits = client.query_points(**kwargs).points
        except Exception as e:
            log.warning(f"[LocalRetriever] query failed for '{q[:40]}': {e}")
            continue

        for rank, hit in enumerate(hits, 1):
            cid = hit.payload.get("chunk_id", str(hit.id))
            rrf_k = 10
            rrf_contribution = 1.0 / (rrf_k + rank)
            if cid in rrf_scores:
                old_score, payload = rrf_scores[cid]
                rrf_scores[cid] = (old_score + rrf_contribution, payload)
            else:
                rrf_scores[cid] = (rrf_contribution, {**hit.payload, "chunk_id": cid})

    results = sorted(rrf_scores.values(), key=lambda x: x[0], reverse=True)
    out = []
    for score, payload in results[:top_k]:
        out.append({**payload, "score": score})
    return out


def search_docs(
    queries: List[str],
    top_k: int = 6,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
) -> List[dict]:
    """Dense vector search over the docs collection."""
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    must = []
    if connector:
        must.append(FieldCondition(key="connector", match=MatchValue(value=connector)))
    if destination:
        must.append(FieldCondition(key="destination", match=MatchValue(value=destination)))
    if sync_mode:
        must.append(FieldCondition(key="sync_mode", match=MatchValue(value=sync_mode)))
    flt = Filter(must=must) if must else None
    results = _vector_search(queries, DOCS_COLLECTION, top_k=top_k, payload_filter=flt)
    for r in results:
        r.setdefault("source", "docs")
    return results


def search_code(queries: List[str], top_k: int = 3) -> List[dict]:
    """Dense vector search over the code collection."""
    results = _vector_search(queries, CODE_COLLECTION, top_k=top_k)
    for r in results:
        r.setdefault("source", "code")
    return results
