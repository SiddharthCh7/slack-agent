"""
Solution Provider Node — Formats and sends the final answer in-thread.

Redesign:
  - No second LLM call if deep_reasoner already drafted response_text (high confidence)
  - Second LLM call only when response_text is missing/empty OR needs substantial polish
  - Alex persona in all formatting
  - Cites max 3 doc sources with exact URLs (from chunk metadata — fixed in new RAG service)
  - Confidence-gated: hides "Confidence: X%" unless asked — avoids eroding user trust
  - At low confidence (<0.6), appends a soft "This might not be the full picture — 
    feel free to ask follow-up questions" note
"""

from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger
from agent.llm import get_chat_completion
from agent.config import Config, OLAKE_CONTEXT

_PARSE_RE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

# Sentence-ending punctuation that signals a complete thought
_SENTENCE_ENDINGS = (".", "!", "?", "…", ":", "```")


def _looks_truncated(text: str) -> bool:
    """Return True if text appears to end mid-sentence (token-limit cut-off)."""
    stripped = text.rstrip()
    return bool(stripped) and not stripped.endswith(_SENTENCE_ENDINGS)

# Alex persona system prompt — injected into polish pass
_ALEX_SYSTEM = f"""You are Alex, a senior support engineer at OLake/Datazip.

About OLake:
{OLAKE_CONTEXT.strip()}

Your job: take a draft answer and return a final formatted Slack reply.

Tone rules:
  - Professional and human. Like messaging a colleague on Slack, not filing a ticket.
  - Lead with the answer or action, not with acknowledgment.
  - Use "you/your". No passive voice for instructions.
  - For step-by-step fixes: numbered list, each step one action.
  - For conceptual answers: 2–4 short paragraphs max.
  - No "Great question!" / "Certainly!" / "Of course!" openers.
  - No trailing "Please let me know if you have any further questions." — use a
    specific follow-up offer if needed ("Does that fix it?" or "Let me know if
    the replication slot error still appears after this.")
  - One emoji max, only if it adds clarity (✅ ❌). Never decorative.
  - End phrases like "Let me know if..." go at the end only — never mid-sentence.
  - If citing documentation, format as: "See the [section name] docs: <URL|link text>"
  - Keep the whole reply under 300 words. Shorter is usually better.

Do NOT quote documentation text verbatim — use it only to inform your own words.
Do NOT start a sentence mid-thought or include disconnected words like "Follow" or "Steps".

Return the final Slack message text only — no JSON, no markdown wrapper."""


def _build_doc_citations(docs: list) -> str:
    """Build a short doc-reference block (max 3 docs)."""
    if not docs:
        return ""
    lines = []
    seen_urls = set()
    for doc in docs[:3]:
        title = doc.title if hasattr(doc, "title") else doc.get("title", "OLake Docs")
        url = doc.url if hasattr(doc, "url") else doc.get("url", "https://olake.io/docs/")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        lines.append(f"• <{url}|{title}>")
    if not lines:
        return ""
    return "\n*Relevant docs:*\n" + "\n".join(lines)


async def _polish_answer(
    draft: str,
    message_text: str,
    docs: list,
    confidence: float,
    problem_summary: str,
) -> str:
    """
    Optional LLM polish pass — only called when draft is missing or low-quality.
    """
    doc_context = ""
    if docs:
        snippets = []
        for d in docs[:4]:
            content = d.content if hasattr(d, "content") else d.get("text", "")
            url = d.url if hasattr(d, "url") else d.get("doc_url", "")
            # Label each doc clearly and limit size to prevent LLM from parroting
            snippets.append(f"[REFERENCE DOC — do not copy verbatim]\nURL: {url}\n{content[:300]}")
        doc_context = "\n\n---\n".join(snippets)

    prompt = f"""User question: "{message_text}"
Problem summary: {problem_summary}

Draft answer (refine this — if empty, write from scratch based on your expertise):
{draft or "(none — use docs below to inform a concise answer in your own words)"}

Reference documentation (use for facts/URLs only — do NOT copy sentences verbatim):
{doc_context or "(none available)"}

Confidence level: {confidence:.0%}

Write the final Slack reply. Start directly with the answer — no preamble."""

    response = await get_chat_completion(
        messages=[
            {"role": "system", "content": _ALEX_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.4,
        # max_tokens=600,
    )
    return (response or "").strip()


def solution_provider(state: ConversationState) -> ConversationState:
    """
    Format and send the final answer.
    Uses asyncio.run to call the async polish pass when needed.
    """
    logger = get_logger()
    db = get_database()

    user_id       = state["user_id"]
    channel_id    = state["channel_id"]
    thread_ts     = state.get("thread_ts") or state["message_ts"]
    message_text  = state["message_text"]
    response_text = state.get("response_text", "") or ""
    confidence    = state.get("final_confidence", 0.0)
    retrieved_docs = state.get("retrieved_docs", [])
    doc_sufficient = state.get("doc_sufficient", False)
    problem_summary = state.get("problem_summary") or message_text

    try:
        slack_client = create_slack_client()

        slack_client.add_reaction(
            channel=channel_id,
            timestamp=state["message_ts"],
            emoji="white_check_mark",
        )

        # Decide whether to polish: skip if draft is good (>= 80 chars and confident)
        needs_polish = (
            not response_text
            or len(response_text) < 80
            or confidence < 0.45
            or _looks_truncated(response_text)   # catch mid-sentence token cut-offs
        )

        # Guard: if confidence is very low AND no real draft, don't hallucinate.
        # Instead send a humble fallback rather than an LLM-generated guess.
        if confidence < 0.15 and not response_text:
            response_text = (
                "I wasn't able to find specific information to address your question right now. "
                "Could you share any error messages or logs you're seeing? "
                "That'll help me point you in the right direction."
            )
            needs_polish = False

        if needs_polish:
            response_text = asyncio.run(_polish_answer(
                draft=response_text,
                message_text=message_text,
                docs=retrieved_docs,
                confidence=confidence,
                problem_summary=problem_summary,
            ))

        # Low-confidence soft note
        if confidence < 0.6 and not state.get("doc_sufficient"):
            response_text += "\n\nIf this doesn't fully address your issue, let me know — I may need a bit more context."

        # Append doc citations
        citations = _build_doc_citations(retrieved_docs)

        final_message = (response_text + (citations if citations else "")).strip()
        state["response_text"] = final_message

        # Build Slack blocks
        docs_cited_list = []
        if retrieved_docs:
            docs_cited_list = [
                {
                    "title": d.title if hasattr(d, "title") else d.get("title", ""),
                    "url": d.url if hasattr(d, "url") else d.get("url", ""),
                    "source": d.source_type if hasattr(d, "source_type") else d.get("source", "docs"),
                }
                for d in retrieved_docs[:3]
            ]

        blocks = slack_client.format_response_blocks(
            response_text=final_message,
            confidence=confidence,
            docs_cited=docs_cited_list if doc_sufficient else None,
            is_clarification=False,
            is_escalation=False,
        )
        state["response_blocks"] = blocks

        slack_client.send_message(
            channel=channel_id,
            text=final_message,
            thread_ts=thread_ts,
            blocks=blocks,
        )

        logger.logger.info(
            f"[SolutionProvider] sent answer confidence={confidence:.2f} len={len(final_message)}"
        )

        # Persist
        try:
            db.save_conversation(ConversationRecord(
                id=None,
                message_ts=state["message_ts"],
                thread_ts=thread_ts,
                channel_id=channel_id,
                user_id=user_id,
                message_text=message_text,
                intent_type=str(state.get("intent_type", "")),
                urgency=str(state.get("urgency", "")),
                response_text=final_message,
                confidence=confidence,
                needs_clarification=False,
                escalated=False,
                escalation_reason=None,
                docs_cited=json.dumps(docs_cited_list),
                reasoning_summary=state.get("reasoning_trace", ""),
                processing_time=0.0,
                created_at=datetime.now(),
                resolved=True,
                resolved_at=datetime.now(),
            ))
        except Exception:
            pass

    except Exception as e:
        logger.log_error(
            error_type="SolutionProviderError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )

    return state
