"""
Hybrid retrieval: dense (nomic-embed-text-v1.5) + sparse (BM25 via fastembed).

Two retrieval paradigms complement each other:
  Dense  — captures semantic meaning, good for paraphrasing and concept matching
  Sparse — BM25, captures exact keyword/token matches (error codes, config flags, names)

OLake docs have many exact technical terms (binlog_format, pgoutput, wal_level) that
benefit hugely from sparse retrieval. Hybrid combines both via Qdrant's native
Prefetch + FusionQuery(RRF) mechanism.

Collection schema (after migration):
  vectors_config       = {"dense": VectorParams(size=768, distance=COSINE)}
  sparse_vectors_config= {"sparse": SparseVectorParams(...)}

Re-index required when migrating from old unnamed-vector collections.
"""

from __future__ import annotations
import logging
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Filter, FieldCondition, MatchValue,
    SparseVector, Prefetch, FusionQuery, Fusion,
)

from config import Config
from embedder import embed_queries, embed_query
from indexer import _client

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sparse (BM25) embedder — lazy-loaded, cached
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_sparse_model():
    """Load BM25 sparse encoder (fastembed). ~10 MB model, CPU-only."""
    try:
        from fastembed import SparseTextEmbedding
        log.info("Loading BM25 sparse encoder (Qdrant/bm25)...")
        model = SparseTextEmbedding(model_name="Qdrant/bm25")
        log.info("BM25 encoder ready ✓")
        return model
    except ImportError:
        log.warning("fastembed not installed — sparse search disabled. Run: pip install fastembed")
        return None
    except Exception as e:
        log.warning(f"BM25 encoder load failed: {e} — sparse search disabled")
        return None


def embed_sparse(texts: List[str], is_query: bool = False) -> List[Optional[SparseVector]]:
    """
    Encode texts as BM25 sparse vectors for Qdrant.
    Returns None per-item when fastembed is unavailable.
    """
    model = _get_sparse_model()
    if model is None:
        return [None] * len(texts)
    try:
        if is_query:
            embeddings = list(model.query_embed(texts))
        else:
            embeddings = list(model.embed(texts))
        out = []
        for emb in embeddings:
            ids = emb.indices.tolist() if hasattr(emb.indices, "tolist") else list(emb.indices)
            vals = emb.values.tolist() if hasattr(emb.values, "tolist") else list(emb.values)
            out.append(SparseVector(indices=ids, values=vals) if ids else None)
        return out
    except Exception as e:
        log.warning(f"Sparse embed failed: {e}")
        return [None] * len(texts)


def embed_sparse_for_index(texts: List[str]) -> List[Optional[SparseVector]]:
    """Encode document texts for indexing (BM25 passage encoding)."""
    return embed_sparse(texts, is_query=False)


def embed_sparse_query(text: str) -> Optional[SparseVector]:
    """Encode a single query text for BM25 sparse search."""
    results = embed_sparse([text], is_query=True)
    return results[0] if results else None


def sparse_is_ready() -> bool:
    return _get_sparse_model() is not None


# ---------------------------------------------------------------------------
# Collection schema detection
# ---------------------------------------------------------------------------

def _uses_named_vectors(collection: str) -> bool:
    """True if the collection uses named 'dense' vectors (new hybrid schema)."""
    try:
        client = _client()
        info = client.get_collection(collection)
        cfg = info.config.params.vectors
        return isinstance(cfg, dict) and "dense" in cfg
    except Exception:
        return False


def _has_sparse_vectors(collection: str) -> bool:
    """True if the collection has sparse 'sparse' vector config."""
    try:
        client = _client()
        info = client.get_collection(collection)
        sparse_cfg = info.config.params.sparse_vectors_config
        return sparse_cfg is not None and "sparse" in sparse_cfg
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class SearchResult:
    """A single retrieved chunk with its score."""
    __slots__ = ("chunk_id", "text", "doc_url", "title", "section",
                 "subsection", "subsubsection", "connector", "sync_mode",
                 "destination", "chunk_type", "tags", "score", "source")

    def __init__(self, payload: dict, score: float, source: str):
        self.chunk_id      = payload.get("chunk_id", "")
        self.text          = payload.get("text", "")
        self.doc_url       = payload.get("doc_url", "https://olake.io/docs/")
        self.title         = payload.get("subsection") or payload.get("section") or "OLake Docs"
        self.section       = payload.get("section", "")
        self.subsection    = payload.get("subsection", "")
        self.subsubsection = payload.get("subsubsection", "")
        self.connector     = payload.get("connector", "")
        self.sync_mode     = payload.get("sync_mode", "")
        self.destination   = payload.get("destination", "")
        self.chunk_type    = payload.get("chunk_type", "prose")
        self.tags          = payload.get("tags", "")
        self.score         = score
        self.source        = source

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ---------------------------------------------------------------------------
# Qdrant filter builder
# ---------------------------------------------------------------------------

def _build_filter(connector="", destination="", sync_mode="") -> Optional[Filter]:
    must = []
    if connector:
        must.append(FieldCondition(key="connector", match=MatchValue(value=connector)))
    if destination:
        must.append(FieldCondition(key="destination", match=MatchValue(value=destination)))
    if sync_mode:
        must.append(FieldCondition(key="sync_mode", match=MatchValue(value=sync_mode)))
    return Filter(must=must) if must else None


# ---------------------------------------------------------------------------
# Core search: hybrid (dense + sparse) or dense-only fallback
# ---------------------------------------------------------------------------

def _hybrid_search_collection(
    queries: List[str],
    collection: str,
    top_k: int,
    payload_filter: Optional[Filter] = None,
) -> List[SearchResult]:
    """
    Hybrid search for a single collection using Qdrant's native Prefetch + FusionQuery.

    If the collection has sparse vectors → dense + sparse → RRF (native Qdrant fusion).
    If only dense vectors → multi-query dense search with application-level RRF.
    """
    client = _client()
    if not client.collection_exists(collection):
        return []

    source = "code" if collection == Config.CODE_COLLECTION else "docs"
    named  = _uses_named_vectors(collection)
    sparse = _has_sparse_vectors(collection) and sparse_is_ready()

    results: List[SearchResult] = []

    if sparse and named:
        # ── Full hybrid: Qdrant native Prefetch + FusionQuery(RRF) ───────
        # Use the primary query for the cross-collection fusion
        primary_query = queries[0]
        dense_vec = embed_query(primary_query)
        sparse_vec = embed_sparse_query(primary_query)

        prefetches = [
            Prefetch(query=dense_vec,  using="dense",  limit=top_k * 2, filter=payload_filter),
        ]
        if sparse_vec:
            prefetches.append(
                Prefetch(query=sparse_vec, using="sparse", limit=top_k * 2, filter=payload_filter)
            )

        hits = client.query_points(
            collection_name=collection,
            prefetch=prefetches,
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
        ).points

        for hit in hits:
            if hit.score >= Config.DOC_RELEVANCE_THRESHOLD:
                results.append(SearchResult(hit.payload, hit.score, source))

        # Run additional queries as dense-only and merge via app-level RRF
        if len(queries) > 1:
            extra = _dense_multi_query(queries[1:], collection, top_k, payload_filter, named, source)
            results = _app_rrf_merge(results, extra, top_k)

    else:
        # ── Dense-only fallback (old collections or fastembed not installed) ─
        results = _dense_multi_query(queries, collection, top_k * 2, payload_filter, named, source)
        results = results[:top_k]

    return results


def _dense_multi_query(
    queries: List[str],
    collection: str,
    top_k: int,
    payload_filter: Optional[Filter],
    named: bool,
    source: str,
) -> List[SearchResult]:
    """Dense multi-query search with app-level RRF merge."""
    client = _client()
    rrf_k = Config.RRF_K
    rrf_scores: Dict[str, float] = {}
    best_payload: Dict[str, dict] = {}

    for query in queries[:4]:
        vec = embed_query(query)
        kwargs = dict(
            collection_name=collection,
            query=vec,
            query_filter=payload_filter,
            limit=top_k,
            with_payload=True,
        )
        if named:
            kwargs["using"] = "dense"
        try:
            hits = client.query_points(**kwargs).points
        except Exception as e:
            log.warning(f"Dense query failed: {e}")
            continue

        for rank, hit in enumerate(hits, 1):
            if hit.score < Config.DOC_RELEVANCE_THRESHOLD:
                continue
            cid = hit.payload.get("chunk_id", str(hit.id))
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            if cid not in best_payload or hit.score > best_payload.get(cid + "_score", -1):
                best_payload[cid] = hit.payload
                best_payload[cid + "_score"] = hit.score

    sorted_ids = sorted(rrf_scores, key=rrf_scores.__getitem__, reverse=True)
    return [
        SearchResult(best_payload[cid], min(rrf_scores[cid] * rrf_k, 1.0), source)
        for cid in sorted_ids[:top_k]
    ]


def _app_rrf_merge(
    *lists: List[SearchResult],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
) -> List[SearchResult]:
    """Application-level RRF merge across multiple result lists."""
    rrf_k = Config.RRF_K
    scores: Dict[str, float] = {}
    best: Dict[str, SearchResult] = {}
    for lst in lists:
        for rank, r in enumerate(lst, 1):
            scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            if r.chunk_id not in best or r.score > best[r.chunk_id].score:
                best[r.chunk_id] = r
    sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)
    merged = []
    for cid in sorted_ids[:top_k]:
        r = best[cid]
        r.score = min(scores[cid] * rrf_k, 1.0)
        merged.append(r)
    return merged


# ---------------------------------------------------------------------------
# Public search API  (drop-in replacement for old retriever.py)
# ---------------------------------------------------------------------------

def search_docs(
    queries: List[str],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
) -> List[dict]:
    filt = _build_filter(connector=connector, destination=destination, sync_mode=sync_mode)
    results = _hybrid_search_collection(queries, Config.DOCS_COLLECTION, top_k=top_k, payload_filter=filt)
    log.info(
        f"search_docs(hybrid): {len(results)} results "
        f"[conn={connector!r}, dest={destination!r}] queries={queries[:2]!r}"
    )
    return [r.to_dict() for r in results]


def search_code(queries: List[str], top_k: int = 3) -> List[dict]:
    results = _hybrid_search_collection(queries, Config.CODE_COLLECTION, top_k=top_k)
    return [r.to_dict() for r in results]


def hybrid_search(
    queries: List[str],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
    **filters,
) -> List[dict]:
    """Cross-collection hybrid search (docs + code)."""
    filt = _build_filter(**{k: v for k, v in filters.items()
                            if k in ("connector", "destination", "sync_mode")})
    docs = _hybrid_search_collection(queries, Config.DOCS_COLLECTION, top_k=top_k, payload_filter=filt)
    code = _hybrid_search_collection(queries, Config.CODE_COLLECTION, top_k=3)
    merged = _app_rrf_merge(docs, code, top_k=top_k)
    return [r.to_dict() for r in merged]
