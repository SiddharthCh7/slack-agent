"""Feed Scanner node for the OLake X Marketing Agent.

This node is responsible for fetching relevant posts from X (Twitter)
using multiple discovery sources.
"""

from datetime import datetime, timedelta
from loguru import logger

from agent.state import AgentState, Post
from agent.config import Config
from agent.x_client import x_client
from agent.persistence import db
from agent.llm import filter_relevant_trends


def feed_scanner(state: AgentState) -> AgentState:
    """Scan X feed for relevant posts using multiple discovery sources.
    
    Discovery sources:
    1. Keyword/hashtag search (primary)
    2. Trending topics (filtered for relevance)
    3. @mentions of our account
    4. Target influencer timelines
    5. Home timeline (personalized)
    
    Args:
        state: Current agent state
        
    Returns:
        Updated state with raw_posts populated
    """
    logger.info("🔍 Starting feed scan...")
    print("🔍 Starting feed scan...")
    
    all_posts: list[Post] = []
    seen_ids: set[str] = set()
    
    def dedupe_add(posts: list[Post], source: str):
        """Add posts avoiding duplicates."""
        count = 0
        for post in posts:
            if post.urn not in seen_ids:
                seen_ids.add(post.urn)
                all_posts.append(post)
                count += 1
        if count > 0:
            logger.info(f"   [{source}] Added {count} tweets")
            print(f"   [{source}] Added {count} tweets")
    
    # 1. Primary: Keyword/hashtag search
    try:
        search_posts = x_client.search_tweets(max_tweets=Config.MAX_POSTS_PER_RUN)
        dedupe_add(search_posts, "Search")
    except Exception as e:
        logger.error(f"Search failed: {e}")
        state["errors"].append(f"Search error: {e}")
    
    # 2. Trending topics (if enabled)
    if Config.ENABLE_TRENDS:
        try:
            trends = x_client.get_trends()
            relevant_trends = filter_relevant_trends(trends)
            
            if relevant_trends:
                logger.info(f"   Found {len(relevant_trends)} relevant trends: {relevant_trends}")
                # Note: In dry-run, trends are mocked; in live mode, we'd search for each trend
                # For now we just log them - trend-based search would be similar to keyword search
        except Exception as e:
            logger.error(f"Trends fetch failed: {e}")
    
    # 3. Mentions (if enabled) - prioritize these
    if Config.ENABLE_MENTIONS:
        try:
            mentions = x_client.get_mentions(max_tweets=10)
            dedupe_add(mentions, "Mentions")
        except Exception as e:
            logger.error(f"Mentions fetch failed: {e}")
            state["errors"].append(f"Mentions error: {e}")
    
    # 4. Target influencer timelines (if configured)
    if Config.TARGET_INFLUENCERS:
        for influencer_id in Config.TARGET_INFLUENCERS[:5]:  # Limit to 5
            try:
                influencer_posts = x_client.get_user_timeline(
                    user_id=influencer_id,
                    max_tweets=5
                )
                dedupe_add(influencer_posts, f"@{influencer_id}")
            except Exception as e:
                logger.debug(f"Failed to fetch timeline for {influencer_id}: {e}")
    
    # 5. Home timeline (if enabled) - personalized content
    if Config.USE_HOME_TIMELINE:
        try:
            home_posts = x_client.get_home_timeline(max_tweets=10)
            dedupe_add(home_posts, "Home")
        except Exception as e:
            logger.error(f"Home timeline failed: {e}")
    
    logger.info(f"📥 Total: {len(all_posts)} tweets from all sources")
    print(f"📥 Total: {len(all_posts)} tweets from all sources")
    
    # Filter by age
    cutoff = datetime.now() - timedelta(hours=Config.POST_AGE_CUTOFF_HOURS)
    filtered_posts = []
    
    for post in all_posts:
        # Skip old posts
        if post.timestamp < cutoff:
            logger.debug(f"Skipping old post {post.urn} (from {post.timestamp})")
            continue
        
        # Skip posts we've already interacted with
        if db.has_commented_on_post(post.urn):
            logger.debug(f"Skipping already-engaged post {post.urn}")
            continue
        
        filtered_posts.append(post)
    
    logger.info(f"After filtering: {len(filtered_posts)} posts to evaluate")
    print(f"After filtering: {len(filtered_posts)} posts to evaluate")
    
    # Sort: prioritize mentions first, then by timestamp (newest first)
    filtered_posts.sort(key=lambda p: (not p.is_mention, p.timestamp), reverse=True)
    
    # Limit to max posts per run
    if len(filtered_posts) > Config.MAX_POSTS_PER_RUN:
        filtered_posts = filtered_posts[:Config.MAX_POSTS_PER_RUN]
        logger.info(f"Limited to {Config.MAX_POSTS_PER_RUN} posts for this run")
    
    state["raw_posts"] = filtered_posts
    state["has_more_posts"] = len(filtered_posts) > 0
    
    return state

