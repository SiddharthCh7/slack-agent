"""LinkedIn API client for the OLake Marketing Agent.

Handles authentication, rate limiting, and API calls to LinkedIn.
Uses the linkedin-api library for unofficial API access.
"""

import time
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from agent.config import Config
from agent.state import Post
from agent.keywords import get_search_keywords, get_all_hashtags


class LinkedInClient:
    """Client for interacting with LinkedIn API.
    
    Note: This uses the unofficial linkedin-api library which requires
    LinkedIn credentials. For production use, consider using the official
    LinkedIn Marketing Developer Platform with OAuth 2.0.
    """
    
    def __init__(self):
        self._api = None
        self._last_request_time = None
        self._request_count = 0
        self._rate_limit_reset = None
        
    def _get_api(self):
        """Lazy-load the LinkedIn API client."""
        if self._api is None:
            # Use mock API in dry-run mode
            if Config.DRY_RUN:
                logger.info("Using Mock LinkedIn API (dry-run mode)")
                self._api = MockLinkedInAPI()
            else:
                try:
                    from linkedin_api import Linkedin
                    # Note: linkedin-api uses email/password authentication
                    # For production, use OAuth 2.0 with the Marketing API
                    logger.info("Initializing LinkedIn API client...")
                    # The access token approach - for official API
                    self._api = LinkedInOfficialAPI(Config.LINKEDIN_ACCESS_TOKEN)
                except ImportError:
                    logger.warning("linkedin-api not available, using mock client")
                    self._api = MockLinkedInAPI()
        return self._api
    
    def _respect_rate_limit(self):
        """Enforce rate limiting (100 requests/min per OAuth token)."""
        now = datetime.now()
        
        # Reset counter every minute
        if self._rate_limit_reset is None or now > self._rate_limit_reset:
            self._request_count = 0
            self._rate_limit_reset = now + timedelta(minutes=1)
        
        # Check if we're at the limit
        if self._request_count >= 100:
            wait_seconds = (self._rate_limit_reset - now).total_seconds()
            if wait_seconds > 0:
                logger.warning(f"Rate limit reached, waiting {wait_seconds:.1f}s")
                time.sleep(wait_seconds)
                self._request_count = 0
                self._rate_limit_reset = datetime.now() + timedelta(minutes=1)
        
        self._request_count += 1
    
    def search_posts(self, max_posts: int = 10) -> list[Post]:
        """Search for posts matching our target keywords and hashtags.
        
        Args:
            max_posts: Maximum number of posts to return
            
        Returns:
            List of Post objects matching our criteria
        """
        api = self._get_api()
        posts = []
        seen_urns = set()
        
        keywords = get_search_keywords()
        hashtags = get_all_hashtags()
        
        # Search by keywords first (higher priority)
        for keyword in keywords:
            if len(posts) >= max_posts:
                break
                
            self._respect_rate_limit()
            
            try:
                results = api.search_posts(keyword, limit=5)
                for post_data in results:
                    urn = post_data.get("urn", post_data.get("id", ""))
                    if urn and urn not in seen_urns:
                        seen_urns.add(urn)
                        post = self._parse_post(post_data)
                        if post:
                            posts.append(post)
                            if len(posts) >= max_posts:
                                break
            except Exception as e:
                logger.warning(f"Error searching for keyword '{keyword}': {e}")
        
        # Then search by hashtags
        for hashtag in hashtags:
            if len(posts) >= max_posts:
                break
                
            self._respect_rate_limit()
            
            try:
                results = api.search_posts(hashtag, limit=5)
                for post_data in results:
                    urn = post_data.get("urn", post_data.get("id", ""))
                    if urn and urn not in seen_urns:
                        seen_urns.add(urn)
                        post = self._parse_post(post_data)
                        if post:
                            posts.append(post)
                            if len(posts) >= max_posts:
                                break
            except Exception as e:
                logger.warning(f"Error searching for hashtag '{hashtag}': {e}")
        
        logger.info(f"Found {len(posts)} posts matching keywords/hashtags")
        return posts
    
    def _parse_post(self, post_data: dict) -> Optional[Post]:
        """Parse raw API response into a Post object."""
        try:
            # Handle different API response formats
            urn = post_data.get("urn") or post_data.get("id") or ""
            text = post_data.get("text") or post_data.get("commentary") or ""
            author = post_data.get("author") or post_data.get("actor") or ""
            author_name = post_data.get("author_name") or post_data.get("actorName") or "Unknown"
            
            # Parse timestamp
            timestamp_val = post_data.get("timestamp") or post_data.get("created_time")
            if isinstance(timestamp_val, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp_val / 1000)  # LinkedIn uses ms
            elif isinstance(timestamp_val, str):
                timestamp = datetime.fromisoformat(timestamp_val.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now()
            
            # Extract hashtags from text
            import re
            hashtags = re.findall(r'#\w+', text)
            
            if not text:
                return None
                
            return Post(
                urn=urn,
                text=text,
                author=author,
                author_name=author_name,
                timestamp=timestamp,
                hashtags=hashtags,
            )
        except Exception as e:
            logger.warning(f"Failed to parse post: {e}")
            return None
    
    def post_comment(self, post_urn: str, comment_text: str) -> dict:
        """Post a comment on a LinkedIn post.
        
        Args:
            post_urn: The URN of the post to comment on
            comment_text: The text of the comment
            
        Returns:
            dict with 'success', 'comment_id', and optionally 'error'
        """
        api = self._get_api()
        
        max_retries = 3
        retry_delays = [2, 4, 8]  # Exponential backoff
        
        for attempt in range(max_retries):
            self._respect_rate_limit()
            
            try:
                result = api.comment_on_post(post_urn, comment_text)
                return {
                    "success": True,
                    "comment_id": result.get("id", result.get("comment_id", "")),
                }
            except RateLimitError:
                if attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.warning(f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    return {"success": False, "error": "Rate limit exceeded after retries"}
            except TokenExpiredError:
                # Would trigger token refresh in production
                logger.error("LinkedIn access token expired")
                return {"success": False, "error": "Access token expired"}
            except Exception as e:
                logger.error(f"Failed to post comment: {e}")
                return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Max retries exceeded"}


class RateLimitError(Exception):
    """Raised when LinkedIn API rate limit is hit."""
    pass


class TokenExpiredError(Exception):
    """Raised when LinkedIn access token is expired."""
    pass


class LinkedInOfficialAPI:
    """Wrapper for official LinkedIn Marketing API calls.
    
    Note: This is a placeholder that shows the expected interface.
    In production, implement using requests with proper OAuth 2.0 headers.
    """
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://api.linkedin.com/v2"
        
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
    
    def search_posts(self, query: str, limit: int = 10) -> list[dict]:
        """Search for posts containing the query.
        
        Note: LinkedIn's official API has limited search capabilities.
        This is a simplified implementation.
        """
        import requests
        
        # Using the feed endpoint with query parameters
        # Note: Actual implementation depends on your API access level
        try:
            response = requests.get(
                f"{self.base_url}/feed?q=search&query={query}&count={limit}",
                headers=self._headers(),
                timeout=30,
            )
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            elif response.status_code == 401:
                raise TokenExpiredError("Access token expired")
            
            response.raise_for_status()
            data = response.json()
            
            return data.get("elements", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return []
    
    def comment_on_post(self, post_urn: str, comment_text: str) -> dict:
        """Post a comment on a post."""
        import requests
        
        payload = {
            "actor": f"urn:li:organization:{Config.LINKEDIN_CLIENT_ID}",
            "message": {
                "text": comment_text
            },
            "parentComment": post_urn if "comment" in post_urn else None,
            "object": post_urn,
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/socialActions/{post_urn}/comments",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            elif response.status_code == 401:
                raise TokenExpiredError("Access token expired")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to post comment: {e}")
            raise


class MockLinkedInAPI:
    """Mock LinkedIn API for testing and dry-run mode."""
    
    def search_posts(self, query: str, limit: int = 10) -> list[dict]:
        """Return mock posts for testing."""
        logger.info(f"[MOCK] Searching for posts with query: {query}")
        
        # Return some realistic mock data
        mock_posts = [
            {
                "urn": "urn:li:share:mock-001",
                "text": f"Just finished migrating our data warehouse to Apache Iceberg! The query performance improvements are incredible. #ApacheIceberg #DataLakehouse",
                "author": "urn:li:person:mock-author-1",
                "author_name": "Jane Data Engineer",
                "timestamp": int((datetime.now() - timedelta(hours=2)).timestamp() * 1000),
            },
            {
                "urn": "urn:li:share:mock-002", 
                "text": f"CDC pipelines are getting more complex. We went from simple DB triggers to Debezium + Kafka + Spark. Looking for simpler alternatives. #CDC #DataEngineering",
                "author": "urn:li:person:mock-author-2",
                "author_name": "Alex StreamPro",
                "timestamp": int((datetime.now() - timedelta(hours=5)).timestamp() * 1000),
            },
            {
                "urn": "urn:li:share:mock-003",
                "text": f"Hot take: The future is ELT, not ETL. Push transformations to where the data lives. Thoughts? #DataEngineering #ETL",
                "author": "urn:li:person:mock-author-3",
                "author_name": "Morgan Analytics",
                "timestamp": int((datetime.now() - timedelta(hours=12)).timestamp() * 1000),
            },
        ]
        
        return mock_posts[:limit]
    
    def comment_on_post(self, post_urn: str, comment_text: str) -> dict:
        """Mock posting a comment."""
        logger.info(f"[MOCK] Would post comment on {post_urn}:")
        logger.info(f"[MOCK] Comment: {comment_text}")
        return {"id": f"mock-comment-{int(time.time())}"}


# Global client instance
linkedin_client = LinkedInClient()
