"""Post Reply node for the OLake X Marketing Agent.

This node posts the drafted reply to X (Twitter), handling rate limits
and authentication as needed.
"""

from loguru import logger

from agent.state import AgentState, CommentResult
from agent.config import Config
from agent.x_client import x_client
from agent.persistence import db


def post_comment(state: AgentState) -> AgentState:
    """Post the drafted reply to X (Twitter).
    
    This node:
    1. Checks if we can reply (rate limits, cooldowns)
    2. Posts the reply to X
    3. Handles errors with retry logic
    
    Args:
        state: Current agent state with drafted_comment
        
    Returns:
        Updated state with comment_result populated
    """
    logger.info("📤 Posting reply to X...")
    
    draft = state.get("drafted_comment")
    
    if not draft:
        logger.warning("No comment to post")
        state["comment_result"] = CommentResult(
            success=False,
            post_urn="",
            error="No draft comment available",
        )
        return state
    
    # Check rate limits and cooldowns
    can_comment, reason = db.can_comment_now()
    if not can_comment:
        logger.warning(f"Cannot post comment: {reason}")
        state["comment_result"] = CommentResult(
            success=False,
            post_urn=draft.post_urn,
            error=reason,
        )
        return state
    
    # Dry run mode - don't actually post
    if Config.DRY_RUN:
        logger.info("🏃 Dry run mode - not posting to X")
        print("🏃 Dry run mode - not posting to X")
        
        logger.info(f"   Would reply to tweet: {draft.post_urn}")
        logger.info(f"   Reply: {draft.comment_text}")
        
        state["comment_result"] = CommentResult(
            success=True,
            post_urn=draft.post_urn,
            linkedin_comment_id="dry-run-comment-id",
        )
        return state
    
    try:
        # Post the reply
        result = x_client.post_reply(
            tweet_id=draft.post_urn,
            reply_text=draft.comment_text,
        )
        
        if result.get("success"):
            comment_id = result.get("tweet_id", "")
            logger.info(f"✅ Comment posted successfully! ID: {comment_id}")
            
            state["comment_result"] = CommentResult(
                success=True,
                post_urn=draft.post_urn,
                linkedin_comment_id=comment_id,
            )
        else:
            error = result.get("error", "Unknown error")
            logger.error(f"❌ Failed to post comment: {error}")
            
            state["comment_result"] = CommentResult(
                success=False,
                post_urn=draft.post_urn,
                error=error,
            )
            
    except Exception as e:
        logger.error(f"Exception posting comment: {e}")
        state["comment_result"] = CommentResult(
            success=False,
            post_urn=draft.post_urn,
            error=str(e),
        )
    
    return state
