"""Comment Drafter node for the OLake LinkedIn Marketing Agent.

This node generates authentic, engaging comments for qualified posts
using the LLM with topic-specific tone templates.
"""

from loguru import logger

from agent.state import AgentState, DraftedComment
from agent.llm import generate_comment
from agent.tone_templates import get_tone_template
from agent.config import Config


def comment_drafter(state: AgentState) -> AgentState:
    """Draft a comment for the current post.
    
    This node:
    1. Gets the appropriate tone template for the post's topic
    2. Generates a comment using the LLM
    3. Validates the comment meets our guidelines
    
    Args:
        state: Current agent state with current_scored_post
        
    Returns:
        Updated state with drafted_comment populated
    """
    logger.info("✍️ Drafting comment...")
    
    scored_post = state.get("current_scored_post")
    
    if not scored_post:
        logger.warning("No post to draft comment for")
        state["drafted_comment"] = None
        return state
    
    post = scored_post.post
    topic = scored_post.primary_topic
    
    # Get the tone template for this topic
    tone_template = get_tone_template(topic)
    
    logger.info(f"Drafting comment for post by {post.author_name} (topic: {topic})")
    logger.debug(f"Post text preview: {post.text[:100]}...")
    
    # Dry run mode - skip LLM call if configured
    if Config.DRY_RUN:
        draft = DraftedComment(
            post_urn=post.urn,
            comment_text="[DRY RUN - Comment would be generated here]",
            topic=topic,
            confidence=0.0,
        )
        state["drafted_comment"] = draft
        logger.info("🏃 Dry run mode - skipping actual comment generation")
        print("🏃 Dry run mode - skipping actual comment generation")
        return state
    
    try:
        # Generate the comment
        comment_text = generate_comment(
            post_text=post.text,
            topic=topic,
            tone_template=tone_template,
        )
        
        if not comment_text:
            logger.warning(f"Failed to generate comment for post {post.urn}")
            state["drafted_comment"] = None
            state["errors"].append(f"Comment generation failed for {post.urn}")
            return state
        
        # Calculate confidence based on relevance and comment quality
        confidence = scored_post.relevance_score
        
        draft = DraftedComment(
            post_urn=post.urn,
            comment_text=comment_text,
            topic=topic,
            confidence=confidence,
        )
        
        logger.info(f"📝 Drafted comment ({len(comment_text.split())} words):")
        logger.info(f"   \"{comment_text}\"")
        print(f"   \"{comment_text}\"")
        
        state["drafted_comment"] = draft
        
    except Exception as e:
        logger.error(f"Error drafting comment: {e}")
        state["drafted_comment"] = None
        state["errors"].append(f"Comment draft error for {post.urn}: {e}")
    
    return state
