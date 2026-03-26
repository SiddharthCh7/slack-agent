# Not yet used

"""
Thread Summariser — independent DB-aware component.

Usage:
    from agent.nodes.summariser import summarise_thread
    result = summarise_thread("1234567890.123456")
    # -> {"summary": "..."}

How it works:
  1. Load (prior_summary, summarised_through_ts) from DB for the given thread.
  2. Load all messages with message_ts > summarised_through_ts (not yet in summary).
  3. If no new messages, return existing summary unchanged (no LLM call, no write).
  4. Otherwise call LLM to merge prior_summary + new conversation turns into one
     updated consolidated summary.
  5. Persist the new summary and advance summarised_through_ts to the last
     included message. Messages written to DB after this point are not affected.
  6. Return {"summary": "..."}.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from agent.config import AGENT_NAME, COMPANY_NAME
from agent.utils.llm import get_chat_completion
from agent.filesystem.persistence import get_database
from agent.utils.parser import parse_llm_json

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are a conversation memory manager for a {COMPANY_NAME} support agent called {AGENT_NAME}.

Your job: given the previous summary of a support thread (if any) and a set of \
new conversation turns that are NOT yet reflected in that summary, produce one \
updated, consolidated summary that covers everything — replacing the old summary.

OUTPUT FORMAT — return ONLY valid JSON, no markdown fences, no extra text:
{{"summary": "..."}}

WRITING RULES:
- Write strictly in first person from {AGENT_NAME}'s perspective ("I", "I searched", \
"I answered", "The user asked", "I clarified").
- The summary must stand alone — a reader with no prior context should fully \
understand the conversation from it.
- Structure with concise labelled sections followed by bullet points, for example:

  Question: <what the user asked>
  Intent: <what I understood they needed — only if meaningfully different from question>
  Actions: <what I did at a high level — searches run, files found, reasoning>
  Answer: <what I told the user>
  Follow-ups: <any subsequent user questions and how I handled them, if any>

- Keep each bullet to one sentence.
- Consolidate — do NOT repeat information already in the prior summary verbatim; \
absorb it. Remove content that is superseded or contradicted by newer turns.
- Omit noise: do not include raw model reasoning steps, internal chain-of-thought, \
search iteration details, or file paths unless they are the answer itself.
- Never include backticks in the output string.
- The summary should be short enough to fit in a system prompt (target < 400 words).\
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_messages(messages: List[Dict]) -> str:
    """
    Render a list of {role, content, message_ts} rows as a readable transcript.
    Pairs are grouped so the LLM sees user → agent exchanges clearly.
    """
    if not messages:
        return "(none)"
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        label = "User" if role == "user" else f"Agent ({AGENT_NAME})"
        lines.append(f"[{label}]: {content}")
    return "\n\n".join(lines)


def _build_user_prompt(
    prior_summary: Optional[str],
    new_messages: List[Dict],
) -> str:
    prior_block = prior_summary.strip() if prior_summary else "(No prior summary exists)"
    messages_block = _format_messages(new_messages)

    return f"""\
Produce an updated consolidated summary for this conversation thread.

---
PRIOR SUMMARY (already consolidated; do not repeat verbatim — absorb and update):
{prior_block}

---
NEW CONVERSATION TURNS (These are the new messages that are not yet in the summary above; integrate these):
{messages_block}

---
Return strict JSON only: {{"summary":"..."}}\
"""


# ---------------------------------------------------------------------------
# Core async logic
# ---------------------------------------------------------------------------

async def _summarise_async(
    thread_id: str,
    prior_summary: Optional[str],
    new_messages: List[Dict],
) -> str:
    
    print(f"(Summariser) Input characters count: {len(_build_user_prompt(prior_summary, new_messages)) + len(_SYSTEM_PROMPT)}")

    response = await get_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(prior_summary, new_messages)},
        ],
        temperature=0.2,
    )

    parsed = parse_llm_json(response)
    summary = parsed.get("summary") if isinstance(parsed, dict) else None

    if not isinstance(summary, str) or not summary.strip():
        log.warning("[Summariser] LLM returned invalid/empty summary for thread %s", thread_id)
        # Preserve prior summary so we never overwrite with garbage
        return prior_summary or ""

    return summary.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def summarise_thread(thread_id: str) -> Dict[str, str]:
    """
    Summarise a thread using only DB data — independent of current graph execution.

    Args:
        thread_id: Slack thread_ts (or message_ts for top-level posts).

    Returns:
        {"summary": "<updated summary text>"}
        If there were no new messages, returns existing summary without touching DB.
    """
    db = get_database()

    # Step 1: load current state from DB
    prior_summary, summarised_through_ts = db.get_thread_summary(thread_id)

    # Step 2: messages not yet included in summary
    new_messages = db.get_thread_messages_after(
        thread_id=thread_id,
        after_ts=summarised_through_ts,  # "" or "0" → all messages when no prior summary
    )

    # Step 3: nothing new — return without LLM call or DB write
    if not new_messages:
        log.debug("[Summariser] No new messages for thread %s; skipping.", thread_id)
        return {"summary": prior_summary or ""}

    # Step 4: build updated summary via LLM
    try:
        new_summary = asyncio.run(
            _summarise_async(thread_id, prior_summary, new_messages)
        )
    except Exception as e:
        log.warning("[Summariser] LLM call failed for thread %s: %s", thread_id, e)
        return {"summary": prior_summary or ""}

    # Step 5: advance cutoff only to the last message we actually processed
    new_cutoff = new_messages[-1]["message_ts"]

    # Step 6: persist
    try:
        db.upsert_thread_summary(
            thread_id=thread_id,
            summary=new_summary,
            summarised_through_ts=new_cutoff,
        )
    except Exception as e:
        log.warning("[Summariser] DB write failed for thread %s: %s", thread_id, e)

    return {"summary": new_summary}
