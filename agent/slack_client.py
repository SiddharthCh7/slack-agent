"""
Slack API client for OLake Community Agent.

Handles HTTP webhook events and Slack API interactions.
"""

import os
import hashlib
import hmac
import json
import time
from typing import Dict, List, Optional, Any
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from agent.utils.logger import get_logger


class SlackClient:
    """Slack API client with webhook event handling."""
    
    def __init__(
        self,
        bot_token: str,
        signing_secret: str,
        logger=None
    ):
        """
        Initialize Slack client.
        
        Args:
            bot_token: Slack bot token (xoxb-...)
            signing_secret: Slack signing secret for webhook verification
            logger: Optional logger instance
        """
        self.client = WebClient(token=bot_token)
        self.signing_secret = signing_secret
        self.bot_user_id = None
        self.logger = logger or get_logger()
        
        # Get bot user ID
        try:
            auth_response = self.client.auth_test()
            self.bot_user_id = auth_response["user_id"]
            self.logger.logger.info(f"Slack client initialized. Bot User ID: {self.bot_user_id}")
        except SlackApiError as e:
            self.logger.log_error(
                error_type="SlackAuthError",
                error_message=f"Failed to authenticate: {e.response['error']}",
                stack_trace=str(e)
            )
            raise
    
    def verify_signature(
        self,
        timestamp: str,
        body: str,
        signature: str
    ) -> bool:
        """
        Verify Slack request signature.
        
        Args:
            timestamp: X-Slack-Request-Timestamp header
            body: Raw request body
            signature: X-Slack-Signature header
            
        Returns:
            True if signature is valid
        """
        # Prevent replay attacks
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
        
        # Compute expected signature
        sig_basestring = f"v0:{timestamp}:{body}"
        expected_signature = 'v0=' + hmac.new(
            self.signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)
    
    def is_bot_message(self, event: Dict[str, Any]) -> bool:
        """Check if message is from the bot itself."""
        return event.get("user") == self.bot_user_id or event.get("bot_id") is not None
    
    def send_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Send a message to Slack.
        
        Args:
            channel: Channel ID
            text: Message text (fallback if blocks used)
            thread_ts: Thread timestamp for replies
            blocks: Optional Block Kit blocks
            
        Returns:
            Slack API response
        """
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts,
                blocks=blocks
            )
            
            self.logger.logger.debug(
                f"Message sent to {channel}" + 
                (f" (thread: {thread_ts})" if thread_ts else "")
            )
            
            return response
        except SlackApiError as e:
            err = e.response.get("error", "unknown")
            needed = e.response.get("needed") or ""
            if isinstance(needed, list):
                needed = ", ".join(needed)
            msg = f"Failed to send message: {err}"
            if needed:
                msg += f". Add scope(s) in Slack app: {needed}"
            self.logger.log_error(
                error_type="SlackMessageError",
                error_message=msg,
                channel_id=channel
            )
            raise
    
    def add_reaction(
        self,
        channel: str,
        timestamp: str,
        emoji: str
    ) -> None:
        """
        Add a reaction to a message.
        
        Args:
            channel: Channel ID
            timestamp: Message timestamp
            emoji: Emoji name (without colons, e.g., 'eyes')
        """
        try:
            self.client.reactions_add(
                channel=channel,
                timestamp=timestamp,
                name=emoji
            )
            self.logger.logger.debug(
                f"Added reaction :{emoji}: to message in {channel}"
            )
        except SlackApiError as e:
            # Ignore if reaction already exists
            if e.response["error"] != "already_reacted":
                self.logger.log_error(
                    error_type="SlackReactionError",
                    error_message=f"Failed to add reaction: {e.response['error']}",
                    channel_id=channel
                )
    
    def remove_reaction(
        self,
        channel: str,
        timestamp: str,
        emoji: str
    ) -> None:
        """
        Remove a reaction from a message.
        
        Args:
            channel: Channel ID
            timestamp: Message timestamp
            emoji: Emoji name (without colons)
        """
        try:
            self.client.reactions_remove(
                channel=channel,
                timestamp=timestamp,
                name=emoji
            )
        except SlackApiError as e:
            # Ignore if reaction doesn't exist
            if e.response["error"] != "no_reaction":
                self.logger.logger.warning(
                    f"Failed to remove reaction: {e.response['error']}"
                )
    
    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """
        Get user information.
        
        Args:
            user_id: Slack user ID
            
        Returns:
            User info dict
        """
        try:
            response = self.client.users_info(user=user_id)
            return response["user"]
        except SlackApiError as e:
            self.logger.log_error(
                error_type="SlackUserInfoError",
                error_message=f"Failed to get user info: {e.response['error']}",
                user_id=user_id
            )
            return {}
    
    def get_thread_messages(
        self,
        channel: str,
        thread_ts: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get messages in a thread.
        
        Args:
            channel: Channel ID
            thread_ts: Thread timestamp
            limit: Max messages to retrieve
            
        Returns:
            List of messages
        """
        try:
            response = self.client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=limit
            )
            return response.get("messages", [])
        except SlackApiError as e:
            self.logger.log_error(
                error_type="SlackThreadError",
                error_message=f"Failed to get thread: {e.response['error']}",
                channel_id=channel
            )
            return []
    
def create_slack_client(
    bot_token: Optional[str] = None,
    signing_secret: Optional[str] = None
) -> SlackClient:
    """
    Create a Slack client from environment variables.
    
    Args:
        bot_token: Optional bot token (uses env var if not provided)
        signing_secret: Optional signing secret (uses env var if not provided)
        
    Returns:
        Configured SlackClient instance
    """
    bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
    signing_secret = signing_secret or os.getenv("SLACK_SIGNING_SECRET")
    
    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN environment variable not set")
    if not signing_secret:
        raise ValueError("SLACK_SIGNING_SECRET environment variable not set")
    
    return SlackClient(bot_token=bot_token, signing_secret=signing_secret)
