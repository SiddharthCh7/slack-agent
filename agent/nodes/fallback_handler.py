"""Fallback Handler node for the OLake LinkedIn Marketing Agent.

This node handles failures gracefully, logging errors and queuing
posts for retry without crashing the workflow.
"""

from loguru import logger

from agent.state import AgentState
from agent.persistence import db


def fallback_handler(state: AgentState) -> AgentState:
    """Handle failures from post_comment or comment_drafter.
    
    This node:
    1. Logs the failure with full context
    2. Queues the post for future retry if appropriate
    3. Allows the workflow to continue with remaining posts
    
    Args:
        state: Current agent state with error information
        
    Returns:
        Updated state ready to continue or end gracefully
    """
    logger.info("🔧 Fallback handler processing failure...")
    
    comment_result = state.get("comment_result")
    draft = state.get("drafted_comment")
    scored_post = state.get("current_scored_post")
    
    # Determine what failed
    if comment_result and not comment_result.success:
        error = comment_result.error or "Unknown posting error"
        post_urn = comment_result.post_urn
        logger.error(f"Comment posting failed for {post_urn}: {error}")
        
        # Add to failed posts list
        if post_urn:
            state["failed_posts"].append(post_urn)
            
            # Queue for retry if we have the post data
            if scored_post:
                try:
                    db.add_to_retry_queue(
                        post_urn=post_urn,
                        post_data=scored_post.to_dict(),
                        error_message=error,
                    )
                    logger.info(f"Queued {post_urn} for future retry")
                except Exception as e:
                    logger.warning(f"Failed to queue post for retry: {e}")
    
    elif not draft:
        # Comment generation failed
        if scored_post:
            post_urn = scored_post.post.urn
            error = f"Comment generation failed for post {post_urn}"
            logger.error(error)
            state["failed_posts"].append(post_urn)
            state["errors"].append(error)
    
    else:
        # Unknown failure
        logger.error("Unknown failure in workflow")
        state["errors"].append("Unknown workflow failure in fallback handler")
    
    # Log summary
    total_errors = len(state.get("errors", []))
    total_failed = len(state.get("failed_posts", []))
    logger.info(f"📊 Error summary: {total_errors} errors, {total_failed} failed posts")
    
    # Continue to log_and_cooldown for tracking
    # The workflow will handle moving to the next iteration
    
    return state
