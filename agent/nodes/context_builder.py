"""
Context Builder Node - Loads user history and thread context.
"""

from typing import Dict, Any

from agent.state import ConversationState
from agent.persistence import get_database
from agent.slack_client import create_slack_client
from agent.logger import get_logger, EventType
from agent.config import Config


def build_context(state: ConversationState) -> ConversationState:
    """
    Build context by loading user history and thread context.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with context loaded
    """
    logger = get_logger()
    db = get_database()
    
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts")
    
    try:
        # Get or create user profile
        user_profile = db.get_user_profile(user_id)
        
        if not user_profile:
            # Create new profile from Slack
            slack_client = create_slack_client()
            user_info = slack_client.get_user_info(user_id)
            
            profile_data = user_info.get("profile", {})
            db.update_user_profile(
                user_id=user_id,
                username=user_info.get("name", ""),
                real_name= profile_data.get("real_name", ""),
                email=profile_data.get("email")
            )
            
            user_profile = db.get_user_profile(user_id)
        
        state["user_profile"] = user_profile
        
        # Get user's previous messages (for context)
        previous_messages = db.get_user_recent_messages(
            user_id=user_id,
            limit=Config.MAX_CONTEXT_MESSAGES
        )
        state["previous_messages"] = previous_messages
        
        # If in a thread, get thread context
        thread_context = []
        if thread_ts:
            thread_context = db.get_thread_messages(thread_ts)
            
            # Also get from Slack API to ensure we have the latest
            slack_client = create_slack_client()
            slack_thread = slack_client.get_thread_messages(
                channel=channel_id,
                thread_ts=thread_ts,
                limit=10
            )
            
            # Merge (prefer database records for context, but add new Slack messages)
            existing_ts = {msg["message_ts"] for msg in thread_context}
            for slack_msg in slack_thread:
                if slack_msg["ts"] not in existing_ts:
                    thread_context.append({
                        "message_ts": slack_msg["ts"],
                        "user_id": slack_msg.get("user", ""),
                        "message_text": slack_msg.get("text", ""),
                        "created_at": slack_msg["ts"]
                    })
        
        state["thread_context"] = thread_context
        
        # Log context loading
        logger.log_event(
            event_type=EventType.CONTEXT_LOADED,
            message=f"Loaded context: {len(previous_messages)} previous messages, {len(thread_context)} thread messages",
            user_id=user_id,
            channel_id=channel_id,
            metadata={
                "user_profile": {
                    "knowledge_level": user_profile.knowledge_level if user_profile else "beginner",
                    "total_messages": user_profile.total_messages if user_profile else 0
                },
                "previous_messages_count": len(previous_messages),
                "thread_context_count": len(thread_context)
            }
        )
        
    except Exception as e:
        logger.log_error(
            error_type="ContextLoadingError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        
        # Fallback to empty context
        state["user_profile"] = None
        state["previous_messages"] = []
        state["thread_context"] = []
    
    return state
