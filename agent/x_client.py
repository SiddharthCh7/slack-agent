"""X (Twitter) API client for the OLake Marketing Agent.

Handles authentication, rate limiting, and API calls to X/Twitter.
Uses the official X API v2.
"""

import time
import requests
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from agent.config import Config
from agent.state import Post
from agent.keywords import get_search_keywords, get_all_hashtags


class XClient:
    """Client for interacting with X (Twitter) API v2.
    
    Uses Bearer Token authentication for search and OAuth 1.0a for posting.
    """
    
    def __init__(self):
        self._last_request_time = None
        self._request_count = 0
        self._rate_limit_reset = None
        
    def _headers(self) -> dict:
        """Get authorization headers for X API."""
        return {
            "Authorization": f"Bearer {Config.X_BEARER_TOKEN}",
            "Content-Type": "application/json",
        }
    
    def _oauth_headers(self) -> dict:
        """Get OAuth 1.0a headers for posting (requires user context)."""
        # For posting, we need OAuth 1.0a with user context
        # This is a simplified version - production should use proper OAuth
        import hashlib
        import hmac
        import base64
        import urllib.parse
        
        return {
            "Authorization": f"Bearer {Config.X_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
    
    def _respect_rate_limit(self):
        """Enforce rate limiting for X API.
        
        X API v2 limits:
        - Search: 450 requests per 15-minute window (app auth)
        - Tweet lookup: 900 requests per 15-minute window
        - Post tweet: 200 tweets per 15 minutes (user auth)
        """
        now = datetime.now()
        
        # Reset counter every 15 minutes
        if self._rate_limit_reset is None or now > self._rate_limit_reset:
            self._request_count = 0
            self._rate_limit_reset = now + timedelta(minutes=15)
        
        # Check if we're at the limit (conservative: 400 per 15 min)
        if self._request_count >= 400:
            wait_seconds = (self._rate_limit_reset - now).total_seconds()
            if wait_seconds > 0:
                logger.warning(f"Rate limit reached, waiting {wait_seconds:.1f}s")
                time.sleep(wait_seconds)
                self._request_count = 0
                self._rate_limit_reset = datetime.now() + timedelta(minutes=15)
        
        self._request_count += 1
    
    def search_tweets(self, max_tweets: int = 10) -> list[Post]:
        """Search for tweets matching our target keywords and hashtags.
        
        Args:
            max_tweets: Maximum number of tweets to return
            
        Returns:
            List of Post objects matching our criteria
        """
        # Use mock API in dry-run mode
        if Config.DRY_RUN:
            logger.info("Using Mock X API (dry-run mode)")
            print("Using Mock X API (dry-run mode)")
            return MockXAPI().search_tweets(max_tweets)
        
        tweets = []
        seen_ids = set()
        
        keywords = get_search_keywords()
        hashtags = get_all_hashtags()
        
        # Build search query - keep it simple for Basic tier
        # Use only hashtags (simpler syntax, no quotes needed)
        primary_terms = hashtags[:2]  # Just 2 hashtags to keep query short
        if not primary_terms:
            primary_terms = [kw.replace(" ", "") for kw in keywords[:2]]  # Remove spaces from keywords
        
        query = " OR ".join(primary_terms)
        query += " -is:retweet lang:en"
        
        logger.info(f"Search query: {query}")
        
        self._respect_rate_limit()
        
        try:
            response = requests.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers=self._headers(),
                params={
                    "query": query,
                    "max_results": min(max_tweets * 2, 100),  # X API allows 10-100
                    "tweet.fields": "created_at,author_id,text,entities",
                    "user.fields": "name,username",
                    "expansions": "author_id",
                },
                timeout=30,
            )
            
            if response.status_code == 429:
                logger.warning("X API rate limit hit")
                return []
            elif response.status_code == 401:
                logger.error("X API authentication failed")
                return []
            
            response.raise_for_status()
            data = response.json()
            
            # Build user lookup dict
            users = {}
            if "includes" in data and "users" in data["includes"]:
                for user in data["includes"]["users"]:
                    users[user["id"]] = user
            
            # Parse tweets
            for tweet_data in data.get("data", []):
                tweet_id = tweet_data.get("id", "")
                if tweet_id and tweet_id not in seen_ids:
                    seen_ids.add(tweet_id)
                    
                    author_id = tweet_data.get("author_id", "")
                    author_info = users.get(author_id, {})
                    
                    # Extract hashtags from entities
                    hashtags_list = []
                    if "entities" in tweet_data and "hashtags" in tweet_data["entities"]:
                        hashtags_list = [f"#{h['tag']}" for h in tweet_data["entities"]["hashtags"]]
                    
                    # Parse timestamp
                    created_at = tweet_data.get("created_at", "")
                    try:
                        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    except:
                        timestamp = datetime.now()
                    
                    post = Post(
                        urn=tweet_id,
                        text=tweet_data.get("text", ""),
                        author=author_id,
                        author_name=author_info.get("name", author_info.get("username", "Unknown")),
                        timestamp=timestamp,
                        hashtags=hashtags_list,
                    )
                    tweets.append(post)
                    
                    if len(tweets) >= max_tweets:
                        break
                        
        except requests.exceptions.RequestException as e:
            logger.error(f"X API request failed: {e}")
            print(f"X API request failed: {e}")
        
        logger.info(f"Found {len(tweets)} tweets matching keywords/hashtags")
        print(f"Found {len(tweets)} tweets matching keywords/hashtags")
        return tweets
    
    def post_reply(self, tweet_id: str, reply_text: str) -> dict:
        """Post a reply to a tweet.
        
        Args:
            tweet_id: The ID of the tweet to reply to
            reply_text: The text of the reply
            
        Returns:
            dict with 'success', 'tweet_id', and optionally 'error'
        """
        # Dry run mode - don't actually post
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would reply to tweet {tweet_id}")
            logger.info(f"[DRY RUN] Reply: {reply_text}")
            print(f"[DRY RUN] Would reply to tweet {tweet_id}")
            print(f"[DRY RUN] Reply: {reply_text}")
            return {
                "success": True,
                "tweet_id": f"dry-run-{int(time.time())}",
            }
        
        max_retries = 3
        retry_delays = [2, 4, 8]  # Exponential backoff
        
        for attempt in range(max_retries):
            self._respect_rate_limit()
            
            try:
                response = requests.post(
                    "https://api.twitter.com/2/tweets",
                    headers=self._oauth_headers(),
                    json={
                        "text": reply_text,
                        "reply": {
                            "in_reply_to_tweet_id": tweet_id
                        }
                    },
                    timeout=30,
                )
                
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        delay = retry_delays[attempt]
                        logger.warning(f"Rate limited, retrying in {delay}s")
                        time.sleep(delay)
                        continue
                    return {"success": False, "error": "Rate limit exceeded"}
                
                if response.status_code == 401:
                    return {"success": False, "error": "Authentication failed"}
                
                response.raise_for_status()
                data = response.json()
                
                return {
                    "success": True,
                    "tweet_id": data.get("data", {}).get("id", ""),
                }
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to post reply: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delays[attempt])
                    continue
                return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Max retries exceeded"}
    
    def like_tweet(self, tweet_id: str) -> dict:
        """Like a tweet.
        
        Args:
            tweet_id: The ID of the tweet to like
            
        Returns:
            dict with 'success' and optionally 'error'
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would like tweet {tweet_id}")
            print(f"[DRY RUN] Would like tweet {tweet_id}")
            return {"success": True}
        
        self._respect_rate_limit()
        
        try:
            # Need the authenticated user's ID
            user_id = self._get_authenticated_user_id()
            if not user_id:
                return {"success": False, "error": "Could not get user ID"}
            
            response = requests.post(
                f"https://api.twitter.com/2/users/{user_id}/likes",
                headers=self._oauth_headers(),
                json={"tweet_id": tweet_id},
                timeout=30,
            )
            
            if response.status_code == 429:
                return {"success": False, "error": "Rate limit exceeded"}
            if response.status_code == 401:
                return {"success": False, "error": "Authentication failed"}
            
            response.raise_for_status()
            data = response.json()
            
            liked = data.get("data", {}).get("liked", False)
            logger.info(f"❤️ Liked tweet {tweet_id}: {liked}")
            return {"success": liked}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to like tweet: {e}")
            return {"success": False, "error": str(e)}
    
    def unlike_tweet(self, tweet_id: str) -> dict:
        """Unlike a tweet.
        
        Args:
            tweet_id: The ID of the tweet to unlike
            
        Returns:
            dict with 'success' and optionally 'error'
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would unlike tweet {tweet_id}")
            return {"success": True}
        
        self._respect_rate_limit()
        
        try:
            user_id = self._get_authenticated_user_id()
            if not user_id:
                return {"success": False, "error": "Could not get user ID"}
            
            response = requests.delete(
                f"https://api.twitter.com/2/users/{user_id}/likes/{tweet_id}",
                headers=self._oauth_headers(),
                timeout=30,
            )
            
            if response.status_code in (429, 401):
                return {"success": False, "error": "API error"}
            
            response.raise_for_status()
            return {"success": True}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to unlike tweet: {e}")
            return {"success": False, "error": str(e)}
    
    def retweet(self, tweet_id: str) -> dict:
        """Retweet a tweet.
        
        Args:
            tweet_id: The ID of the tweet to retweet
            
        Returns:
            dict with 'success' and optionally 'error'
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would retweet {tweet_id}")
            print(f"[DRY RUN] Would retweet {tweet_id}")
            return {"success": True}
        
        self._respect_rate_limit()
        
        try:
            user_id = self._get_authenticated_user_id()
            if not user_id:
                return {"success": False, "error": "Could not get user ID"}
            
            response = requests.post(
                f"https://api.twitter.com/2/users/{user_id}/retweets",
                headers=self._oauth_headers(),
                json={"tweet_id": tweet_id},
                timeout=30,
            )
            
            if response.status_code == 429:
                return {"success": False, "error": "Rate limit exceeded"}
            if response.status_code == 401:
                return {"success": False, "error": "Authentication failed"}
            
            response.raise_for_status()
            data = response.json()
            
            retweeted = data.get("data", {}).get("retweeted", False)
            logger.info(f"🔄 Retweeted {tweet_id}: {retweeted}")
            return {"success": retweeted}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to retweet: {e}")
            return {"success": False, "error": str(e)}
    
    def quote_tweet(self, tweet_id: str, quote_text: str) -> dict:
        """Post a quote tweet.
        
        Args:
            tweet_id: The ID of the tweet to quote
            quote_text: The commentary text for the quote
            
        Returns:
            dict with 'success', 'tweet_id', and optionally 'error'
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would quote tweet {tweet_id}")
            logger.info(f"[DRY RUN] Quote: {quote_text}")
            print(f"[DRY RUN] Would quote tweet {tweet_id}")
            print(f"[DRY RUN] Quote: {quote_text}")
            return {"success": True, "tweet_id": f"dry-run-quote-{int(time.time())}"}
        
        self._respect_rate_limit()
        
        try:
            response = requests.post(
                "https://api.twitter.com/2/tweets",
                headers=self._oauth_headers(),
                json={
                    "text": quote_text,
                    "quote_tweet_id": tweet_id
                },
                timeout=30,
            )
            
            if response.status_code == 429:
                return {"success": False, "error": "Rate limit exceeded"}
            if response.status_code == 401:
                return {"success": False, "error": "Authentication failed"}
            
            response.raise_for_status()
            data = response.json()
            
            new_tweet_id = data.get("data", {}).get("id", "")
            logger.info(f"💬 Quote tweet posted: {new_tweet_id}")
            return {"success": True, "tweet_id": new_tweet_id}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to quote tweet: {e}")
            return {"success": False, "error": str(e)}
    
    def follow_user(self, user_id: str) -> dict:
        """Follow a user.
        
        Args:
            user_id: The ID of the user to follow
            
        Returns:
            dict with 'success' and optionally 'error'
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would follow user {user_id}")
            print(f"[DRY RUN] Would follow user {user_id}")
            return {"success": True}
        
        self._respect_rate_limit()
        
        try:
            my_user_id = self._get_authenticated_user_id()
            if not my_user_id:
                return {"success": False, "error": "Could not get user ID"}
            
            response = requests.post(
                f"https://api.twitter.com/2/users/{my_user_id}/following",
                headers=self._oauth_headers(),
                json={"target_user_id": user_id},
                timeout=30,
            )
            
            if response.status_code == 429:
                return {"success": False, "error": "Rate limit exceeded"}
            if response.status_code == 401:
                return {"success": False, "error": "Authentication failed"}
            
            response.raise_for_status()
            data = response.json()
            
            following = data.get("data", {}).get("following", False)
            logger.info(f"👤 Followed user {user_id}: {following}")
            return {"success": following}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to follow user: {e}")
            return {"success": False, "error": str(e)}
    
    def get_trends(self, woeid: int = 1) -> list[str]:
        """Get trending topics.
        
        Args:
            woeid: Where On Earth ID (1 = Worldwide, 23424977 = USA)
            
        Returns:
            List of trending topic names
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would fetch trends for WOEID {woeid}")
            return MockXAPI().get_trends()
        
        self._respect_rate_limit()
        
        try:
            response = requests.get(
                f"https://api.twitter.com/2/trends/by/woeid/{woeid}",
                headers=self._headers(),
                timeout=30,
            )
            
            if response.status_code in (429, 401):
                return []
            
            response.raise_for_status()
            data = response.json()
            
            trends = [t.get("trend_name", "") for t in data.get("data", [])]
            logger.info(f"📈 Found {len(trends)} trending topics")
            return trends
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get trends: {e}")
            return []
    
    def get_user_timeline(self, user_id: str, max_tweets: int = 10) -> list[Post]:
        """Get tweets from a specific user's timeline.
        
        Args:
            user_id: The user ID to fetch tweets from
            max_tweets: Maximum number of tweets to return
            
        Returns:
            List of Post objects
        """
        if Config.DRY_RUN:
            logger.info(f"[DRY RUN] Would fetch timeline for user {user_id}")
            return []
        
        self._respect_rate_limit()
        
        try:
            response = requests.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers=self._headers(),
                params={
                    "max_results": min(max_tweets, 100),
                    "tweet.fields": "created_at,author_id,text,entities",
                    "exclude": "retweets,replies",
                },
                timeout=30,
            )
            
            if response.status_code in (429, 401):
                return []
            
            response.raise_for_status()
            data = response.json()
            
            tweets = []
            for tweet_data in data.get("data", []):
                created_at = tweet_data.get("created_at", "")
                try:
                    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except:
                    timestamp = datetime.now()
                
                hashtags_list = []
                if "entities" in tweet_data and "hashtags" in tweet_data["entities"]:
                    hashtags_list = [f"#{h['tag']}" for h in tweet_data["entities"]["hashtags"]]
                
                post = Post(
                    urn=tweet_data.get("id", ""),
                    text=tweet_data.get("text", ""),
                    author=user_id,
                    author_name="",  # Would need separate lookup
                    timestamp=timestamp,
                    hashtags=hashtags_list,
                )
                tweets.append(post)
            
            logger.info(f"📜 Fetched {len(tweets)} tweets from user {user_id}")
            return tweets
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user timeline: {e}")
            return []
    
    def get_mentions(self, max_tweets: int = 10) -> list[Post]:
        """Get tweets that mention the authenticated user.
        
        Returns:
            List of Post objects mentioning the user
        """
        if Config.DRY_RUN:
            logger.info("[DRY RUN] Would fetch mentions")
            return MockXAPI().get_mentions()
        
        self._respect_rate_limit()
        
        try:
            user_id = self._get_authenticated_user_id()
            if not user_id:
                return []
            
            response = requests.get(
                f"https://api.twitter.com/2/users/{user_id}/mentions",
                headers=self._headers(),
                params={
                    "max_results": min(max_tweets, 100),
                    "tweet.fields": "created_at,author_id,text,entities",
                    "expansions": "author_id",
                    "user.fields": "name,username",
                },
                timeout=30,
            )
            
            if response.status_code in (429, 401):
                return []
            
            response.raise_for_status()
            data = response.json()
            
            # Build user lookup
            users = {}
            if "includes" in data and "users" in data["includes"]:
                for user in data["includes"]["users"]:
                    users[user["id"]] = user
            
            tweets = []
            for tweet_data in data.get("data", []):
                created_at = tweet_data.get("created_at", "")
                try:
                    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except:
                    timestamp = datetime.now()
                
                author_id = tweet_data.get("author_id", "")
                author_info = users.get(author_id, {})
                
                hashtags_list = []
                if "entities" in tweet_data and "hashtags" in tweet_data["entities"]:
                    hashtags_list = [f"#{h['tag']}" for h in tweet_data["entities"]["hashtags"]]
                
                post = Post(
                    urn=tweet_data.get("id", ""),
                    text=tweet_data.get("text", ""),
                    author=author_id,
                    author_name=author_info.get("name", author_info.get("username", "Unknown")),
                    timestamp=timestamp,
                    hashtags=hashtags_list,
                    is_mention=True,  # Mark as mention
                )
                tweets.append(post)
            
            logger.info(f"📣 Fetched {len(tweets)} mentions")
            return tweets
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get mentions: {e}")
            return []
    
    def get_home_timeline(self, max_tweets: int = 10) -> list[Post]:
        """Get the authenticated user's home timeline.
        
        Returns:
            List of Post objects from home timeline
        """
        if Config.DRY_RUN:
            logger.info("[DRY RUN] Would fetch home timeline")
            return []
        
        self._respect_rate_limit()
        
        try:
            user_id = self._get_authenticated_user_id()
            if not user_id:
                return []
            
            response = requests.get(
                f"https://api.twitter.com/2/users/{user_id}/timelines/reverse_chronological",
                headers=self._oauth_headers(),  # Requires user context
                params={
                    "max_results": min(max_tweets, 100),
                    "tweet.fields": "created_at,author_id,text,entities",
                    "expansions": "author_id",
                    "user.fields": "name,username",
                    "exclude": "retweets",
                },
                timeout=30,
            )
            
            if response.status_code in (429, 401):
                return []
            
            response.raise_for_status()
            data = response.json()
            
            # Build user lookup
            users = {}
            if "includes" in data and "users" in data["includes"]:
                for user in data["includes"]["users"]:
                    users[user["id"]] = user
            
            tweets = []
            for tweet_data in data.get("data", []):
                created_at = tweet_data.get("created_at", "")
                try:
                    timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except:
                    timestamp = datetime.now()
                
                author_id = tweet_data.get("author_id", "")
                author_info = users.get(author_id, {})
                
                hashtags_list = []
                if "entities" in tweet_data and "hashtags" in tweet_data["entities"]:
                    hashtags_list = [f"#{h['tag']}" for h in tweet_data["entities"]["hashtags"]]
                
                post = Post(
                    urn=tweet_data.get("id", ""),
                    text=tweet_data.get("text", ""),
                    author=author_id,
                    author_name=author_info.get("name", author_info.get("username", "Unknown")),
                    timestamp=timestamp,
                    hashtags=hashtags_list,
                )
                tweets.append(post)
            
            logger.info(f"🏠 Fetched {len(tweets)} tweets from home timeline")
            return tweets
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get home timeline: {e}")
            return []
    
    def _get_authenticated_user_id(self) -> Optional[str]:
        """Get the authenticated user's ID.
        
        Caches the result for subsequent calls.
        """
        if hasattr(self, '_user_id') and self._user_id:
            return self._user_id
        
        try:
            response = requests.get(
                "https://api.twitter.com/2/users/me",
                headers=self._oauth_headers(),
                timeout=30,
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            self._user_id = data.get("data", {}).get("id")
            return self._user_id
            
        except requests.exceptions.RequestException:
            return None


class MockXAPI:
    """Mock X API for testing and dry-run mode."""
    
    def search_tweets(self, max_tweets: int = 10) -> list[Post]:
        """Return mock tweets for testing."""
        logger.info("[MOCK] Searching for tweets...")
        print("[MOCK] Searching for tweets...")
        
        mock_tweets = [
            Post(
                urn="mock-tweet-001",
                text="Just finished migrating our data warehouse to Apache Iceberg! The query performance improvements are incredible. #ApacheIceberg #DataLakehouse",
                author="mock-user-1",
                author_name="Jane DataEngineer",
                timestamp=datetime.now() - timedelta(hours=2),
                hashtags=["#ApacheIceberg", "#DataLakehouse"],
            ),
            Post(
                urn="mock-tweet-002", 
                text="CDC pipelines are getting more complex. We went from simple DB triggers to Debezium + Kafka + Spark. Looking for simpler alternatives. #CDC #DataEngineering",
                author="mock-user-2",
                author_name="Alex StreamPro",
                timestamp=datetime.now() - timedelta(hours=5),
                hashtags=["#CDC", "#DataEngineering"],
            ),
            Post(
                urn="mock-tweet-003",
                text="Hot take: The future is ELT, not ETL. Push transformations to where the data lives. Thoughts? #DataEngineering #ETL",
                author="mock-user-3",
                author_name="Morgan Analytics",
                timestamp=datetime.now() - timedelta(hours=12),
                hashtags=["#DataEngineering", "#ETL"],
            ),
        ]
        
        return mock_tweets[:max_tweets]
    
    def post_reply(self, tweet_id: str, reply_text: str) -> dict:
        """Mock posting a reply."""
        logger.info(f"[MOCK] Would reply to tweet {tweet_id}:")
        logger.info(f"[MOCK] Reply: {reply_text}")
        print(f"[MOCK] Would reply to tweet {tweet_id}:")
        print(f"[MOCK] Reply: {reply_text}")
        return {"success": True, "tweet_id": f"mock-reply-{int(time.time())}"}
    
    def like_tweet(self, tweet_id: str) -> dict:
        """Mock liking a tweet."""
        logger.info(f"[MOCK] Would like tweet {tweet_id}")
        print(f"[MOCK] Would like tweet {tweet_id}")
        return {"success": True}
    
    def retweet(self, tweet_id: str) -> dict:
        """Mock retweeting."""
        logger.info(f"[MOCK] Would retweet {tweet_id}")
        print(f"[MOCK] Would retweet {tweet_id}")
        return {"success": True}
    
    def quote_tweet(self, tweet_id: str, quote_text: str) -> dict:
        """Mock quote tweeting."""
        logger.info(f"[MOCK] Would quote tweet {tweet_id}: {quote_text}")
        print(f"[MOCK] Would quote tweet {tweet_id}: {quote_text}")
        return {"success": True, "tweet_id": f"mock-quote-{int(time.time())}"}
    
    def follow_user(self, user_id: str) -> dict:
        """Mock following a user."""
        logger.info(f"[MOCK] Would follow user {user_id}")
        print(f"[MOCK] Would follow user {user_id}")
        return {"success": True}
    
    def get_trends(self) -> list[str]:
        """Return mock trends for testing."""
        logger.info("[MOCK] Fetching trends...")
        return [
            "#ApacheIceberg",
            "#DataEngineering", 
            "#DataLakehouse",
            "#CDC",
            "#OpenSource",
        ]
    
    def get_mentions(self) -> list[Post]:
        """Return mock mentions for testing."""
        logger.info("[MOCK] Fetching mentions...")
        return [
            Post(
                urn="mock-mention-001",
                text="@OLake looks interesting! How does it compare to Airbyte for Iceberg?",
                author="mock-user-4",
                author_name="Curious DataEng",
                timestamp=datetime.now() - timedelta(hours=1),
                hashtags=["#ApacheIceberg"],
                is_mention=True,
            ),
        ]


# Global client instance
x_client = XClient()
