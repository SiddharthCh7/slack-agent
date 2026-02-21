"""
OLake RAG Service — FastMCP + FastAPI.

Exposes:
  GET  /health          — readiness probe (returns {"ready": bool})
  GET  /mcp/sse         — MCP SSE endpoint (for MCP clients like Claude Desktop)
  POST /mcp/messages    — MCP message handler

MCP Tools (also callable as REST via /api/* for internal service use):
  search_docs      — semantic search over the prose docs collection
  search_code      — semantic search over the code collection
  ingest_docs      — chunk, embed, and upsert the docs file into Qdrant
  get_chunk        — point lookup by chunk_id
  list_collections — list all active Qdrant collections
  collection_stats — count + config info for a collection
"""

from __future__ import annotations
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, List, Optional

import uvicorn
from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from config import Config
from embedder import embed_documents, is_ready
from chunker import parse_file
from indexer import (
    ensure_collection,
    list_collections as _list_collections,
    collection_stats as _collection_stats,
    upsert_chunks,
    get_chunk as _get_chunk,
)
import retriever as ret

log = logging.getLogger(__name__)
logging.basicConfig(level=Config.LOG_LEVEL, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# FastMCP — tool definitions
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="OLake RAG Service",
    instructions=(
        "Provides semantic search over OLake documentation and code examples. "
        "Use search_docs for prose documentation. Use search_code for YAML configs, "
        "SQL, and shell commands. Pass connector/destination/sync_mode filters when "
        "the user's question is specific to a connector or destination."
    ),
)


@mcp.tool()
def search_docs(
    query: str,
    top_k: int = 5,
    queries: Optional[List[str]] = None,
    connector: str = "",
    destination: str = "",
    sync_mode: str = "",
) -> list:
    """
    Semantic search over OLake prose documentation.

    Args:
        query:       Primary search query (the user's question or key phrase)
        top_k:       Maximum number of results
        queries:     Additional search queries (key topics, technical terms).
                     If provided, all queries are used for multi-vector search.
        connector:   Filter to a specific connector: postgres|mysql|mongodb|oracle|kafka
        destination: Filter to a destination: iceberg|parquet|s3|gcs|minio
        sync_mode:   Filter to a sync mode: cdc|full_refresh|incremental

    Returns:
        List of matching document chunks with score, url, and full text
    """
    all_queries = [query] + (queries or [])
    return ret.search_docs(
        queries=all_queries,
        top_k=top_k,
        connector=connector,
        destination=destination,
        sync_mode=sync_mode,
    )


@mcp.tool()
def search_code(
    query: str,
    top_k: int = 3,
    queries: Optional[List[str]] = None,
) -> list:
    """
    Semantic search over OLake code examples (YAML configs, SQL, shell).

    Args:
        query:  Primary search query
        top_k:  Maximum number of results
        queries: Additional queries for multi-vector search
    """
    all_queries = [query] + (queries or [])
    return ret.search_code(queries=all_queries, top_k=top_k)


@mcp.tool()
def ingest_docs(
    path: str = str(Config.DOCS_FILE),
    reset: bool = False,
) -> dict:
    """
    Chunk, embed, and upsert the OLake docs file into Qdrant.

    Args:
        path:  Path to the markdown knowledge-base file
        reset: If True, drop and recreate both collections before ingesting
    """
    return _run_ingest(path=path, reset=reset)


@mcp.tool()
def get_chunk(chunk_id: str, collection: str = Config.DOCS_COLLECTION) -> dict:
    """Retrieve a single chunk by its chunk_id for inspection or debugging."""
    result = _get_chunk(collection, chunk_id)
    return result or {"error": "chunk_id not found"}


@mcp.tool()
def list_collections() -> list:
    """List all active Qdrant collection names."""
    return _list_collections()


@mcp.tool()
def collection_stats(collection: str = Config.DOCS_COLLECTION) -> dict:
    """Return point count, vector size, and distance metric for a collection."""
    return _collection_stats(collection)


# ---------------------------------------------------------------------------
# Ingest implementation (shared by tool + REST endpoint)
# ---------------------------------------------------------------------------

def _run_ingest(path: str, reset: bool) -> dict:
    docs_path = Path(path)
    if not docs_path.exists():
        return {"error": f"File not found: {path}"}

    chunks = parse_file(docs_path)
    prose_chunks = [c for c in chunks if c.chunk_type != "code"]
    code_chunks  = [c for c in chunks if c.chunk_type == "code"]

    ensure_collection(Config.DOCS_COLLECTION, drop_first=reset)
    ensure_collection(Config.CODE_COLLECTION, drop_first=reset)

    prose_count = code_count = 0

    if prose_chunks:
        log.info(f"Embedding {len(prose_chunks)} doc chunks...")
        prose_vecs = embed_documents([c.raw_text for c in prose_chunks])
        prose_count = upsert_chunks(Config.DOCS_COLLECTION, prose_chunks, prose_vecs)

    if code_chunks:
        log.info(f"Embedding {len(code_chunks)} code chunks...")
        code_vecs = embed_documents([c.raw_text for c in code_chunks])
        code_count = upsert_chunks(Config.CODE_COLLECTION, code_chunks, code_vecs)

    return {
        "ok": True,
        "docs_upserted": prose_count,
        "code_upserted": code_count,
        "total_chunks": len(chunks),
        "reset": reset,
        "path": str(path),
    }


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("RAG Service starting up...")
    # Warm the embedding model in a background thread so the first search
    # doesn't have 30s cold-start latency; health endpoint returns "ready: false"
    # until model is loaded.
    def _warm():
        from embedder import _get_model
        _get_model()
        log.info("Embedding model warmed ✓")
    threading.Thread(target=_warm, daemon=True).start()
    yield
    log.info("RAG Service shutting down.")


app = FastAPI(
    title="OLake RAG Service",
    description="Chunking · Embedding · Semantic Search over OLake docs",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount MCP SSE transport at /mcp
app.mount("/mcp", mcp.http_app())


@app.get("/health")
def health():
    """Readiness probe. Returns ready=true once the embedding model is loaded."""
    return {"status": "ok", "ready": is_ready()}


# ---------------------------------------------------------------------------
# Convenience REST wrappers (used by agent service via httpx)
# ---------------------------------------------------------------------------

class SearchDocsRequest(BaseModel):
    query: str
    queries: List[str] = Field(default_factory=list)
    top_k: int = 5
    connector: str = ""
    destination: str = ""
    sync_mode: str = ""


class SearchCodeRequest(BaseModel):
    query: str
    queries: List[str] = Field(default_factory=list)
    top_k: int = 3


class IngestRequest(BaseModel):
    path: str = str(Config.DOCS_FILE)
    reset: bool = False


@app.post("/api/search_docs")
def api_search_docs(body: SearchDocsRequest):
    all_queries = [body.query] + body.queries
    return ret.search_docs(
        queries=all_queries,
        top_k=body.top_k,
        connector=body.connector,
        destination=body.destination,
        sync_mode=body.sync_mode,
    )


@app.post("/api/search_code")
def api_search_code(body: SearchCodeRequest):
    all_queries = [body.query] + body.queries
    return ret.search_code(queries=all_queries, top_k=body.top_k)


@app.post("/api/search_docs_reranked")
def api_search_docs_reranked(body: SearchDocsRequest):
    """
    Bi-encoder retrieval + cross-encoder re-ranking.
    Retrieves top-20 candidates, re-ranks with ms-marco cross-encoder, returns top-k.
    More accurate than /api/search_docs but slightly slower (~30ms extra on CPU).
    """
    from reranker import rerank
    all_queries = [body.query] + body.queries
    # Retrieve wider candidate set for re-ranking
    candidates = ret.search_docs(
        queries=all_queries,
        top_k=max(body.top_k * 3, 15),   # retrieve 3x more for re-ranking pool
        connector=body.connector,
        destination=body.destination,
        sync_mode=body.sync_mode,
    )
    # Re-rank using primary query (cross-encoder is pairwise — single query)
    reranked = rerank(query=body.query, results=candidates, top_k=body.top_k)
    return reranked


@app.post("/api/ingest")
def api_ingest(body: IngestRequest, background_tasks: BackgroundTasks):
    """Kick off ingestion asynchronously (can take minutes for large files)."""
    background_tasks.add_task(_run_ingest, path=body.path, reset=body.reset)
    return {"ok": True, "message": "Ingestion started in background"}


@app.post("/api/ingest/sync")
def api_ingest_sync(body: IngestRequest):
    """Synchronous ingest — blocks until complete. Use for scripting."""
    return _run_ingest(path=body.path, reset=body.reset)


@app.get("/api/chunk/{chunk_id}")
def api_get_chunk(chunk_id: str, collection: str = Config.DOCS_COLLECTION):
    result = _get_chunk(collection, chunk_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return result


@app.get("/api/collections")
def api_list_collections():
    return _list_collections()


@app.get("/api/collections/{name}/stats")
def api_collection_stats(name: str):
    return _collection_stats(name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    uvicorn.run(
        "server:app",
        host=Config.HOST,
        port=Config.PORT,
        log_level=Config.LOG_LEVEL.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
