"""Engagement router node for the OLake X Marketing Agent.

This node decides what type of engagement action to take based on post relevance.
"""

from loguru import logger

from agent.state import AgentState
from agent.config import Config


def engagement_router(state: AgentState) -> AgentState:
    """Route posts to different engagement actions based on relevance score.
    
    Routing logic:
    - 0.9+ with @mention → Priority reply
    - 0.85+ → Quote tweet with commentary  
    - 0.7+ → Standard reply
    - 0.5+ → Like + maybe retweet
    - Below 0.5 → Skip
    
    Args:
        state: Current agent state with current_scored_post
        
    Returns:
        Updated state with engagement_action set
    """
    logger.info("🔀 Routing engagement action...")
    print("🔀 Routing engagement action...")
    
    scored_post = state.get("current_scored_post")
    
    if not scored_post:
        logger.warning("No post to route")
        state["engagement_action"] = "skip"
        return state
    
    score = scored_post.relevance_score
    post = scored_post.post
    is_mention = getattr(post, "is_mention", False)
    
    # Check daily limits
    likes_today = state.get("likes_today", 0)
    retweets_today = state.get("retweets_today", 0)
    follows_today = state.get("follows_today", 0)
    
    # Priority: Mentions always get replies
    if is_mention and score >= 0.5:
        logger.info(f"📣 Mention detected (score: {score:.2f}) → reply")
        print(f"📣 Mention detected (score: {score:.2f}) → reply")
        state["engagement_action"] = "reply"
        return state
    
    # Very high relevance: Quote tweet
    if score >= Config.QUOTE_THRESHOLD:
        logger.info(f"⭐ High relevance (score: {score:.2f}) → quote_tweet")
        print(f"⭐ High relevance (score: {score:.2f}) → quote_tweet")
        state["engagement_action"] = "quote_tweet"
        return state
    
    # High relevance: Reply
    if score >= Config.RELEVANCE_THRESHOLD:
        logger.info(f"💬 Relevant (score: {score:.2f}) → reply")
        print(f"💬 Relevant (score: {score:.2f}) → reply")
        state["engagement_action"] = "reply"
        return state
    
    # Medium relevance: Like and maybe retweet
    if score >= Config.LIKE_THRESHOLD:
        # Check if we should retweet too
        if score >= Config.RETWEET_THRESHOLD and Config.ENABLE_RETWEETS:
            if retweets_today < Config.MAX_RETWEETS_PER_DAY:
                logger.info(f"🔄 Medium-high relevance (score: {score:.2f}) → like_and_retweet")
                print(f"🔄 Medium-high relevance (score: {score:.2f}) → like_and_retweet")
                state["engagement_action"] = "like_and_retweet"
                return state
        
        # Just like
        if Config.ENABLE_LIKES and likes_today < Config.MAX_LIKES_PER_DAY:
            logger.info(f"❤️ Medium relevance (score: {score:.2f}) → like")
            print(f"❤️ Medium relevance (score: {score:.2f}) → like")
            state["engagement_action"] = "like"
            return state
    
    # Low relevance: Skip
    logger.info(f"⏭️ Low relevance (score: {score:.2f}) → skip")
    print(f"⏭️ Low relevance (score: {score:.2f}) → skip")
    state["engagement_action"] = "skip"
    return state


def route_by_action(state: AgentState) -> str:
    """Conditional routing function for the graph.
    
    Returns the next node based on engagement_action.
    """
    action = state.get("engagement_action", "skip")
    
    if action == "reply":
        return "comment_drafter"
    elif action == "quote_tweet":
        return "quote_drafter"
    elif action == "like":
        return "like_tweet"
    elif action == "like_and_retweet":
        return "like_and_retweet"
    elif action == "follow":
        return "follow_handler"
    else:
        return "log_and_cooldown"
