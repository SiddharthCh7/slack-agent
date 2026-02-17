"""Quote tweet drafter and poster for the OLake X Marketing Agent.

This node generates a quote tweet with commentary for high-relevance posts.
"""

from loguru import logger

from agent.state import AgentState, DraftedComment, CommentResult
from agent.config import Config
from agent.llm import generate_quote_comment
from agent.tone_templates import get_tone_template
from agent.x_client import x_client


def quote_drafter(state: AgentState) -> AgentState:
    """Draft a quote tweet for a high-relevance post.
    
    Quote tweets add value by providing commentary on exceptional content.
    
    Args:
        state: Current agent state with current_scored_post
        
    Returns:
        Updated state with drafted_comment (quote text)
    """
    logger.info("💬 Drafting quote tweet...")
    print("💬 Drafting quote tweet...")
    
    scored_post = state.get("current_scored_post")
    
    if not scored_post:
        logger.warning("No post to quote")
        state["drafted_comment"] = None
        return state
    
    post = scored_post.post
    topic = scored_post.primary_topic
    
    # In dry run mode with test API key, create a placeholder
    if Config.DRY_RUN:
        draft = DraftedComment(
            post_urn=post.urn,
            comment_text=f"[MOCK QUOTE] Great insights on {topic}! 🚀",
            topic=topic,
            confidence=scored_post.relevance_score,
        )
        state["drafted_comment"] = draft
        logger.info("🏃 Dry run mode - using mock quote")
        print("🏃 Dry run mode - using mock quote")
        return state
    
    try:
        # Get tone template for this topic
        tone = get_tone_template(topic)
        
        # Generate quote tweet text
        quote_text = generate_quote_comment(
            post_text=post.text,
            topic=topic,
            tone_template=tone,
        )
        
        if not quote_text:
            logger.warning("Failed to generate quote text")
            state["drafted_comment"] = None
            return state
        
        # Create draft
        draft = DraftedComment(
            post_urn=post.urn,
            comment_text=quote_text,
            topic=topic,
            confidence=scored_post.relevance_score,
        )
        
        logger.info(f"📝 Quote draft ({len(quote_text)} chars):")
        logger.info(f"   \"{quote_text}\"")
        print(f"   Quote: \"{quote_text}\"")
        
        state["drafted_comment"] = draft
        
    except Exception as e:
        logger.error(f"Error drafting quote: {e}")
        state["drafted_comment"] = None
        state["errors"].append(f"Quote draft error: {e}")
    
    return state


def post_quote(state: AgentState) -> AgentState:
    """Post the drafted quote tweet.
    
    Args:
        state: Current agent state with drafted_comment
        
    Returns:
        Updated state with comment_result
    """
    logger.info("📤 Posting quote tweet...")
    print("📤 Posting quote tweet...")
    
    draft = state.get("drafted_comment")
    
    if not draft:
        logger.warning("No quote to post")
        state["comment_result"] = CommentResult(
            success=False,
            post_urn="",
            error="No quote draft available"
        )
        return state
    
    # Post the quote tweet
    result = x_client.quote_tweet(
        tweet_id=draft.post_urn,
        quote_text=draft.comment_text,
    )
    
    if result.get("success"):
        new_tweet_id = result.get("tweet_id", "")
        logger.info(f"✅ Quote tweet posted! ID: {new_tweet_id}")
        print(f"✅ Quote tweet posted! ID: {new_tweet_id}")
        
        state["comment_result"] = CommentResult(
            success=True,
            post_urn=draft.post_urn,
            tweet_id=new_tweet_id,
        )
        state["comments_posted"] = state.get("comments_posted", 0) + 1
    else:
        error = result.get("error", "Unknown error")
        logger.error(f"Failed to post quote: {error}")
        
        state["comment_result"] = CommentResult(
            success=False,
            post_urn=draft.post_urn,
            error=error,
        )
        state["errors"].append(f"Quote post error: {error}")
    
    return state
