"""
Documentation Retriever Node — retrieves relevant OLake docs via RAG Service.

Strategy:
  1. Call RAG Service (search_docs + search_code) via rag_client over HTTP.
     - Multi-query: uses message + key_topics + technical_terms
     - Metadata filters: passes detected connector/destination/sync_mode
     - Merges docs + code results (RRF done server-side)
  2. If RAG Service is unreachable → return empty results (agent will ask for clarification).

Sets state["doc_sufficient"] = True when top result score >= DOCS_ANSWER_THRESHOLD.
"""

from __future__ import annotations
from typing import Dict, Any, List
import re
import logging

from agent.state import ConversationState, RetrievedDocument
from agent.config import Config, load_olake_docs
from agent.logger import get_logger, EventType
import agent.rag_client as rag

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connector/destination/sync_mode detector (for metadata filters)
# ---------------------------------------------------------------------------

_CONNECTOR_PATTERNS = {
    "postgres":  ["postgres", "postgresql", "pgoutput", "cdc postgres"],
    "mysql":     ["mysql", "binlog"],
    "mongodb":   ["mongodb", "mongo", "oplog"],
    "oracle":    ["oracle"],
    "kafka":     ["kafka"],
}
_DEST_PATTERNS = {
    "iceberg": ["iceberg"],
    "parquet": ["parquet"],
    "s3":      ["amazon s3", "aws s3", " s3 "],
    "gcs":     ["gcs", "google cloud storage"],
    "minio":   ["minio"],
}
_SYNC_MODE_PATTERNS = {
    "cdc":          ["cdc", "change data capture", "binlog", "oplog", "pgoutput"],
    "full_refresh": ["full refresh"],
    "incremental":  ["incremental"],
}


def _detect(text: str, patterns: dict) -> str:
    tl = text.lower()
    for key, pats in patterns.items():
        if any(p in tl for p in pats):
            return key
    return ""


# ---------------------------------------------------------------------------
# Map RAG result dict → RetrievedDocument
# ---------------------------------------------------------------------------

def _to_retrieved_doc(r: dict) -> RetrievedDocument:
    return RetrievedDocument(
        title=r.get("title") or r.get("subsection") or r.get("section") or "OLake Docs",
        content=r.get("text", ""),
        url=r.get("doc_url") or "https://olake.io/docs/",
        relevance_score=float(r.get("score", 0.0)),
        source_type=r.get("source", "docs"),
    )


# ---------------------------------------------------------------------------
# Keyword fallback (last resort when RAG is down)
# ---------------------------------------------------------------------------

def _keyword_search(queries: List[str]) -> List[RetrievedDocument]:
    """Simple keyword search over local olake_docs.md as a last-resort fallback."""
    try:
        raw = load_olake_docs()
    except Exception:
        return []

    sections: List[Dict[str, str]] = []
    current = {"title": "Introduction", "content": ""}
    for line in raw.split("\n"):
        if line.startswith("## ") or line.startswith("# "):
            if current["content"].strip():
                sections.append(current)
            current = {"title": line.lstrip("#").strip(), "content": ""}
        else:
            current["content"] += line + "\n"
    if current["content"].strip():
        sections.append(current)

    results = []
    for sec in sections:
        cl = sec["content"].lower()
        score = 0.0
        for q in queries:
            terms = re.findall(r"\w+", q.lower())
            if terms:
                score += sum(1 for t in terms if t in cl) / len(terms)
        if queries:
            score /= len(queries)
        if score >= Config.DOC_RELEVANCE_THRESHOLD:
            results.append(RetrievedDocument(
                title=sec["title"],
                content=sec["content"][:2500],
                url="https://olake.io/docs/",
                relevance_score=score,
                source_type="docs",
            ))

    results.sort(key=lambda d: d.relevance_score, reverse=True)
    return results[:Config.MAX_RETRIEVED_DOCS]


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------

def doc_retriever(state: ConversationState) -> ConversationState:
    """
    Retrieve relevant docs and code examples for the user's message.

    Query priority:
      1. state["search_queries"] — set by problem_decomposer (specific keyword phrases)
      2. key_topics + technical_terms — from intent analyzer
      3. message_text — raw fallback (put last; it's a question, not keywords)

    Retrieval priority:
      1. RAG Service (reranked endpoint) — bi-encoder + cross-encoder rerank
      2. RAG Service (bi-encoder only) — if reranker not ready
      3. Keyword search over local file — last resort when RAG is unavailable
    """
    logger = get_logger()
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    message_text = state["message_text"]
    key_topics = state.get("key_topics", [])
    technical_terms = state.get("technical_terms", [])

    # ── Query construction ────────────────────────────────────────────────────
    # Use decomposer's queries if present — they're specific, keyword-style.
    # Only fall back to raw message if decomposer produced nothing useful.
    decomposer_queries = [q for q in (state.get("search_queries") or []) if q.strip()]
    if decomposer_queries:
        all_queries = list(dict.fromkeys(decomposer_queries))
    else:
        # Build from intent analysis: put specific terms before the raw message
        all_queries = list(dict.fromkeys(
            q for q in (key_topics + technical_terms + [message_text]) if q.strip()
        ))
    state["search_queries"] = all_queries

    # Detect metadata filters from message + queries
    combined_text = " ".join(all_queries + [message_text])
    connector   = _detect(combined_text, _CONNECTOR_PATTERNS)
    destination = _detect(combined_text, _DEST_PATTERNS)
    sync_mode   = _detect(combined_text, _SYNC_MODE_PATTERNS)

    # Primary query for reranker (must be single string; use the best query)
    primary_query = all_queries[0] if all_queries else message_text

    try:
        retrieved_docs: List[RetrievedDocument] = []

        # ── Primary: RAG Service (bi-encoder + cross-encoder rerank) ─────────
        docs_raw = rag.search_docs_reranked(
            query=primary_query,
            queries=all_queries[1:],
            top_k=Config.MAX_RETRIEVED_DOCS,
            connector=connector,
            destination=destination,
            sync_mode=sync_mode,
        )

        # Fallback to bi-encoder only if reranker not ready
        if docs_raw is None:
            docs_raw = rag.search_docs(
                query=message_text,
                queries=all_queries[1:],
                top_k=Config.MAX_RETRIEVED_DOCS,
                connector=connector,
                destination=destination,
                sync_mode=sync_mode,
            )

        code_raw = rag.search_code(
            query=message_text,
            queries=all_queries[1:],
            top_k=3,
        )

        if docs_raw is not None or code_raw is not None:
            # RAG service responded — merge and convert
            state["rag_service_available"] = True
            all_raw = (docs_raw or []) + (code_raw or [])
            seen_ids = set()
            for r in sorted(all_raw, key=lambda x: x.get("score", 0), reverse=True):
                cid = r.get("chunk_id", "")
                if cid and cid in seen_ids:
                    continue
                seen_ids.add(cid)
                retrieved_docs.append(_to_retrieved_doc(r))
                if len(retrieved_docs) >= Config.MAX_RETRIEVED_DOCS:
                    break

            log.info(
                f"RAG service returned {len(retrieved_docs)} results "
                f"(connector={connector!r}, dest={destination!r}, sync={sync_mode!r})"
            )
        else:
            # ── Fallback: keyword search over local file ─────────────────────
            # RAG service is down. Use simple keyword search as last resort.
            state["rag_service_available"] = False
            log.warning("RAG service unavailable — using keyword fallback")
            retrieved_docs = _keyword_search(all_queries)
            if retrieved_docs:
                log.info(f"Keyword fallback returned {len(retrieved_docs)} results")
            else:
                log.warning("Keyword fallback also returned no results")

        # ACCUMULATE docs across iterations instead of replacing
        # This is critical for multi-iteration retrieval to work properly
        existing_docs = state.get("retrieved_docs", [])
        existing_ids = {d.url + d.title for d in existing_docs}  # dedup key
        
        # Add only new docs that weren't retrieved in previous iterations
        for doc in retrieved_docs:
            dedup_key = doc.url + doc.title
            if dedup_key not in existing_ids:
                existing_docs.append(doc)
                existing_ids.add(dedup_key)
        
        # Compute average score and doc_sufficient flag
        avg_score = (
            sum(d.relevance_score for d in existing_docs) / len(existing_docs)
            if existing_docs else 0.0
        )
        state["retrieved_docs"] = existing_docs
        state["docs_relevance_score"] = avg_score
        state["doc_sufficient"] = (
            avg_score >= Config.DOCS_ANSWER_THRESHOLD and bool(existing_docs)
        )

        logger.log_docs_searched(
            query=message_text,
            num_results=len(retrieved_docs),
            top_results=[
                {"title": d.title, "relevance": round(d.relevance_score, 3), "source": d.source_type}
                for d in retrieved_docs[:3]
            ],
            user_id=user_id,
            channel_id=channel_id,
        )

    except Exception as e:
        logger.log_error(
            error_type="DocRetrievalError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        state["retrieved_docs"] = []
        state["docs_relevance_score"] = 0.0
        state["doc_sufficient"] = False
        state["search_queries"] = all_queries

    return state
