"""
Context Builder Node — Loads thread context and summary from DB.

Behavior:
  1. Resolve thread_id (thread_ts if present, else message_ts).
  2. Upsert user and thread records in DB.
  3. Load last 10 messages for the thread → state["thread_context"]
     Each item: {role, content, message_ts}
  4. Load thread summary → state["thread_summary"] (None on first message)
  5. Log result and handle errors with safe fallback.
"""

from typing import Dict, Any, List

from agent.state import ConversationState
from agent.filesystem.persistence import get_database
from agent.utils.logger import get_logger


def build_context(state: ConversationState) -> ConversationState:
    """
    Load thread context and summary from DB into state.

    Sets:
      state["thread_context"]  — last 10 messages [{role, content, message_ts}, ...]
      state["thread_summary"]  — latest consolidated summary string, or None
      state["org_member_replied"] — always False (detection removed)
    """
    logger = get_logger()
    db = get_database()

    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts")
    message_ts = state.get("message_ts") or ""

    # thread_id: use Slack thread_ts if this is a threaded message,
    # otherwise use message_ts as the canonical thread identifier.
    thread_id = thread_ts if thread_ts else message_ts

    try:
        # ----------------------------------------------------------------
        # Upsert user + thread (lightweight; no Slack API calls)
        # ----------------------------------------------------------------
        if user_id:
            db.upsert_user(user_id=user_id)

        if thread_id:
            db.upsert_thread(thread_id=thread_id, channel_id=channel_id)

        # ----------------------------------------------------------------
        # Thread context: last 10 messages, chronological
        # ----------------------------------------------------------------
        thread_context: List[Dict[str, Any]] = []
        if thread_id:
            thread_context = db.get_thread_messages(thread_id, limit=10)

        # ----------------------------------------------------------------
        # Thread summary
        # ----------------------------------------------------------------
        thread_summary = None
        if thread_id:
            thread_summary, _ = db.get_thread_summary(thread_id)

        state["thread_context"] = thread_context
        state["thread_summary"] = thread_summary
        state["org_member_replied"] = False

        print(
            f"[ContextBuilder] ✓ thread_id={thread_id}  messages={len(thread_context)}  "
            f"summary={'yes' if thread_summary else 'no'}"
        )

    except Exception as e:
        logger.log_error(
            error_type="ContextLoadingError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        state["thread_context"] = []
        state["thread_summary"] = None
        state["org_member_replied"] = False

    return state
