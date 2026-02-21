"""
RAG Service HTTP client for the Agent Service.

Calls the RAG service REST API (POST /api/search_docs, /api/search_code, etc.)
over httpx. Falls back to local keyword search if the service is unreachable.

The MCP SSE endpoint (/mcp/sse) is also available for direct MCP tool calls
(e.g. from Claude Desktop or future agent improvements using tool-calling LLMs).
"""

from __future__ import annotations
import logging
import os
from typing import List, Optional

import httpx

log = logging.getLogger(__name__)

RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:7070").rstrip("/")
RAG_TOOL_TIMEOUT = float(os.getenv("RAG_TOOL_TIMEOUT", "10"))

# MCP SSE endpoint for external MCP clients
RAG_MCP_SSE_URL = f"{RAG_SERVICE_URL}/mcp/sse"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _post(path: str, body: dict) -> list | dict | None:
    """POST to the RAG service. Returns parsed JSON or None on failure."""
    url = f"{RAG_SERVICE_URL}{path}"
    try:
        resp = httpx.post(url, json=body, timeout=RAG_TOOL_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        log.warning(f"RAG service unreachable at {url} — will use keyword fallback")
        return None
    except httpx.TimeoutException:
        log.warning(f"RAG service timed out ({RAG_TOOL_TIMEOUT}s) at {url}")
        return None
    except Exception as e:
        log.warning(f"RAG service error at {url}: {e}")
        return None


def _get(path: str, **params) -> dict | None:
    """GET from the RAG service."""
    url = f"{RAG_SERVICE_URL}{path}"
    try:
        resp = httpx.get(url, params=params, timeout=RAG_TOOL_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning(f"RAG GET {url} failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API (mirrors the MCP tool signatures)
# ---------------------------------------------------------------------------

def search_docs(
    query: str,
    queries: Optional[List[str]] = None,
    top_k: int = 5,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
) -> list | None:
    """
    Semantic search over the OLake prose documentation.

    Returns a list of result dicts, or None if the RAG service is down.
    The caller should handle None by falling back to keyword search.
    """
    return _post("/api/search_docs", {
        "query": query,
        "queries": queries or [],
        "top_k": top_k,
        "connector": connector,
        "destination": destination,
        "sync_mode": sync_mode,
    })


def search_code(
    query: str,
    queries: Optional[List[str]] = None,
    top_k: int = 3,
) -> list | None:
    """Semantic search over code blocks. Returns None if service is down."""
    return _post("/api/search_code", {
        "query": query,
        "queries": queries or [],
        "top_k": top_k,
    })


def search_docs_reranked(
    query: str,
    queries: Optional[List[str]] = None,
    top_k: int = 5,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
) -> list | None:
    """
    Semantic search + cross-encoder re-ranking over the docs collection.
    Returns None if service is down (caller should fall back to search_docs).
    Use this as the primary search call — more accurate than search_docs alone.
    """
    return _post("/api/search_docs_reranked", {
        "query": query,
        "queries": queries or [],
        "top_k": top_k,
        "connector": connector,
        "destination": destination,
        "sync_mode": sync_mode,
    })


def ingest(path: str, reset: bool = False, sync: bool = True) -> dict | None:
    """
    Trigger ingestion of the docs file.
    sync=True blocks until complete (for scripts).
    sync=False returns immediately (background task).
    """
    endpoint = "/api/ingest/sync" if sync else "/api/ingest"
    return _post(endpoint, {"path": path, "reset": reset})


def get_chunk(chunk_id: str, collection: str = "olake_docs") -> dict | None:
    """Look up a single chunk by ID."""
    return _get(f"/api/chunk/{chunk_id}", collection=collection)


def health() -> dict:
    """Check if the RAG service is up and the model is warm."""
    result = _get("/health")
    return result or {"status": "unreachable", "ready": False}


def is_available() -> bool:
    """Quick check: returns True if the service responds and model is ready."""
    h = health()
    return h.get("status") == "ok" and h.get("ready", False)
