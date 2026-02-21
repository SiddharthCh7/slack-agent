"""
Clarification Asker Node — Sends 1–2 focused questions to the user.

Redesign principles:
  - Max 2 questions, always — enforced at LLM-prompt AND code level
  - Questions use the Alex persona: direct, human-phrased, like a Slack message
  - Questions sourced from deep_reasoner's clarification_questions[] — already
    formatted as specific, complete questions
  - If reasoner supplied good questions, uses them directly (no second LLM call)
  - Falls back to LLM generation only if questions list is empty
  - OLake context injected so questions can reference product-specific terms
"""

from __future__ import annotations
import asyncio
import json
import re
from datetime import datetime
from typing import Dict, Any, List

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger, EventType
from agent.llm import get_chat_completion
from agent.config import OLAKE_CONTEXT

_PARSE_RE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _parse_json(text: str | None) -> list:
    if not text:
        raise ValueError("LLM returned empty")
    text = _PARSE_RE_FENCE.sub("", text.strip())
    return json.loads(text)


# System prompt for fallback question generation
_SYSTEM_PROMPT = f"""You are Alex, a senior OLake support engineer.

About OLake:
{OLAKE_CONTEXT.strip()}

Your job: generate 1–2 clarifying questions to send to a user who posted a support question.

Rules for questions:
  - Max 2. If 1 is enough, use 1.
  - Each question is a single sentence ending with "?"
  - Phrased like you'd ask on Slack — direct, not formal
  - Reference specific OLake concepts when relevant (connector, sync mode, destination, etc.)
  - Never compound multiple questions into one sentence
  - Never start with "Could you please" or "Would you be able to"
  - Bad: "Could you kindly provide details about your PostgreSQL deployment type and version?"
  - Good: "What PostgreSQL version are you on?" and "Is this on RDS, Aurora, or self-hosted?"

Return a JSON array of question strings. No preamble.
Example: ["What PostgreSQL version are you running?", "Are you using CDC or full-refresh mode?"]"""


def _format_questions_as_slack(questions: List[str]) -> str:
    """
    Format 1–2 questions as a natural Slack reply.
    Avoids numbered lists for a single question.
    """
    qs = [q.strip() for q in questions if q.strip()][:2]
    if not qs:
        return "Could you share a bit more context?"
    if len(qs) == 1:
        return f"Quick question — {qs[0]}" if not qs[0][0].isupper() else qs[0]
    return "A couple of quick questions:\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs))


async def clarification_asker(state: ConversationState) -> Dict[str, Any]:
    logger = get_logger()
    db = get_database()

    user_id    = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts  = state.get("thread_ts") or state["message_ts"]
    message_text = state["message_text"]

    # Questions may already be set by deep_reasoner
    questions: List[str] = state.get("clarification_questions", [])

    try:
        slack_client = create_slack_client()

        slack_client.add_reaction(
            channel=channel_id,
            timestamp=state["message_ts"],
            emoji="thinking_face",
        )

        # Generate questions if reasoner didn't provide any
        if not questions:
            problem_summary = state.get("problem_summary") or message_text
            gaps = []
            for it in state.get("reasoning_iterations", []):
                gaps.extend(it.identified_gaps)
            gaps = list(dict.fromkeys(gaps))[:4]

            prompt = f"""User asked: "{message_text}"
Problem summary: {problem_summary}
Information gaps: {gaps}

Generate 1–2 clarifying questions. Return JSON array only."""

            response = await get_chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.3,
            )
            questions = _parse_json(response) if response else []
            questions = [q for q in questions if isinstance(q, str)][:2]

        message_body = _format_questions_as_slack(questions)

        # Send to Slack thread
        slack_client.send_message(
            channel=channel_id,
            text=message_body,
            thread_ts=thread_ts,
        )

        state["response_text"] = message_body
        state["clarification_questions"] = questions

        logger.log_event(
            event_type=EventType.CLARIFICATION_SENT,
            message=f"Sent {len(questions)} clarification question(s)",
            user_id=user_id,
            channel_id=channel_id,
            metadata={"questions": questions},
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
                response_text=message_body,
                confidence=state.get("final_confidence", 0.0),
                needs_clarification=True,
                escalated=False,
                escalation_reason=None,
                docs_cited=None,
                reasoning_summary=state.get("reasoning_trace", ""),
                processing_time=0.0,
                created_at=datetime.now(),
                resolved=False,
                resolved_at=None,
            ))
        except Exception:
            pass

    except Exception as e:
        logger.log_error(
            error_type="ClarificationError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )

    return state


def clarification_asker_sync(state: ConversationState) -> ConversationState:
    return asyncio.run(clarification_asker(state))
