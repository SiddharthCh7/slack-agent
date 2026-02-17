"""Like tweet node for the OLake X Marketing Agent.

This node likes tweets that pass the relevance filter.
"""

from loguru import logger

from agent.state import AgentState, EngagementResult
from agent.config import Config
from agent.x_client import x_client


def like_tweet(state: AgentState) -> AgentState:
    """Like a tweet.
    
    Args:
        state: Current agent state with current_scored_post
        
    Returns:
        Updated state with engagement result
    """
    logger.info("❤️ Liking tweet...")
    print("❤️ Liking tweet...")
    
    scored_post = state.get("current_scored_post")
    
    if not scored_post:
        logger.warning("No post to like")
        return state
    
    tweet_id = scored_post.post.urn
    
    # Check daily limit
    likes_today = state.get("likes_today", 0)
    if likes_today >= Config.MAX_LIKES_PER_DAY:
        logger.warning(f"Daily like limit reached ({Config.MAX_LIKES_PER_DAY})")
        result = EngagementResult(
            action="like",
            tweet_id=tweet_id,
            success=False,
            error="Daily limit reached"
        )
        state["engagement_results"].append(result)
        return state
    
    # Like the tweet
    result = x_client.like_tweet(tweet_id)
    
    if result.get("success"):
        logger.info(f"✅ Liked tweet {tweet_id}")
        print(f"✅ Liked tweet {tweet_id}")
        state["likes_today"] = likes_today + 1
        
        engagement_result = EngagementResult(
            action="like",
            tweet_id=tweet_id,
            success=True
        )
    else:
        logger.error(f"Failed to like tweet: {result.get('error')}")
        engagement_result = EngagementResult(
            action="like",
            tweet_id=tweet_id,
            success=False,
            error=result.get("error")
        )
    
    state["engagement_results"].append(engagement_result)
    return state


def like_and_retweet(state: AgentState) -> AgentState:
    """Like and retweet a tweet.
    
    Args:
        state: Current agent state with current_scored_post
        
    Returns:
        Updated state with engagement results
    """
    logger.info("❤️🔄 Liking and retweeting...")
    print("❤️🔄 Liking and retweeting...")
    
    scored_post = state.get("current_scored_post")
    
    if not scored_post:
        logger.warning("No post to engage with")
        return state
    
    tweet_id = scored_post.post.urn
    likes_today = state.get("likes_today", 0)
    retweets_today = state.get("retweets_today", 0)
    
    # Like first
    if likes_today < Config.MAX_LIKES_PER_DAY:
        like_result = x_client.like_tweet(tweet_id)
        if like_result.get("success"):
            state["likes_today"] = likes_today + 1
            logger.info(f"✅ Liked tweet {tweet_id}")
            print(f"✅ Liked tweet {tweet_id}")
            state["engagement_results"].append(EngagementResult(
                action="like",
                tweet_id=tweet_id,
                success=True
            ))
    
    # Then retweet
    if retweets_today < Config.MAX_RETWEETS_PER_DAY:
        retweet_result = x_client.retweet(tweet_id)
        if retweet_result.get("success"):
            state["retweets_today"] = retweets_today + 1
            logger.info(f"✅ Retweeted {tweet_id}")
            print(f"✅ Retweeted {tweet_id}")
            state["engagement_results"].append(EngagementResult(
                action="retweet",
                tweet_id=tweet_id,
                success=True
            ))
        else:
            state["engagement_results"].append(EngagementResult(
                action="retweet",
                tweet_id=tweet_id,
                success=False,
                error=retweet_result.get("error")
            ))
    
    return state
