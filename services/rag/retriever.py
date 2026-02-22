"""
Dense retrieval with Qdrant full-text index.

Query/Retrieval strategy:
  1. Run dense search with a full-text MatchText keyword pre-filter on the text field
  2. If that returns zero results, fall back to pure dense search with no filter
  3. Return top-K from whichever path succeeds

No sparse vectors, no BM25, no fastembed.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Filter, FieldCondition, MatchValue, MatchText,
)

from config import Config
from embedder import embed_query, embed_queries
from indexer import _client

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class SearchResult:
    """A single retrieved chunk with its score."""
    __slots__ = ("chunk_id", "text", "doc_url", "title", "section",
                 "subsection", "subsubsection", "section_path", "connector",
                 "sync_mode", "destination", "chunk_type", "tags", "score", "source",
                 "doc_path", "doc_category", "internal_links", "external_links",
                 "anchor_links", "is_redirect")

    def __init__(self, payload: dict, score: float, source: str):
        self.chunk_id      = payload.get("chunk_id", "")
        self.text          = payload.get("text", "")
        self.doc_url       = payload.get("doc_url", "https://olake.io/docs/")
        self.title         = payload.get("subsection") or payload.get("section") or "OLake Docs"
        self.section       = payload.get("section", "")
        self.subsection    = payload.get("subsection", "")
        self.subsubsection = payload.get("subsubsection", "")
        self.section_path  = payload.get("section_path", "")
        self.connector     = payload.get("connector", "")
        self.sync_mode     = payload.get("sync_mode", "")
        self.destination   = payload.get("destination", "")
        self.chunk_type    = payload.get("chunk_type", "prose")
        self.tags          = payload.get("tags", "")
        self.score         = score
        self.source        = source
        # New fields for link expansion
        self.doc_path      = payload.get("doc_path", "")
        self.doc_category  = payload.get("doc_category", "")
        self.is_redirect   = payload.get("is_redirect", False)
        # Parse link fields from JSON strings
        import json
        try:
            self.internal_links = json.loads(payload.get("internal_links", "[]")) if payload.get("internal_links") else []
        except (json.JSONDecodeError, TypeError):
            self.internal_links = []
        try:
            self.external_links = json.loads(payload.get("external_links", "[]")) if payload.get("external_links") else []
        except (json.JSONDecodeError, TypeError):
            self.external_links = []
        try:
            self.anchor_links = json.loads(payload.get("anchor_links", "[]")) if payload.get("anchor_links") else []
        except (json.JSONDecodeError, TypeError):
            self.anchor_links = []

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


def _build_text_filter(keyword: str) -> Optional[Filter]:
    """Build a MatchText filter on the text field for full-text search."""
    if not keyword:
        return None
    return Filter(must=[FieldCondition(key="text", match=MatchText(text=keyword))])


def _merge_filters(*filters: Optional[Filter]) -> Optional[Filter]:
    """Merge multiple filters into one."""
    all_must = []
    for f in filters:
        if f and f.must:
            all_must.extend(f.must)
    return Filter(must=all_must) if all_must else None


# ---------------------------------------------------------------------------
# Core search: dense with full-text pre-filter, fallback to pure dense
# ---------------------------------------------------------------------------

def _extract_keyword(query: str) -> str:
    """Extract a keyword from the query for full-text filtering."""
    # Simple heuristic: use the first significant word
    words = query.lower().split()
    for word in words:
        # Skip common stop words
        if word not in {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
                        "have", "has", "had", "do", "does", "did", "will", "would", "could",
                        "should", "may", "might", "must", "shall", "can", "need", "to", "of",
                        "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
                        "and", "or", "not", "if", "else", "than", "but", "so"}:
            if len(word) >= 3:
                return word
    return ""


def _dense_search_with_fallback(
    query: str,
    collection: str,
    top_k: int,
    payload_filter: Optional[Filter] = None,
) -> List[SearchResult]:
    """
    Dense search with full-text pre-filter, fallback to pure dense.

    Strategy:
    1. Extract keyword from query
    2. Run dense search with MatchText filter on text field
    3. If zero results, fall back to pure dense search with no text filter
    4. Return top-K from whichever path succeeds
    """
    client = _client()
    if not client.collection_exists(collection):
        return []

    source = "code" if collection == Config.CODE_COLLECTION else "docs"

    # Embed query
    query_vec = embed_query(query)

    # Extract keyword for full-text filter
    keyword = _extract_keyword(query)
    text_filter = _build_text_filter(keyword) if keyword else None

    # Combine with payload filter
    combined_filter = _merge_filters(payload_filter, text_filter)

    # Try dense search with full-text pre-filter first
    results = []
    if combined_filter:
        try:
            hits = client.query_points(
                collection_name=collection,
                query=query_vec,
                query_filter=combined_filter,
                limit=top_k,
                with_payload=True,
                using="dense",
            ).points

            for hit in hits:
                if hit.score >= Config.DOC_RELEVANCE_THRESHOLD:
                    results.append(SearchResult(hit.payload, hit.score, source))

        except Exception as e:
            log.warning(f"Dense search with text filter failed: {e}")

    # Fallback to pure dense search if no results
    if not results:
        try:
            hits = client.query_points(
                collection_name=collection,
                query=query_vec,
                query_filter=payload_filter,  # Only metadata filters, no text filter
                limit=top_k,
                with_payload=True,
                using="dense",
            ).points

            results = []
            for hit in hits:
                if hit.score >= Config.DOC_RELEVANCE_THRESHOLD:
                    results.append(SearchResult(hit.payload, hit.score, source))

        except Exception as e:
            log.warning(f"Pure dense search failed: {e}")

    return results


def _prefer_detail_over_summary(
    results: List[SearchResult],
    threshold: float = Config.DOC_RELEVANCE_THRESHOLD,
) -> List[SearchResult]:
    """
    Apply retrieval rule: when both summary (§12) and detail chunks score above
    threshold, prefer detail chunks. Summary chunks are only returned as fallback.
    """
    if not results:
        return results

    # Check if any detail chunk scores above threshold
    has_high_scoring_detail = any(
        r.chunk_type != "summary" and r.score >= threshold
        for r in results
    )

    if has_high_scoring_detail:
        # Filter out summary chunks
        filtered = [r for r in results if r.chunk_type != "summary"]
        if filtered:
            return filtered

    return results


# ---------------------------------------------------------------------------
# Public search API
# ---------------------------------------------------------------------------

def search_docs(
    queries: List[str],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
) -> List[dict]:
    """Search docs using dense embeddings with full-text pre-filter."""
    filt = _build_filter(connector=connector, destination=destination, sync_mode=sync_mode)

    # Use the first query for search (primary query)
    primary_query = queries[0] if queries else ""
    results = _dense_search_with_fallback(
        primary_query, Config.DOCS_COLLECTION, top_k=top_k, payload_filter=filt
    )

    # Apply "prefer detail over summary" rule
    results = _prefer_detail_over_summary(results)

    log.info(
        f"search_docs(dense+fulltext): {len(results)} results "
        f"[conn={connector!r}, dest={destination!r}] query={primary_query!r}"
    )
    return [r.to_dict() for r in results]


def search_code(queries: List[str], top_k: int = 3) -> List[dict]:
    """Search code using dense embeddings with full-text pre-filter."""
    primary_query = queries[0] if queries else ""
    results = _dense_search_with_fallback(primary_query, Config.CODE_COLLECTION, top_k=top_k)
    return [r.to_dict() for r in results]


def hybrid_search(
    queries: List[str],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
    **filters,
) -> List[dict]:
    """Cross-collection dense search (docs + code)."""
    filt = _build_filter(**{k: v for k, v in filters.items()
                            if k in ("connector", "destination", "sync_mode")})

    primary_query = queries[0] if queries else ""
    docs = _dense_search_with_fallback(primary_query, Config.DOCS_COLLECTION, top_k=top_k, payload_filter=filt)
    code = _dense_search_with_fallback(primary_query, Config.CODE_COLLECTION, top_k=3)

    # Merge results by score
    merged = docs + code
    merged.sort(key=lambda r: r.score, reverse=True)
    merged = merged[:top_k]

    # Apply "prefer detail over summary" rule
    merged = _prefer_detail_over_summary(merged)

    return [r.to_dict() for r in merged]


# ---------------------------------------------------------------------------
# Link expansion and related document retrieval
# ---------------------------------------------------------------------------

def search_by_doc_paths(
    doc_paths: List[str],
    collection: str = None,
    top_k_per_path: int = 5,
) -> List[SearchResult]:
    """
    Retrieve chunks by their doc_path field.

    Useful for fetching related documents discovered via link expansion.

    Args:
        doc_paths: List of doc_path values (e.g., "connectors/postgres/config.mdx")
        collection: Collection name (defaults to DOCS_COLLECTION)
        top_k_per_path: Max chunks to retrieve per doc_path

    Returns:
        List of SearchResult objects
    """
    if collection is None:
        collection = Config.DOCS_COLLECTION

    client = _client()
    if not client.collection_exists(collection):
        return []

    all_results: List[SearchResult] = []
    source = "code" if collection == Config.CODE_COLLECTION else "docs"

    for doc_path in doc_paths[:10]:  # Limit to prevent abuse
        if not doc_path:
            continue

        try:
            filt = Filter(must=[FieldCondition(key="doc_path", match=MatchValue(value=doc_path))])

            # Dense search with empty query to get all matching chunks
            hits = client.query_points(
                collection_name=collection,
                query_filter=filt,
                limit=top_k_per_path,
                with_payload=True,
                using="dense",
            ).points

            for hit in hits:
                result = SearchResult(hit.payload, hit.score, source)
                # Avoid duplicates
                if not any(r.chunk_id == result.chunk_id for r in all_results):
                    all_results.append(result)

        except Exception as e:
            log.warning(f"Failed to fetch doc_path {doc_path}: {e}")

    return all_results


def expand_with_linked_docs(
    results: List[SearchResult],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
    max_expanded: int = 3,
    min_score: float = 0.3,
) -> List[SearchResult]:
    """
    Expand search results by fetching documents linked from top results.

    Strategy:
    1. Take top N results with score >= min_score
    2. Extract internal_links from those chunks
    3. Fetch chunks from linked documents
    4. Re-rank combined results

    Args:
        results: Initial search results
        top_k: Final number of results to return
        max_expanded: Max number of linked docs to fetch
        min_score: Minimum score for a result to be considered for expansion

    Returns:
        Expanded and re-ranked list of SearchResult
    """
    if not results:
        return results

    # Filter high-scoring results for link extraction
    high_scoring = [r for r in results if r.score >= min_score and not r.is_redirect]

    if not high_scoring:
        return results

    # Collect unique internal links from top results
    linked_paths: List[str] = []
    seen_paths = set()

    for result in high_scoring[:5]:  # Check top 5 results
        if result.internal_links:
            for link in result.internal_links[:5]:  # Limit links per chunk
                # Clean link (remove anchors for path matching)
                path = link.split("#")[0] if "#" in link else link
                if path and path not in seen_paths and path.endswith(".mdx"):
                    linked_paths.append(path)
                    seen_paths.add(path)

    if not linked_paths:
        return results

    # Fetch linked documents
    log.info(f"Expanding with {len(linked_paths[:max_expanded])} linked docs")
    linked_results = search_by_doc_paths(
        linked_paths[:max_expanded],
        top_k_per_path=3
    )

    if not linked_results:
        return results

    # Combine and re-rank
    # Boost scores of linked results that share connector/category with original results
    original_connectors = {r.connector for r in results if r.connector}
    original_categories = {r.doc_category for r in results if r.doc_category}

    for lr in linked_results:
        # Slight score boost if related
        if lr.connector in original_connectors or lr.doc_category in original_categories:
            lr.score *= 1.1

    # Merge by score
    merged = results + linked_results
    merged.sort(key=lambda r: r.score, reverse=True)
    merged = merged[:top_k * 2]

    # Apply "prefer detail over summary" rule
    merged = _prefer_detail_over_summary(merged)

    return merged[:top_k]


def search_docs_with_expansion(
    queries: List[str],
    top_k: int = Config.MAX_RETRIEVED_DOCS,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
    expand_links: bool = True,
) -> List[dict]:
    """
    Search docs with optional link expansion.

    When expand_links=True, also retrieves chunks from documents linked
    from the top results, providing richer context.

    Args:
        queries: Search queries
        top_k: Number of results to return
        connector: Filter by connector type
        destination: Filter by destination
        sync_mode: Filter by sync mode
        expand_links: Whether to expand with linked documents

    Returns:
        List of result dicts with chunk data and links
    """
    filt = _build_filter(connector=connector, destination=destination, sync_mode=sync_mode)

    primary_query = queries[0] if queries else ""
    results = _dense_search_with_fallback(
        primary_query, Config.DOCS_COLLECTION, top_k=top_k, payload_filter=filt
    )

    # Apply "prefer detail over summary" rule
    results = _prefer_detail_over_summary(results)

    if expand_links:
        results = expand_with_linked_docs(results, top_k=top_k)

    log.info(
        f"search_docs_with_expansion: {len(results)} results "
        f"[conn={connector!r}, dest={destination!r}, expand={expand_links}] "
        f"query={primary_query!r}"
    )

    return [r.to_dict() for r in results]
