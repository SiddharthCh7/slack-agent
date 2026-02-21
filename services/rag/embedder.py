"""
Local embedding using nomic-embed-text-v1.5 via sentence-transformers.

Task prefixes (nomic best practice):
  - Indexing:  "search_document: {text}"
  - Querying:  "search_query: {text}"
"""

from __future__ import annotations
import logging
from functools import lru_cache
from typing import List

from config import Config

log = logging.getLogger(__name__)

_INDEX_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


@lru_cache(maxsize=1)
def _get_model():
    """Load and cache the embedding model (downloads on first call)."""
    from sentence_transformers import SentenceTransformer
    log.info(f"Loading embedding model: {Config.EMBED_MODEL}")
    model = SentenceTransformer(
        Config.EMBED_MODEL,
        trust_remote_code=True,
        device=Config.EMBED_DEVICE,
    )
    log.info("Embedding model loaded ✓")
    return model


def embed_documents(texts: List[str]) -> List[List[float]]:
    """
    Embed a batch of document chunks for indexing.
    Applies the 'search_document:' task prefix.
    """
    model = _get_model()
    prefixed = [_INDEX_PREFIX + t for t in texts]
    vectors = model.encode(
        prefixed,
        batch_size=Config.EMBED_BATCH_SIZE,
        show_progress_bar=len(texts) > 100,
        normalize_embeddings=True,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> List[float]:
    """
    Embed a single retrieval query.
    Applies the 'search_query:' task prefix.
    """
    model = _get_model()
    vector = model.encode(
        _QUERY_PREFIX + text,
        normalize_embeddings=True,
    )
    return vector.tolist()


def embed_queries(texts: List[str]) -> List[List[float]]:
    """Embed multiple queries (for multi-query retrieval)."""
    model = _get_model()
    prefixed = [_QUERY_PREFIX + t for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def vector_size() -> int:
    """Return the dimensionality of the embedding model output."""
    return _get_model().get_sentence_embedding_dimension()


def is_ready() -> bool:
    """Return True if the model is already loaded (warm)."""
    return _get_model.cache_info().currsize > 0
