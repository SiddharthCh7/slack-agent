"""
Shared embedding function.

Uses nomic-ai/nomic-embed-text-v1.5 locally via sentence-transformers.
Model is ~274 MB — lightweight enough to run locally without OOM issues.

Produces 768-dimensional cosine-normalised vectors, matching the
Qdrant collection config (size=768, distance=COSINE).
"""

import logging
from typing import List

log = logging.getLogger(__name__)

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        log.info(f"Loading embedding model: {MODEL_NAME}")
        _model = SentenceTransformer(
            MODEL_NAME,
            trust_remote_code=True,  # required by nomic models
        )
        log.info("Embedding model loaded.")
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed a list of texts using nomic-embed-text-v1.5 locally.
    Returns a list of 768-dimensional float vectors.
    """
    if not texts:
        return []

    model = _get_model()
    # nomic-embed-text-v1.5 works best with a task prefix
    prefixed = [f"search_document: {t}" for t in texts]
    embeddings = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str) -> List[float]:
    """
    Embed a single query string. Uses the 'search_query' task prefix
    for better semantic alignment at query time.
    """
    model = _get_model()
    vec = model.encode(
        [f"search_query: {query}"],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vec[0].tolist()
