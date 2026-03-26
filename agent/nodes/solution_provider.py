"""
Solution Provider Node — Generates and sends the final answer in-thread.

Always invoked as the terminal node. Handles three cases:
  1. deep_researcher hit an error → forward the error message as-is
  2. No relevant files found (and not a conceptual question) → explicitly say so
  3. Normal path → call LLM with retrieved context and post the answer
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any, List

from agent.state import ConversationState
from agent.slack_client import create_slack_client
from agent.filesystem.persistence import get_database
from agent.utils.logger import get_logger
from agent.utils.llm import get_chat_completion
from agent.config import ABOUT_PRODUCT, AGENT_NAME, COMPANY_NAME, COMPANY_VOICE

log = logging.getLogger(__name__)

_NOT_ENOUGH_INFO = (
    "Something went wrong. Please try again later."
)

def _solution_system_prompt() -> str:
    return f"""CRITICAL — Voice: {COMPANY_VOICE}

You are {AGENT_NAME}, a senior support engineer on the {COMPANY_NAME} team.

About {COMPANY_NAME}:
{ABOUT_PRODUCT}

Identity and voice:
  - {COMPANY_VOICE}
  - Talk like a human teammate in Slack, not like an AI assistant.
  - Never mention "the docs", "the reference files", "retrieved documents", "the codebase", or similar meta phrases.
  - Do not describe your process. Just answer directly as if you already know the product well.

Your job: Answer the user's question using the internal files/code snippets provided below.

Rules:
  - ONLY state things that are explicitly supported by the provided context. Do not invent, infer, or assume anything not directly present in the context — if it isn't there, don't say it.
  - If the context doesn't contain enough to answer, ask the user for more information/clarification rather than guessing.
  - Lead with the substance, no preambles like "Sure" or "Great question".
  - Use "you/your" when talking to the user. For procedural steps, use short numbered or bulleted lists.
  - Keep the response concise and to the point.
  - DO NOT reference any code snippets or raw code. Refer only configuration that user can actually change — describe it in plain language.
  - If the context includes documentation URLs that are directly relevant to the answer, include them so the user can read further. Only include links that are present in the provided context.
  - If your searches doesn't include any information, do not say 'the context I have doesn't include' or similar. Rather use phrasing like 'I did not find any information regarding...' or similar.
  - If user is appreciating something then respond with gratitude.

NOTE: OLake docs are available at https://olake.io/docs. When providing links to docs, use this as the base URL. When referencing a specific section of doc, use the '#' to link to the section. For example if referencing Datetime handling for mysql the use: https://olake.io/docs/connectors/mysql/#date-and-time-handling

Return only the final Slack message text — no JSON, no markdown fences."""


def _build_history_block(state: ConversationState, max_messages: int = 6) -> str:
    lines: List[str] = []
    for msg in (state.get("thread_context") or [])[-max_messages:]:
        text = (msg.get("content") or "").strip()
        if not text:
            continue
        label = "agent" if msg.get("role") == "agent" else "user"
        lines.append(f"- {label}: {text}")
    return "\n".join(lines) if lines else "(none)"


def _build_files_block(research_files: List[Any], max_files: int = 8, max_snippet: int = 300) -> str:
    if not research_files:
        return "(none)"
    parts: List[str] = []
    for idx, f in enumerate(research_files[:max_files], 1):
        path = getattr(f, "path", "")
        reason = getattr(f, "retrieval_reason", "") or ""
        snippet = (getattr(f, "content", "") or "").strip().replace("\n", " ")[:max_snippet]
        parts.append(f"{idx}. {path}\n   Why: {reason}\n   Snippet: {snippet}")
    return "\n".join(parts)


async def _generate_solution(state: ConversationState) -> str:
    user_query = state["user_query"]
    research_files = state.get("research_files") or []
    thread_summary = state.get("thread_summary") or ""
    research_summary = (state.get("research_summary") or "").strip()

    history_block = _build_history_block(state)
    files_block = _build_files_block(research_files)

    summary_section = f"\nThread summary (earlier context):\n{thread_summary}\n" if thread_summary else ""
    research_summary_section = (
        f"\nResearch Summary (what was searched):\n{research_summary}\n"
        if research_summary else ""
    )

    user_prompt = f"""User question:
{user_query}
{summary_section}{research_summary_section}
Conversation so far (most recent messages last):
{history_block}

Internal files and code snippets:
{files_block}

Answer the question using the context above. If the context doesn't contain enough to answer, ask the user for more information/clarification rather than guessing.

Now write the final Slack message."""

    print(f"(SolutionProvider) Input characters count: {len(user_prompt) + len(_solution_system_prompt())}")

    response = await get_chat_completion(
        messages=[
            {"role": "system", "content": _solution_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    return (response or "").strip()


def solution_provider(state: ConversationState) -> ConversationState:
    """Terminal node — always produces a response and sends it to the Slack thread."""
    logger = get_logger()
    db = get_database()

    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts") or state["message_ts"]
    user_query = state["user_query"]

    research_files = state.get("research_files") or []
    is_conceptual = state.get("is_conceptual", False)
    print(f"\n[SolutionProvider] Starting  files={len(research_files)}  is_conceptual={is_conceptual}")
    log.info("[SolutionProvider] start files=%d conceptual=%s", len(research_files), is_conceptual)

    try:
        slack_client = create_slack_client()

        # Case 1: deep_researcher encountered an unrecoverable error
        if state.get("research_error") and state.get("response_text"):
            final_message = (state["response_text"] or "").strip()
            print(f"[SolutionProvider] ✗ Research error path — sending error message ({len(final_message)} chars)")
            log.warning("[SolutionProvider] research error fallback len=%d", len(final_message))
            slack_client.send_message(channel=channel_id, text=final_message, thread_ts=thread_ts)
            _persist(db, logger, thread_ts, user_id, user_query, state["message_ts"], final_message)

            print(f"[SolutionProvider] Error message: {final_message}")

            return state

        # Case 2: no files found and it wasn't a conceptual question → explicit admission
        if not research_files and not is_conceptual:
            print("[SolutionProvider] ⚠ No research files found — sending not-enough-info message")
            log.info("[SolutionProvider] no files, not conceptual — sending not-enough-info")
            slack_client.send_message(channel=channel_id, text=_NOT_ENOUGH_INFO, thread_ts=thread_ts)
            state["response_text"] = _NOT_ENOUGH_INFO
            _persist(db, logger, thread_ts, user_id, user_query, state["message_ts"], _NOT_ENOUGH_INFO)
            print(f"[SolutionProvider] Not enough info message: {_NOT_ENOUGH_INFO}")
            return state

        # Case 3: normal path — generate answer with LLM
        print(f"[SolutionProvider] 🤖 Generating answer (files={len(research_files)}, conceptual={is_conceptual})...")
        log.info("[SolutionProvider] generating answer files=%d", len(research_files))
        try:
            final_message = asyncio.run(_generate_solution(state))
        except Exception as gen_err:
            print(f"[SolutionProvider] ✗ LLM generation failed: {gen_err}")
            logger.logger.warning("[SolutionProvider] LLM call failed: %s", gen_err)
            final_message = _NOT_ENOUGH_INFO

        final_message = (final_message or _NOT_ENOUGH_INFO).strip()
        state["response_text"] = final_message

        print(f"[SolutionProvider] Answer message: {final_message}")
        print("-"*100)
        print(f"[SolutionProvider] ✓ Answer ready ({len(final_message)} chars) — sending to Slack")
        log.info("[SolutionProvider] answer len=%d", len(final_message))
        slack_client.send_message(channel=channel_id, text=final_message, thread_ts=thread_ts)

        _persist(db, logger, thread_ts, user_id, user_query, state["message_ts"], final_message)

    except Exception as e:
        logger.log_error(
            error_type="SolutionProviderError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )

    return state


def _persist(db, logger, thread_ts: str, user_id: str, user_query: str, message_ts: str, agent_reply: str) -> None:
    try:
        db.save_message(thread_ts, user_id, "user", user_query, message_ts)
        db.save_message(thread_ts, None, "agent", agent_reply, message_ts + "_agent")
        logger.logger.info("[SolutionProvider] persisted user+agent messages")
    except Exception as persist_err:
        logger.logger.warning("[SolutionProvider] failed to persist messages: %s", persist_err)
