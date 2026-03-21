"""
Context builder for CLI mode.

Lightweight: no database, no Slack API. Sets empty thread context and no summary.
"""

from agent.state import ConversationState
from agent.logger import get_logger


def build_cli_context(state: ConversationState) -> ConversationState:
    """
    Build minimal context for CLI mode.

    Sets thread_context=[], thread_summary=None, org_member_replied=False.
    """
    logger = get_logger()
    logger.logger.debug(f"[CLI Context] Built minimal context for user {state['user_id']}")

    state["thread_context"] = []
    state["thread_summary"] = None
    state["org_member_replied"] = False

    return state
