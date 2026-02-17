"""
Solution Provider Node - Generates and sends solution to user.
"""

from typing import Dict, Any
import json
from datetime import datetime

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger
from agent.config import Config


def solution_provider(state: ConversationState) -> ConversationState:
    """
    Provide solution to the user based on reasoning results.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with response sent
    """
    logger = get_logger()
    slack_client = create_slack_client()
    db = get_database()
    
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts") or state["message_ts"]
    
    response_text = state.get("response_text", "")
    final_confidence = state.get("final_confidence", 0.0)
    retrieved_docs = state.get("retrieved_docs", [])
    reasoning_iterations = state.get("reasoning_iterations", [])
    
    try:
        # Add thumbs up reaction to acknowledge
        slack_client.add_reaction(
            channel=channel_id,
            timestamp=state["message_ts"],
            emoji="white_check_mark"
        )
        
        # Prepare citations
        docs_cited = []
        if retrieved_docs:
            docs_cited = [
                {"title": doc.title, "url": doc.url}
                for doc in retrieved_docs[:3]
            ]
        
        # Format response with Block Kit
        response_blocks = slack_client.format_response_blocks(
            response_text=response_text,
            confidence=final_confidence,
            docs_cited=docs_cited,
            is_clarification=False,
            is_escalation=False
        )
        
        # Send response
        slack_client.send_message(
            channel=channel_id,
            text=response_text,  # Fallback text
            thread_ts=thread_ts,
            blocks=response_blocks
        )
        
        state["response_blocks"] = response_blocks
        
        # Create reasoning summary
        reasoning_summary = "\n".join([
            f"Iteration {r.iteration}: {r.thought_process[:100]}..."
            for r in reasoning_iterations
        ])
        
        # Log response
        logger.log_response_sent(
            user_id=user_id,
            channel_id=channel_id,
            response_text=response_text,
            confidence=final_confidence,
            reasoning_summary=reasoning_summary,
            thread_ts=thread_ts,
            docs_cited=docs_cited
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
            response_text=response_text,
            confidence=final_confidence,
            needs_clarification=False,
            escalated=False,
            escalation_reason=None,
            docs_cited=json.dumps(docs_cited),
            reasoning_summary=reasoning_summary,
            processing_time=processing_time,
            created_at=state["processing_start_time"],
            resolved=True,
            resolved_at=datetime.now()
        )
        
        db.save_conversation(conversation_record)
        
        # Update user profile
        slack_user = slack_client.get_user_info(user_id)
        profile = slack_user.get("profile", {})
        db.update_user_profile(
            user_id=user_id,
            username=slack_user.get("name", ""),
            real_name=profile.get("real_name", ""),
            email=profile.get("email")
        )
        
    except Exception as e:
        logger.log_error(
            error_type="SolutionProviderError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        state["error"] = str(e)
    
    return state
