"""
Solution provider for CLI mode.

Generates the final answer via LLM and persists to DB. No Slack API calls.
"""

from __future__ import annotations
import asyncio
from typing import List

from agent.state import ConversationState
from agent.persistence import get_database
from agent.logger import get_logger
from agent.llm import get_chat_completion
from agent.config import ABOUT_OLAKE

_NOT_ENOUGH_INFO = (
    "I wasn't able to find enough information in the codebase to answer this confidently. "
    "Could you share more details about what you're trying to do?"
)

_ALEX_SYSTEM_TEMPLATE = """You are Alex, a senior support engineer on the OLake team. You answer as part of OLake — use "we" and "our". Never refer to OLake as "they" or "their."

About OLake:
{about_olake}

Your job: Answer the user's question using the reference files provided.

Rules:
  - Speak as a teammate. Base your answer ONLY on the reference files.
  - If the files don't describe a feature at all, say so honestly — do NOT guess.
  - Lead with the answer, no preambles.
  - Use "you/your" for the user. For procedural steps, use short numbered/bulleted lists.
  - Under 300 words.
  - Use "we"/"our" or "OLake" when referring to OLake — never "they" or "their".

Return the final message text only — no JSON, no markdown wrapper."""


def _alex_system(state: ConversationState) -> str:
    about = (state.get("about_olake_summary") or ABOUT_OLAKE).strip()
    return _ALEX_SYSTEM_TEMPLATE.format(about_olake=about)


def _build_history_block(state: ConversationState, max_messages: int = 6) -> str:
    lines: List[str] = []
    for msg in (state.get("thread_context") or [])[-max_messages:]:
        text = (msg.get("content") or "").strip()
        if not text:
            continue
        label = "agent" if msg.get("role") == "agent" else "user"
        lines.append(f"- {label}: {text}")
    return "\n".join(lines) if lines else "(none)"


def _build_files_block(research_files: list, max_files: int = 8, max_snippet: int = 300) -> str:
    if not research_files:
        return "(none)"
    parts: List[str] = []
    for idx, f in enumerate(research_files[:max_files], 1):
        path = f.path if hasattr(f, "path") else f.get("path", "")
        reason = (f.retrieval_reason if hasattr(f, "retrieval_reason") else f.get("retrieval_reason", "")) or ""
        content = (f.content if hasattr(f, "content") else f.get("content", "")) or ""
        snippet = content.strip().replace("\n", " ")[:max_snippet]
        parts.append(f"{idx}. {path}\n   Why: {reason}\n   Snippet: {snippet}")
    return "\n".join(parts)


async def _generate_answer(state: ConversationState) -> str:
    user_query = state["user_query"]
    research_files = state.get("research_files") or []
    thread_summary = state.get("thread_summary") or ""

    history_block = _build_history_block(state)
    files_block = _build_files_block(research_files)
    summary_section = f"\nThread summary (earlier context):\n{thread_summary}\n" if thread_summary else ""

    user_prompt = f"""User question:
{user_query}
{summary_section}
Conversation so far (most recent messages last):
{history_block}

Reference files:
{files_block}

Answer the question using only the context above. If it isn't there, say so in one sentence.

Write the final reply."""

    response = await get_chat_completion(
        messages=[
            {"role": "system", "content": _alex_system(state)},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    return (response or "").strip()


def cli_solution_provider(state: ConversationState) -> ConversationState:
    """Format final answer for CLI mode and persist to DB."""
    logger = get_logger()

    user_id = state["user_id"]
    user_query = state["user_query"]
    research_files = state.get("research_files") or []
    is_conceptual = state.get("is_conceptual", False)

    try:
        # No files and not a conceptual question → explicit admission
        if not research_files and not is_conceptual:
            logger.logger.info("[CLISolutionProvider] no research files; sending not-enough-info message")
            state["response_text"] = _NOT_ENOUGH_INFO
            _persist(logger, state)
            return state

        # Generate answer
        try:
            final_message = asyncio.run(_generate_answer(state))
        except Exception as gen_err:
            logger.logger.warning("[CLISolutionProvider] LLM call failed: %s", gen_err)
            final_message = _NOT_ENOUGH_INFO

        final_message = (final_message or _NOT_ENOUGH_INFO).strip()
        state["response_text"] = final_message

        logger.logger.info("[CLISolutionProvider] generated answer len=%d", len(final_message))
        _persist(logger, state)

    except Exception as e:
        logger.log_error(
            error_type="CLISolutionProviderError",
            error_message=str(e),
            user_id=user_id,
            channel_id="cli_channel",
        )

    return state


def _persist(logger, state: ConversationState) -> None:
    try:
        thread_ts = state.get("thread_ts")
        message_ts = state["message_ts"]
        thread_id = thread_ts if thread_ts else message_ts
        db = get_database()
        db.save_message(thread_id, state["user_id"], "user", state["user_query"], message_ts)
        db.save_message(thread_id, None, "agent", state.get("response_text", ""), message_ts + "_agent")
    except Exception as e:
        logger.logger.warning("[CLISolutionProvider] failed to persist: %s", e)
