"""
Escalation Handler Node — Escalates to the right OLake team member when the agent can't help.

Uses team_resolver to:
  1. Pick the correct person based on issue type (Engineering vs Product)
  2. Format proper <@USERID> Slack mentions
  3. Send DM notifications to the escalation targets
  4. Reply in-thread so all context stays in one place
"""

from typing import Dict, Any
import json
from datetime import datetime

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger
from agent.team_resolver import (
    get_escalation_targets,
    format_escalation_message,
    resolve_mention,
)


def escalation_handler(state: ConversationState) -> ConversationState:
    """
    Escalate to human team when agent cannot handle the request.

    Args:
        state: Current conversation state

    Returns:
        Updated state with escalation handled
    """
    logger = get_logger()
    slack_client = create_slack_client()
    db = get_database()

    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts") or state["message_ts"]
    message_text = state["message_text"]

    escalation_reason = state.get("escalation_reason") or (
        f"Low confidence ({state.get('final_confidence', 0):.2f}) — needs human expertise"
    )

    try:
        # Add alert reaction
        slack_client.add_reaction(
            channel=channel_id,
            timestamp=state["message_ts"],
            emoji="rotating_light",
        )

        # Resolve who to tag based on issue content
        targets = get_escalation_targets(issue_text=message_text)

        # Build the in-thread escalation message
        escalation_message = format_escalation_message(
            targets=targets,
            issue_summary=message_text[:300],
        )

        # Append helpful links
        escalation_message += (
            "\n\n_Resources while you wait:_\n"
            "• <https://olake.io/docs/|OLake Documentation>\n"
            "• <https://github.com/datazip-inc/olake/discussions|GitHub Discussions>\n"
            "• <https://github.com/datazip-inc/olake/issues|Report an Issue>"
        )

        response_blocks = slack_client.format_response_blocks(
            response_text=escalation_message,
            confidence=0.0,
            docs_cited=None,
            is_clarification=False,
            is_escalation=True,
        )

        # Reply in-thread (always thread_ts so context is preserved)
        slack_client.send_message(
            channel=channel_id,
            text=escalation_message,
            thread_ts=thread_ts,
            blocks=response_blocks,
        )

        # DM each escalation target
        for target in targets:
            try:
                mention = resolve_mention(target["slack_name"])
                dm_text = (
                    f"🚨 *Escalation from OLake Slack Agent*\n\n"
                    f"*User:* <@{user_id}>\n"
                    f"*Channel:* <#{channel_id}>\n"
                    f"*Message:* {message_text[:300]}\n\n"
                    f"*Reason:* {escalation_reason}\n\n"
                    f"*Thread:* https://slack.com/app_redirect"
                    f"?channel={channel_id}&message_ts={thread_ts}"
                )
                slack_client.send_message(
                    channel=target["slack_name"],  # Slack resolves DM by username
                    text=dm_text,
                    blocks=None,
                )
            except Exception as dm_err:
                logger.logger.warning(
                    f"Failed to DM escalation target {target['slack_name']}: {dm_err}"
                )

        state["response_text"] = escalation_message
        state["response_blocks"] = response_blocks

        logger.log_escalation(
            user_id=user_id,
            channel_id=channel_id,
            reason=escalation_reason,
            original_message=message_text,
            thread_ts=thread_ts,
        )

        processing_time = (datetime.now() - state["processing_start_time"]).total_seconds()

        db.save_conversation(
            ConversationRecord(
                id=None,
                message_ts=state["message_ts"],
                thread_ts=thread_ts,
                channel_id=channel_id,
                user_id=user_id,
                message_text=state["message_text"],
                intent_type=state["intent_type"].value if state.get("intent_type") else "unknown",
                urgency=state["urgency"].value if state.get("urgency") else "medium",
                response_text=escalation_message,
                confidence=state.get("final_confidence", 0.0),
                needs_clarification=False,
                escalated=True,
                escalation_reason=escalation_reason,
                docs_cited=None,
                reasoning_summary=escalation_reason,
                processing_time=processing_time,
                created_at=state["processing_start_time"],
                resolved=False,
                resolved_at=None,
            )
        )

    except Exception as e:
        logger.log_error(
            error_type="EscalationHandlerError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        state["error"] = str(e)

    return state
