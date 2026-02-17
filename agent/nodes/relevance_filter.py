"""Relevance Filter node for the OLake LinkedIn Marketing Agent.

This node evaluates each post using the LLM to determine its relevance
to OLake and data engineering topics.
"""

from loguru import logger

from agent.state import AgentState, ScoredPost
from agent.config import Config
from agent.llm import classify_post_relevance


def relevance_filter(state: AgentState) -> AgentState:
    """Filter and score posts by relevance to OLake.
    
    This node:
    1. Sends each post to the LLM for classification
    2. Filters out posts below the relevance threshold
    3. Sorts remaining posts by relevance score (descending)
    
    Args:
        state: Current agent state with raw_posts
        
    Returns:
        Updated state with scored_posts populated
    """
    logger.info("📊 Filtering posts by relevance...")
    print("📊 Filtering posts by relevance...")
    
    raw_posts = state.get("raw_posts", [])
    
    if not raw_posts:
        logger.info("No posts to filter")
        print("No posts to filter")
        state["scored_posts"] = []
        state["has_more_posts"] = False
        return state
    
    scored_posts = []
    
    for post in raw_posts:
        logger.debug(f"Classifying post {post.urn}...")
        print(f"Classifying post {post.urn}...")
        
        try:
            # Get LLM classification
            classification = classify_post_relevance(post.text)
            
            relevance_score = classification.get("relevance_score", 0.0)
            primary_topic = classification.get("primary_topic", "off_topic")
            reason = classification.get("reason", "")
            
            logger.debug(
                f"Post {post.urn}: score={relevance_score:.2f}, "
                f"topic={primary_topic}, reason={reason}"
            )
            
            # Only keep posts above threshold
            if relevance_score >= Config.RELEVANCE_THRESHOLD:
                scored_post = ScoredPost(
                    post=post,
                    relevance_score=relevance_score,
                    primary_topic=primary_topic,
                    reason=reason,
                )
                scored_posts.append(scored_post)
                logger.info(
                    f"✅ Post qualifies: {post.urn} "
                    f"(score={relevance_score:.2f}, topic={primary_topic})"
                )
            else:
                logger.debug(
                    f"❌ Post below threshold: {post.urn} "
                    f"(score={relevance_score:.2f} < {Config.RELEVANCE_THRESHOLD})"
                )
                
        except Exception as e:
            logger.error(f"Failed to classify post {post.urn}: {e}")
            state["errors"].append(f"Classification error for {post.urn}: {e}")
            continue
    
    # Sort by relevance score (highest first)
    scored_posts.sort(key=lambda x: x.relevance_score, reverse=True)
    
    logger.info(f"Filtered to {len(scored_posts)} relevant posts")
    
    state["scored_posts"] = scored_posts
    state["current_post_index"] = 0
    state["has_more_posts"] = len(scored_posts) > 0
    
    # Set up first post for processing
    if scored_posts:
        state["current_scored_post"] = scored_posts[0]
    
    return state
