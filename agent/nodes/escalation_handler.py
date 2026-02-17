"""
Escalation Handler Node - Escalates to human team when needed.
"""

from typing import Dict, Any
import json
from datetime import datetime

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger
from agent.config import Config


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
    
    # Determine escalation reason
    escalation_reason = state.get("escalation_reason")
    if not escalation_reason:
        final_confidence = state.get("final_confidence", 0.0)
        if final_confidence < Config.CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY:
            escalation_reason = f"Low confidence ({final_confidence:.2f}), needs human expertise"
        else:
            escalation_reason = "Unable to determine appropriate response"
    
    try:
        # Add alert emoji
        slack_client.add_reaction(
            channel=channel_id,
            timestamp=state["message_ts"],
            emoji="rotating_light"
        )
        
        # Prepare escalation message
        escalation_message = f"""Thanks for reaching out! I've analyzed your question, but I think this needs expert attention from our team.

**Reason**: {escalation_reason}

{f'<@{Config.ESCALATION_USERS[0]}>' if Config.ESCALATION_USERS else 'A team member'} will assist you shortly! ⏱️

In the meantime, you might find these resources helpful:
• 📚 [OLake Documentation](https://olake.io/docs/)
• 💬 [GitHub Discussions](https://github.com/datazip-inc/olake/discussions)
• 🐛 [Report an Issue](https://github.com/datazip-inc/olake/issues)
"""
        
        # Format with Block Kit
        response_blocks = slack_client.format_response_blocks(
            response_text=escalation_message,
            confidence=0.0,
            docs_cited=None,
            is_clarification=False,
            is_escalation=True
        )
        
        # Send escalation message
        slack_client.send_message(
            channel=channel_id,
            text=escalation_message,
            thread_ts=thread_ts,
            blocks=response_blocks
        )
        
        # Notify escalation users (if configured)
        if Config.ESCALATION_USERS:
            for escalation_user_id in Config.ESCALATION_USERS:
                try:
                    notification_text = f"""🚨 *Escalation Alert*

*User*: <@{user_id}>
*Channel*: <#{channel_id}>
*Message*: {message_text[:200]}...

*Reason*: {escalation_reason}

*Thread*: https://slack.com/app_redirect?channel={channel_id}&message_ts={thread_ts}
"""
                    
                    slack_client.send_message(
                        channel=escalation_user_id,  # DM
                        text=notification_text,
                        blocks=None
                    )
                except Exception as notify_error:
                    logger.logger.warning(
                        f"Failed to notify {escalation_user_id}: {notify_error}"
                    )
        
        state["response_text"] = escalation_message
        state["response_blocks"] = response_blocks
        
        # Log escalation
        logger.log_escalation(
            user_id=user_id,
            channel_id=channel_id,
            reason=escalation_reason,
            original_message=message_text,
            thread_ts=thread_ts
        )
        
        # Save to database
        processing_time = (
            (datetime.now() - state["processing_start_time"]).total_seconds()
        )
        
        conversation_record = ConversationRecord(
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
            resolved_at=None
        )
        
        db.save_conversation(conversation_record)
        
    except Exception as e:
        logger.log_error(
            error_type="EscalationHandlerError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        state["error"] = str(e)
    
    return state
