"""
Context Builder Node — Loads user history, thread context, and detects org-member presence.

Key behaviors:
  - Fetches thread messages from both the DB and Slack API
  - Annotates each thread message with `is_bot` flag (True if sent by this OLake agent)
  - Sets state["org_member_replied"] = True if any org team member has posted in the thread
    (detection uses slack_name matching via team_resolver)
"""

from typing import Dict, Any, List

from agent.state import ConversationState
from agent.persistence import get_database
from agent.slack_client import create_slack_client
from agent.logger import get_logger, EventType
from agent.config import Config
from agent.team_resolver import (
    is_org_member_by_name,
    is_org_member_by_id,
    get_bot_user_id,
)


def build_context(state: ConversationState) -> ConversationState:
    """
    Build context by loading user history and thread context.

    Also:
    - Annotates thread messages with `is_bot` so the reasoner knows which messages
      are already answered by the OLake agent.
    - Sets `org_member_replied = True` if an org team member posted in the thread,
      prompting the agent to stay silent.

    Args:
        state: Current conversation state

    Returns:
        Updated state with context loaded
    """
    logger = get_logger()
    db = get_database()
    slack_client = create_slack_client()

    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts")
    bot_user_id = get_bot_user_id()

    try:
        # ----------------------------------------------------------------
        # User profile
        # ----------------------------------------------------------------
        user_profile = db.get_user_profile(user_id)

        if not user_profile:
            user_info = slack_client.get_user_info(user_id)
            profile_data = user_info.get("profile", {})
            db.update_user_profile(
                user_id=user_id,
                username=user_info.get("name", ""),
                real_name=profile_data.get("real_name", ""),
                email=profile_data.get("email"),
            )
            user_profile = db.get_user_profile(user_id)

        state["user_profile"] = user_profile

        # ----------------------------------------------------------------
        # Previous messages (cross-thread history for this user)
        # ----------------------------------------------------------------
        previous_messages = db.get_user_recent_messages(
            user_id=user_id,
            limit=Config.MAX_CONTEXT_MESSAGES,
        )
        state["previous_messages"] = previous_messages

        # ----------------------------------------------------------------
        # Thread context
        # ----------------------------------------------------------------
        thread_context: List[Dict[str, Any]] = []
        org_member_replied = False

        if thread_ts:
            # Fetch from DB first
            thread_context = db.get_thread_messages(thread_ts)

            # Fetch from Slack API for latest messages not yet in DB
            slack_thread = slack_client.get_thread_messages(
                channel=channel_id,
                thread_ts=thread_ts,
                limit=20,  # raised from 10 to get richer thread context
            )

            existing_ts = {msg["message_ts"] for msg in thread_context}
            for slack_msg in slack_thread:
                if slack_msg["ts"] not in existing_ts:
                    thread_context.append(
                        {
                            "message_ts": slack_msg["ts"],
                            "user_id": slack_msg.get("user", ""),
                            "message_text": slack_msg.get("text", ""),
                            "created_at": slack_msg["ts"],
                        }
                    )

            # Annotate each thread message
            for msg in thread_context:
                sender_id = msg.get("user_id", "")
                sender_name = msg.get("display_name", "") or msg.get("username", "")

                # Mark bot messages
                is_bot = (bot_user_id and sender_id == bot_user_id)
                msg["is_bot"] = bool(is_bot)

                # Check if an org member posted (skip the bot itself)
                if not is_bot:
                    if is_org_member_by_id(sender_id) or (
                        sender_name and is_org_member_by_name(sender_name)
                    ):
                        org_member_replied = True
                        logger.logger.info(
                            f"Org member detected in thread {thread_ts}: "
                            f"user_id={sender_id}, name={sender_name}"
                        )

        state["thread_context"] = thread_context
        state["org_member_replied"] = org_member_replied

        # ----------------------------------------------------------------
        # Logging
        # ----------------------------------------------------------------
        logger.log_event(
            event_type=EventType.CONTEXT_LOADED,
            message=(
                f"Loaded context: {len(previous_messages)} previous messages, "
                f"{len(thread_context)} thread messages, "
                f"org_member_replied={org_member_replied}"
            ),
            user_id=user_id,
            channel_id=channel_id,
            metadata={
                "user_profile": {
                    "knowledge_level": user_profile.knowledge_level if user_profile else "beginner",
                    "total_messages": user_profile.total_messages if user_profile else 0,
                },
                "previous_messages_count": len(previous_messages),
                "thread_context_count": len(thread_context),
                "org_member_replied": org_member_replied,
            },
        )

    except Exception as e:
        logger.log_error(
            error_type="ContextLoadingError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        # Safe fallback
        state["user_profile"] = None
        state["previous_messages"] = []
        state["thread_context"] = []
        state["org_member_replied"] = False

    return state
