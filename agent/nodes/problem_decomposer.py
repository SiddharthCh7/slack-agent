"""
Problem Decomposer Node — Turns a raw user message into structured retrieval inputs.

Purpose:
  Before any retrieval happens, this node uses an LLM to:
  1. Summarise the problem in one sentence (problem_summary)
  2. Break it into specific sub-questions that can be answered by documentation
  3. Generate max 4 targeted search queries (closely related to the actual issue)

What it does NOT do:
  - It does NOT ask the user anything (that's clarification_asker's job)
  - It does NOT decide whether clarification is needed (that's deep_reasoner's job)
  - It does NOT retrieve documents (that's doc_retriever's job)

The OLake context summary is injected so the LLM understands domain vocabulary
(CDC, connectors, pgoutput, WAL, etc.) and can generate precise queries.
"""

from __future__ import annotations
import asyncio
import json
import re
from typing import Dict, Any

from agent.state import ConversationState
from agent.llm import get_chat_completion
from agent.logger import get_logger
from agent.config import OLAKE_CONTEXT

_PARSE_RE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _parse_json(text: str | None) -> dict:
    if not text:
        raise ValueError("LLM returned empty response")
    text = _PARSE_RE_FENCE.sub("", text.strip())
    return json.loads(text)


_SYSTEM_PROMPT = f"""You analyse OLake support messages and produce search inputs. Return JSON only.

OLake: {OLAKE_CONTEXT.strip()[:600]}

Output this JSON object:
{{
  "problem_summary": "one sentence: what the user needs",
  "sub_questions": ["max 3 doc-answerable sub-questions"],
  "search_queries": ["max 3 short keyword phrases for semantic search — specific, not generic"],
  "is_ambiguous": false
}}

Search query rules:
- Short keyword phrases (2-4 words), NOT full questions
- Include connector names (e.g., "mssql", "postgres"), error keywords, technical terms
- Use exact technical terms from the message (e.g., "schema change", "CDC", "WAL")
- Skip vague phrases like "OLake setup", "how to use OLake", "OLake connector"
- Extract key error phrases verbatim if present
- Prefer specific over generic: "mssql cdc schema" NOT "OLake mssql connector"

Return ONLY valid JSON, no markdown."""


async def problem_decomposer(state: ConversationState) -> Dict[str, Any]:
    logger = get_logger()
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    message_text = state["message_text"]

    # Include thread context so we don't re-decompose already-answered parts
    thread_context = state.get("thread_context", [])
    thread_snippet = ""
    if thread_context:
        lines = []
        for msg in thread_context[-6:]:       # last 6 messages for context
            role = "Bot" if msg.get("is_bot") else "User"
            lines.append(f"{role}: {msg.get('text', '')[:200]}")
        thread_snippet = "\nRecent thread context:\n" + "\n".join(lines)

    prompt = f"""Analyse this support message and decompose it into structured search inputs.

User message: "{message_text}"{thread_snippet}

Return JSON only."""

    try:
        response = await get_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        result = _parse_json(response)

        state["problem_summary"]   = result.get("problem_summary", message_text[:120])
        state["sub_questions"]     = result.get("sub_questions", [])
        state["is_ambiguous"]      = bool(result.get("is_ambiguous", False))

        # Generated queries come FIRST — they're specific keyword phrases.
        # message_text is a natural-language question (bad for vector search);
        # only include it as a fallback if the LLM produced fewer than 2 queries.
        generated_queries = [q.strip() for q in result.get("search_queries", []) if q.strip()]
        if len(generated_queries) < 2:
            generated_queries.append(message_text)
        state["search_queries"] = list(dict.fromkeys(generated_queries))[:5]

        logger.logger.info(
            f"[ProblemDecomposer] summary={state['problem_summary']!r} "
            f"queries={state['search_queries']} ambiguous={state['is_ambiguous']}"
        )

    except Exception as e:
        logger.log_error(
            error_type="ProblemDecomposerError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        # Fallback: use key_topics as search queries
        fallback = [message_text] + state.get("key_topics", []) + state.get("technical_terms", [])
        state["search_queries"]  = list(dict.fromkeys(fallback))[:4]
        state["problem_summary"] = message_text[:120]
        state["sub_questions"]   = []
        state["is_ambiguous"]    = False

    return state


def problem_decomposer_sync(state: ConversationState) -> ConversationState:
    """Synchronous wrapper for LangGraph."""
    return asyncio.run(problem_decomposer(state))
