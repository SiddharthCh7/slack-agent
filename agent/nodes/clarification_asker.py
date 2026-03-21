"""
Clarification Asker Node — Sends 1-2 focused questions to the user.

Redesign principles:
  - Max 2 questions, always — enforced at LLM-prompt AND code level
  - Questions use the Alex persona: direct, human-phrased, like a Slack message
  - Questions sourced from deep_researcher's clarification_questions[] — already
    formatted as specific, complete questions
  - If reasoner supplied good questions, uses them directly (no second LLM call)
  - Falls back to LLM generation only if questions list is empty
  - OLake context injected so questions can reference product-specific terms
"""

from __future__ import annotations
import asyncio
from typing import Dict, Any, List

from agent.state import ConversationState
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger, EventType
from agent.llm import get_chat_completion
from agent.config import ABOUT_OLAKE
from agent.utils.parser import parse_json_list as _parse_json


# System prompt for fallback question generation
_SYSTEM_PROMPT_TEMPLATE = """You are Alex, a senior OLake support engineer.

About OLake:
{about_olake}

Your job: generate 1-2 clarifying questions to send to a user who posted a support question.

Rules for questions:
  - Max 2. If 1 is enough, use 1.
  - Each question is a single sentence ending with "?"
  - Phrased like you'd ask on Slack — direct, not formal
  - Reference specific OLake concepts when relevant (connector, sync mode, destination, etc.)
  - Never compound multiple questions into one sentence
  - Never start with "Could you please" or "Would you be able to"
  - VERY IMPORTANT: ONLY ask about user-specific context (their version, their config, their logs, what database they use).
  - NEVER ask the user about OLake system capabilities or if OLake supports a feature. You are the expert. If you internalize a gap like "I don't know if OLake has an API", DO NOT ask the user. Instead, ask them what they are trying to achieve.
  - Bad: "Does OLake provide a REST API?" or "Could you kindly provide details about your PostgreSQL deployment type and version?"
  - Good: "What PostgreSQL version are you on?" and "Is this on RDS, Aurora, or self-hosted?"

Return a JSON array of question strings. No preamble.
Example: ["What PostgreSQL version are you running?", "Are you using CDC or full-refresh mode?"]"""


def _clarification_system_prompt(state: ConversationState) -> str:
    about = (state.get("about_olake_summary") or ABOUT_OLAKE).strip()
    return _SYSTEM_PROMPT_TEMPLATE.format(about_olake=about)


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
    user_query = state["user_query"]

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
            gaps = []
            for it in state.get("reasoning_iterations", []):
                gaps.extend(it.identified_gaps)
            gaps = list(dict.fromkeys(gaps))[:4]

            prompt = f"""User asked: "{user_query}"
Internal Agent Gaps: {gaps} (Do NOT ask the user to solve these gaps for you. Only ask for context about their setup.)

Generate 1-2 clarifying questions about the USER'S specific setup or intent. Return JSON array only."""

            response = await get_chat_completion(
                messages=[
                    {"role": "system", "content": _clarification_system_prompt(state)},
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
            message_ts = state["message_ts"]
            db.save_message(thread_ts, user_id, "user", user_query, message_ts)
            db.save_message(thread_ts, None, "agent", message_body, message_ts + "_agent")
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
