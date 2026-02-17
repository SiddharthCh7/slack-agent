"""Log and Cooldown node for the OLake LinkedIn Marketing Agent.

This node handles logging comment results and managing cooldowns
between comments.
"""

from datetime import datetime
from loguru import logger

from agent.state import AgentState
from agent.persistence import db


def log_and_cooldown(state: AgentState) -> AgentState:
    """Log the comment result and update cooldown tracking.
    
    This node:
    1. Records the comment attempt in the database
    2. Updates cooldown tracking if successful
    3. Advances to the next post if available
    
    Args:
        state: Current agent state with comment_result
        
    Returns:
        Updated state with next_allowed_at and iteration controls
    """
    logger.info("📋 Logging result and managing cooldown...")
    
    comment_result = state.get("comment_result")
    draft = state.get("drafted_comment")
    scored_post = state.get("current_scored_post")
    
    if not comment_result:
        logger.warning("No comment result to log")
        return state
    
    # Get topic and relevance for logging
    topic = draft.topic if draft else "unknown"
    relevance_score = scored_post.relevance_score if scored_post else 0.0
    comment_text = draft.comment_text if draft else ""
    
    # Record in database
    try:
        db.record_comment(
            post_urn=comment_result.post_urn,
            comment_text=comment_text,
            topic=topic,
            relevance_score=relevance_score,
            success=comment_result.success,
            linkedin_comment_id=getattr(comment_result, 'tweet_id', None) or getattr(comment_result, 'comment_id', None),
            error_message=comment_result.error,
        )
    except Exception as e:
        logger.error(f"Failed to record comment in database: {e}")
    
    # Update cooldown if successful
    if comment_result.success:
        state["comments_posted"] = state.get("comments_posted", 0) + 1
        next_allowed = db.update_cooldown()
        state["next_allowed_at"] = next_allowed
        logger.info(f"⏰ Next comment allowed at: {next_allowed.strftime('%H:%M:%S')}")
    
    # Log stats
    logger.info(
        f"Comment {'✅ succeeded' if comment_result.success else '❌ failed'} | "
        f"Post: {comment_result.post_urn} | Topic: {topic} | "
        f"Score: {relevance_score:.2f}"
    )
    
    # Advance to next post
    current_index = state.get("current_post_index", 0)
    scored_posts = state.get("scored_posts", [])
    
    next_index = current_index + 1
    
    if next_index < len(scored_posts):
        state["current_post_index"] = next_index
        state["current_scored_post"] = scored_posts[next_index]
        state["has_more_posts"] = True
        logger.info(f"📍 Moving to next post ({next_index + 1}/{len(scored_posts)})")
    else:
        state["has_more_posts"] = False
        state["current_scored_post"] = None
        logger.info("✅ All posts processed for this run")
    
    # Check if we should continue
    can_continue, reason = db.can_comment_now()
    if not can_continue:
        logger.info(f"⏸️ Stopping: {reason}")
        state["should_continue"] = False
    else:
        state["should_continue"] = state.get("has_more_posts", False)
    
    return state
