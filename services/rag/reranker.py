"""
Cross-encoder re-ranker for the RAG service.

Uses ms-marco-MiniLM-L-6-v2 (37 MB) to re-score the top-N bi-encoder results.
The cross-encoder sees (query, passage) jointly, giving significantly better
relevance signals than cosine similarity alone.

Flow:
  bi-encoder retrieves top-20 (fast, approximate)
      → cross-encoder re-ranks to top-6 (precise)

The model is loaded once and cached — warm time ~1s on CPU.
"""

from __future__ import annotations
import logging
from functools import lru_cache
from typing import List

log = logging.getLogger(__name__)

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=1)
def _get_reranker():
    from sentence_transformers import CrossEncoder
    log.info(f"Loading cross-encoder: {RERANK_MODEL}")
    model = CrossEncoder(RERANK_MODEL, max_length=512)
    log.info("Cross-encoder loaded ✓")
    return model


def rerank(
    query: str,
    results: List[dict],
    top_k: int = 6,
) -> List[dict]:
    """
    Re-rank a list of result dicts using the cross-encoder.

    Args:
        query:   The primary user query (single string — cross-encoders are pairwise)
        results: List of result dicts from bi-encoder search (each must have "text" key)
        top_k:   Number of results to return after re-ranking

    Returns:
        Re-ranked, truncated list of result dicts with updated "score" field.
    """
    if not results:
        return []

    try:
        model = _get_reranker()
        pairs = [(query, r.get("text", "")[:512]) for r in results]
        scores = model.predict(pairs).tolist()

        # Attach cross-encoder score and sort descending
        scored = sorted(
            zip(scores, results),
            key=lambda x: x[0],
            reverse=True,
        )

        reranked = []
        for score, result in scored[:top_k]:
            r = dict(result)
            r["score"] = float(score)   # overwrite bi-encoder score
            r["reranked"] = True
            reranked.append(r)

        return reranked

    except Exception as e:
        log.warning(f"Cross-encoder re-ranking failed: {e} — returning original order")
        return results[:top_k]


def is_ready() -> bool:
    """Return True if the cross-encoder model is already loaded."""
    return _get_reranker.cache_info().currsize > 0
