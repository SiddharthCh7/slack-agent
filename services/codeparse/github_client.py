"""
GitHub API client for repository polling and change detection.

Uses GitHub REST API with optional authentication for higher rate limits:
- Unauthenticated: 60 requests/hour
- Authenticated: 5000 requests/hour

Endpoints:
  - GET /repos/{owner}/{repo}/commits/{branch} - Get latest commit
  - GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1 - Get file tree
  - GET /repos/{owner}/{repo}/contents/{path} - Get file content
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger


@dataclass
class GitHubFile:
    """Represents a file from GitHub repository."""
    path: str
    sha: str
    size: int
    content: str
    encoding: str  # 'base64' or 'none'
    last_modified: datetime


@dataclass
class GitTreeEntry:
    """Represents an entry in a git tree."""
    path: str
    sha: str
    type: str  # 'blob' or 'tree'
    mode: str
    size: Optional[int] = None


@dataclass
class CommitInfo:
    """Information about a git commit."""
    sha: str
    message: str
    author: str
    committed_at: datetime
    tree_sha: str


class GitHubClient:
    """
    GitHub REST API client with rate limit handling.
    
    Supports unauthenticated requests (60 req/hour) and 
    token-authenticated requests (5000 req/hour).
    """

    BASE_URL = "https://api.github.com"
    
    def __init__(
        self,
        token: Optional[str] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ):
        """
        Initialize GitHub client.

        Args:
            token: Optional GitHub personal access token for higher rate limits.
                   If not provided, will try to load from GITHUB_TOKEN env var.
            max_retries: Maximum number of retry attempts.
            base_delay: Initial delay between retries (seconds).
            max_delay: Maximum delay between retries (seconds).
        """
        # Auto-load token from environment if not provided
        if token is None:
            token = os.getenv("GITHUB_TOKEN")
            if token:
                logger.info("GitHub token loaded from environment")
            else:
                logger.warning("No GitHub token provided - using unauthenticated API (60 req/hour limit)")
        
        self.token = token
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        # Build headers
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "codeparse-agent/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
            logger.info("Using authenticated GitHub API (5000 req/hour limit)")
        else:
            logger.warning("Using unauthenticated GitHub API (60 req/hour limit)")

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=30.0,
        )
        
        self._rate_limit_remaining: Optional[int] = None
        self._rate_limit_reset: Optional[datetime] = None

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # =========================================================================
    # Public API
    # =========================================================================

    def get_latest_commit(self, repo_url: str, branch: str = "main") -> CommitInfo | None:
        """
        Get the latest commit for a branch.
        
        Args:
            repo_url: GitHub repository URL.
            branch: Branch name to check.
        
        Returns:
            CommitInfo if successful, None if repo not found or error.
        """
        owner, repo = self._parse_repo_url(repo_url)
        if not owner or not repo:
            logger.error(f"Invalid repo URL: {repo_url}")
            return None

        endpoint = f"/repos/{owner}/{repo}/commits/{branch}"
        
        try:
            response = self._request_with_retry("GET", endpoint)
            if response is None:
                return None
            
            data = response.json()
            return CommitInfo(
                sha=data["sha"],
                message=data["commit"]["message"],
                author=data["commit"]["author"]["name"],
                committed_at=datetime.fromisoformat(
                    data["commit"]["author"]["date"].replace("Z", "+00:00")
                ),
                tree_sha=data["commit"]["tree"]["sha"],
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Repository not found: {repo_url}/{branch}")
            else:
                logger.error(f"Error fetching commit: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching commit: {e}")
            return None

    def get_file_tree(
        self,
        repo_url: str,
        commit_sha: str,
    ) -> list[GitTreeEntry]:
        """
        Get the complete file tree for a commit.
        
        Args:
            repo_url: GitHub repository URL.
            commit_sha: Commit SHA or tree SHA.
        
        Returns:
            List of GitTreeEntry objects.
        """
        owner, repo = self._parse_repo_url(repo_url)
        if not owner or not repo:
            return []

        endpoint = f"/repos/{owner}/{repo}/git/trees/{commit_sha}"
        params = {"recursive": "1"}
        
        try:
            response = self._request_with_retry("GET", endpoint, params=params)
            if response is None:
                return []
            
            data = response.json()
            entries = []
            for item in data.get("tree", []):
                entries.append(GitTreeEntry(
                    path=item["path"],
                    sha=item["sha"],
                    type=item["type"],
                    mode=item["mode"],
                    size=item.get("size"),
                ))
            return entries
        except Exception as e:
            logger.error(f"Error fetching file tree: {e}")
            return []

    def get_file_content(
        self,
        repo_url: str,
        file_path: str,
        ref: str = "main",
    ) -> GitHubFile | None:
        """
        Get file content from repository.
        
        Args:
            repo_url: GitHub repository URL.
            file_path: Path to file within repo.
            ref: Branch name, tag, or commit SHA.
        
        Returns:
            GitHubFile with content, or None if not found.
        """
        owner, repo = self._parse_repo_url(repo_url)
        if not owner or not repo:
            return None

        # URL-encode the file path
        encoded_path = file_path.replace(" ", "%20")
        endpoint = f"/repos/{owner}/{repo}/contents/{encoded_path}"
        params = {"ref": ref}
        
        try:
            response = self._request_with_retry("GET", endpoint, params=params)
            if response is None:
                return None
            
            data = response.json()
            
            # Handle directory response
            if isinstance(data, list):
                logger.warning(f"Path is a directory: {file_path}")
                return None
            
            # Decode content if base64 encoded
            content = data.get("content", "")
            encoding = data.get("encoding", "none")
            
            if encoding == "base64":
                import base64
                content = base64.b64decode(content).decode("utf-8", errors="replace")
            
            # Parse last modified
            last_modified = datetime.now(timezone.utc)
            if "git_url" in data:
                # Try to get commit info for accurate timestamp
                pass
            
            return GitHubFile(
                path=data["path"],
                sha=data["sha"],
                size=data.get("size", len(content)),
                content=content,
                encoding="none",  # We decoded it
                last_modified=last_modified,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"File not found: {file_path}")
            else:
                logger.error(f"Error fetching file: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching file: {e}")
            return None

    def has_changes(
        self,
        repo_url: str,
        branch: str,
        cached_commit: str | None,
    ) -> bool:
        """
        Check if repository has new commits since cached commit.
        
        Args:
            repo_url: GitHub repository URL.
            branch: Branch to check.
            cached_commit: Previously cached commit SHA.
        
        Returns:
            True if there are new commits, False otherwise.
        """
        latest = self.get_latest_commit(repo_url, branch)
        if latest is None:
            return False
        
        if cached_commit is None:
            return True
        
        return latest.sha != cached_commit

    def get_changed_files(
        self,
        repo_url: str,
        base_commit: str,
        head_commit: str,
    ) -> list[str]:
        """
        Get list of files changed between two commits.
        
        Args:
            repo_url: GitHub repository URL.
            base_commit: Base commit SHA.
            head_commit: Head commit SHA.
        
        Returns:
            List of file paths that changed.
        """
        owner, repo = self._parse_repo_url(repo_url)
        if not owner or not repo:
            return []

        endpoint = f"/repos/{owner}/{repo}/compare/{base_commit}...{head_commit}"
        
        try:
            response = self._request_with_retry("GET", endpoint)
            if response is None:
                return []
            
            data = response.json()
            files = []
            for file_obj in data.get("files", []):
                files.append(file_obj["filename"])
            return files
        except Exception as e:
            logger.error(f"Error fetching changed files: {e}")
            return []

    def check_rate_limit(self) -> dict[str, Any]:
        """
        Check current rate limit status.
        
        Returns:
            Dict with rate limit information.
        """
        try:
            response = self._client.get("/rate_limit")
            response.raise_for_status()
            data = response.json()
            return data.get("resources", {}).get("core", {})
        except Exception as e:
            logger.warning(f"Could not check rate limit: {e}")
            return {}

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _parse_repo_url(self, repo_url: str) -> tuple[str | None, str | None]:
        """
        Parse GitHub repo URL into owner and repo name.
        
        Args:
            repo_url: Full GitHub URL or owner/repo format.
        
        Returns:
            Tuple of (owner, repo) or (None, None) if invalid.
        """
        # Handle full URL format
        if repo_url.startswith("http://") or repo_url.startswith("https://"):
            parsed = urlparse(repo_url)
            if parsed.hostname != "github.com":
                logger.warning(f"Not a GitHub URL: {repo_url}")
                return None, None
            
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
            return None, None
        
        # Handle owner/repo format
        if "/" in repo_url:
            parts = repo_url.strip("/").split("/")
            if len(parts) == 2:
                return parts[0], parts[1]
        
        logger.error(f"Invalid repo URL format: {repo_url}")
        return None, None

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> httpx.Response | None:
        """
        Make HTTP request with exponential backoff retry.
        
        Args:
            method: HTTP method.
            endpoint: API endpoint path.
            params: Optional query parameters.
        
        Returns:
            Response object or None if all retries failed.
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                response = self._client.request(method, endpoint, params=params)
                
                # Update rate limit tracking
                self._update_rate_limit(response)
                
                # Handle rate limit exceeded
                if response.status_code == 403:
                    remaining = response.headers.get("X-RateLimit-Remaining", "0")
                    if remaining == "0":
                        reset_time = response.headers.get("X-RateLimit-Reset")
                        if reset_time:
                            wait_time = max(
                                int(reset_time) - int(time.time()),
                                self.base_delay
                            )
                            wait_time = min(wait_time, self.max_delay)
                            logger.warning(
                                f"Rate limit exceeded, waiting {wait_time}s"
                            )
                            time.sleep(wait_time)
                            continue
                
                # Handle server errors (retryable)
                if response.status_code >= 500:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(
                        f"Server error {response.status_code}, retrying in {wait_time}s"
                    )
                    time.sleep(wait_time)
                    continue
                
                # Raise for other HTTP errors
                response.raise_for_status()
                return response
                
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500:
                    wait_time = self._calculate_backoff(attempt)
                    logger.warning(f"HTTP error {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    raise  # Non-retryable error
            
            except httpx.RequestError as e:
                last_error = e
                wait_time = self._calculate_backoff(attempt)
                logger.warning(f"Request error {e}, retrying in {wait_time}s")
                time.sleep(wait_time)
        
        logger.error(f"All {self.max_retries} retries failed for {endpoint}")
        return None

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self.base_delay * (2 ** attempt)
        # Add jitter
        import random
        delay = delay * (0.5 + random.random())
        return min(delay, self.max_delay)

    def _update_rate_limit(self, response: httpx.Response) -> None:
        """Update rate limit tracking from response headers."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        limit = response.headers.get("X-RateLimit-Limit")
        
        if remaining:
            self._rate_limit_remaining = int(remaining)
            # Warn when approaching limit
            if self._rate_limit_remaining < 10:
                logger.warning(f"⚠️  Rate limit low: {self._rate_limit_remaining}/{limit} requests remaining")
            elif self._rate_limit_remaining < 50:
                logger.info(f"Rate limit: {self._rate_limit_remaining}/{limit} requests remaining")
                
        if reset:
            self._rate_limit_reset = datetime.fromtimestamp(
                int(reset), tz=timezone.utc
            )
            if self._rate_limit_remaining and self._rate_limit_remaining < 10:
                reset_time = self._rate_limit_reset.strftime("%H:%M:%S")
                logger.warning(f"Rate limit resets at: {reset_time}")
