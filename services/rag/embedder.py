"""
Local embedding using nomic-embed-text-v1.5 via transformers.

Uses AutoModel + AutoTokenizer with mean pooling + L2 normalization.
Prefix all text with "search_document: " before embedding.
No sentence-transformers, no fastembed.
"""

from __future__ import annotations
import logging
from functools import lru_cache
from typing import List

import torch
from transformers import AutoModel, AutoTokenizer

from config import Config

log = logging.getLogger(__name__)

_INDEX_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


@lru_cache(maxsize=1)
def _get_model():
    """Load and cache the embedding model (uses HuggingFace cache)."""
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
    log.info("Embedding model loaded ✓")
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


def _embed_texts(texts: List[str], prefix: str) -> List[List[float]]:
    """Embed a list of texts with the given prefix."""
    model, tokenizer = _get_model()
    prefixed_texts = [prefix + t for t in texts]

    encoded = tokenizer(
        prefixed_texts,
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


def embed_documents(texts: List[str]) -> List[List[float]]:
    """
    Embed a batch of document chunks for indexing.
    Applies the 'search_document:' task prefix.
    Processes one at a time - no batching for stability.
    """
    all_vectors = []
    for text in texts:
        vectors = _embed_texts([text], _INDEX_PREFIX)
        all_vectors.append(vectors[0])
    return all_vectors


def embed_query(text: str) -> List[float]:
    """
    Embed a single retrieval query.
    Applies the 'search_query:' task prefix.
    """
    vectors = _embed_texts([text], _QUERY_PREFIX)
    return vectors[0]


def embed_queries(texts: List[str]) -> List[List[float]]:
    """Embed multiple queries (for multi-query retrieval)."""
    return _embed_texts(texts, _QUERY_PREFIX)


def vector_size() -> int:
    """Return the dimensionality of the embedding model output."""
    return 768  # nomic-embed-text-v1.5 output dimension


def is_ready() -> bool:
    """Return True if the model is already loaded (warm)."""
    return _get_model.cache_info().currsize > 0
