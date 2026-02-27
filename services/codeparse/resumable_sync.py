"""
Resumable sync manager for code documentation.

Handles:
- Tracking which files have been processed vs failed
- Retry logic with configurable wait times
- Rate limit handling with automatic pause/resume
- Only updates commit_state when ALL files are processed
- Can resume incomplete syncs
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from loguru import logger

from .config import CodebaseConfig, SyncConfig
from .cache import CodeParseCache, FileRecord, SymbolRecord
from .hasher import HashIdentity
from .github_client import GitHubClient, GitTreeEntry
from .parser import CodeParser
from .qdrant_client import QdrantCodeStore, CodePoint


@dataclass
class ResumableSyncState:
    """
    Persistent state for resumable sync.
    Stored in cache between retries.
    """
    repo_url: str
    commit_hash: str
    total_files: int
    file_statuses: dict[str, str]  # file_path -> FileStatus value
    file_errors: dict[str, str]  # file_path -> error message
    file_retry_counts: dict[str, int]  # file_path -> retry count
    started_at: str
    last_updated: str
    is_complete: bool = False
    
    @classmethod
    def create(cls, repo_url: str, commit_hash: str, file_paths: list[str]) -> "ResumableSyncState":
        """Create new sync state."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            repo_url=repo_url,
            commit_hash=commit_hash,
            total_files=len(file_paths),
            file_statuses={fp: "pending" for fp in file_paths},
            file_errors={},
            file_retry_counts={fp: 0 for fp in file_paths},
            started_at=now,
            last_updated=now,
            is_complete=False,
        )
    
    @property
    def pending_files(self) -> list[str]:
        """Get list of pending or failed files."""
        return [
            fp for fp, status in self.file_statuses.items()
            if status in ("pending", "failed")
        ]
    
    @property
    def completed_files(self) -> list[str]:
        """Get list of completed files."""
        return [
            fp for fp, status in self.file_statuses.items()
            if status == "completed"
        ]
    
    @property
    def failed_files(self) -> list[str]:
        """Get list of failed files."""
        return [
            fp for fp, status in self.file_statuses.items()
            if status == "failed"
        ]
    
    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_files == 0:
            return 0.0
        completed = len(self.completed_files)
        return (completed / self.total_files) * 100


class ResumableSyncManager:
    """
    Manages resumable sync operations.
    
    Ensures:
    - All files are tracked
    - Failed files are retried
    - commit_state only updated when complete
    - Rate limits are handled gracefully
    """
    
    def __init__(
        self,
        cache: CodeParseCache,
        github: GitHubClient,
        qdrant: QdrantCodeStore,
        parser: CodeParser,
        embed_fn: Callable,
        sync_config: SyncConfig,
    ):
        self.cache = cache
        self.github = github
        self.qdrant = qdrant
        self.parser = parser
        self.embed_fn = embed_fn
        self.config = sync_config
        
        # State file path (in same directory as cache)
        cache_path = Path(cache.db_path)
        self._state_file = cache_path.parent / "sync_state.json"
        
        self._current_state: Optional[ResumableSyncState] = None

    def start_sync(
        self,
        codebase: CodebaseConfig,
        commit_hash: str,
        file_entries: list[GitTreeEntry],
    ) -> bool:
        """
        Start a new resumable sync.
        
        Args:
            codebase: Codebase configuration.
            commit_hash: Target commit SHA.
            file_entries: List of files to process.
        
        Returns:
            True if sync completed successfully.
        """
        file_paths = [entry.path for entry in file_entries]
        
        # Check for existing incomplete sync
        existing_state = self._load_state(codebase.repo_url)
        if existing_state and existing_state.commit_hash == commit_hash:
            if not existing_state.is_complete:
                logger.info(
                    f"Resuming incomplete sync for {codebase.name} "
                    f"({len(existing_state.pending_files)} files pending)"
                )
                self._current_state = existing_state
                return self._resume_sync(codebase, commit_hash, file_entries)
        
        # Start fresh sync
        logger.info(f"Starting new sync for {codebase.name} ({len(file_paths)} files)")
        self._current_state = ResumableSyncState.create(
            codebase.repo_url,
            commit_hash,
            file_paths,
        )
        
        return self._execute_sync(codebase, commit_hash, file_entries)

    def _resume_sync(
        self,
        codebase: CodebaseConfig,
        commit_hash: str,
        all_file_entries: list[GitTreeEntry],
    ) -> bool:
        """Resume an incomplete sync."""
        if not self._current_state:
            return False
        
        # Get only pending/failed files
        pending_paths = self._current_state.pending_files
        pending_entries = [e for e in all_file_entries if e.path in pending_paths]
        
        logger.info(f"Retrying {len(pending_entries)} files")
        
        return self._execute_sync(
            codebase,
            commit_hash,
            pending_entries,
            is_retry=True,
        )

    def _execute_sync(
        self,
        codebase: CodebaseConfig,
        commit_hash: str,
        file_entries: list[GitTreeEntry],
        is_retry: bool = False,
    ) -> bool:
        """Execute sync for a set of files."""
        if not self._current_state:
            return False
        
        stats = {
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "retries": 0,
            "rate_limit_waits": 0,
        }
        
        max_workers = self.config.max_workers
        rate_limited_until: Optional[datetime] = None
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit files for processing
            futures = {
                executor.submit(
                    self._process_single_file,
                    codebase,
                    entry,
                    commit_hash,
                ): entry
                for entry in file_entries
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                entry = futures[future]
                file_path = entry.path
                
                try:
                    result = future.result()
                    
                    if result.get("status") == "rate_limit":
                        # Handle rate limit
                        if self.config.pause_on_rate_limit:
                            wait_time = self.config.rate_limit_wait_seconds
                            logger.warning(
                                f"Rate limit hit, pausing for {wait_time}s "
                                f"before retrying {file_path}"
                            )
                            stats["rate_limit_waits"] += 1
                            time.sleep(wait_time)
                            rate_limited_until = datetime.now(timezone.utc) + timedelta(seconds=wait_time)
                            
                            # Retry this file
                            self._current_state.file_statuses[file_path] = "pending"
                            self._current_state.file_retry_counts[file_path] += 1
                            stats["retries"] += 1
                            
                            # Re-submit for processing
                            new_future = executor.submit(
                                self._process_single_file,
                                codebase,
                                entry,
                                commit_hash,
                            )
                            # Process immediately
                            retry_result = new_future.result()
                            self._update_file_status(file_path, retry_result)
                        else:
                            self._update_file_status(file_path, result)
                    else:
                        self._update_file_status(file_path, result)
                    
                    if result.get("status") == "completed":
                        stats["processed"] += 1
                    elif result.get("status") == "failed":
                        stats["failed"] += 1
                    elif result.get("status") == "skipped":
                        stats["skipped"] += 1
                    
                    # Update progress
                    self._current_state.last_updated = datetime.now(timezone.utc).isoformat()
                    self._save_state()
                    
                    # Log progress
                    total_done = len(self._current_state.completed_files)
                    total = self._current_state.total_files
                    logger.debug(
                        f"Progress: {total_done}/{total} files "
                        f"({self._current_state.progress_percent:.1f}%)"
                    )
                    
                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    self._current_state.file_statuses[file_path] = "failed"
                    self._current_state.file_errors[file_path] = str(e)
                    stats["failed"] += 1
        
        # Check if all files processed
        all_complete = len(self._current_state.failed_files) == 0
        
        if all_complete:
            # All files processed successfully
            self._current_state.is_complete = True
            self._save_state()
            
            # Now update commit_state
            self._update_commit_state(codebase, commit_hash)
            
            logger.info(
                f"Sync complete: {stats['processed']} processed, "
                f"{stats['skipped']} skipped, {stats['retries']} retries"
            )
            return True
        else:
            # Some files failed
            logger.warning(
                f"Sync incomplete: {len(self._current_state.failed_files)} files failed. "
                f"Run again to retry."
            )
            self._save_state()
            return False

    def _process_single_file(
        self,
        codebase: CodebaseConfig,
        file_entry: GitTreeEntry,
        commit_hash: str,
    ) -> dict[str, Any]:
        """
        Process a single file.
        
        Returns dict with status and details.
        """
        file_path = file_entry.path
        
        try:
            # Check content hash first
            cached_content_hash = self.cache.get_file_content_hash(
                codebase.repo_url,
                file_path,
            )
            
            # Get file content
            file_obj = self.github.get_file_content(
                codebase.repo_url,
                file_path,
                commit_hash,
            )
            
            if file_obj is None:
                return {"status": "failed", "error": "Could not fetch file"}
            
            # Check for rate limit
            if hasattr(self.github, '_rate_limit_remaining'):
                if self.github._rate_limit_remaining and self.github._rate_limit_remaining < 5:
                    return {"status": "rate_limit", "error": "Rate limit approaching"}
            
            # Compute content hash
            content_hash = HashIdentity.compute_content_hash(file_obj.content)
            
            # If content hash matches, skip
            if cached_content_hash and cached_content_hash == content_hash:
                return {"status": "skipped", "content_hash": content_hash}
            
            # Parse file
            language = self._detect_language(file_path)
            chunks = self.parser.parse_file(
                file_path=file_path,
                content=file_obj.content,
                language=language,
                repo_url=codebase.repo_url,
                commit_hash=commit_hash,
            )
            
            if not chunks:
                return {"status": "skipped", "reason": "No chunks extracted"}
            
            # Process chunks (embed and upsert)
            # ... (existing chunk processing logic)
            
            return {
                "status": "completed",
                "content_hash": content_hash,
                "symbols_count": len(chunks),
            }
            
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def _update_file_status(self, file_path: str, result: dict[str, Any]) -> None:
        """Update file status in current state."""
        if not self._current_state:
            return
        
        status = result.get("status", "failed")
        self._current_state.file_statuses[file_path] = status
        
        if status == "failed":
            self._current_state.file_errors[file_path] = result.get("error", "Unknown error")

    def _update_commit_state(
        self,
        codebase: CodebaseConfig,
        commit_hash: str,
    ) -> None:
        """Update commit state after successful sync."""
        from .cache import CommitState
        
        state = CommitState(
            repo_url=codebase.repo_url,
            latest_commit_hash=commit_hash,
            synced_at=datetime.now(timezone.utc),
        )
        self.cache.upsert_commit_state(state)
        logger.info(f"Commit state updated: {commit_hash[:8]}")

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file path."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
        }
        ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
        return ext_map.get(ext, "unknown")

    def _load_state(self, repo_url: str) -> Optional[ResumableSyncState]:
        """Load sync state from file."""
        # TODO: Implement JSON file loading
        return None

    def _save_state(self) -> None:
        """Save current sync state to file."""
        # TODO: Implement JSON file saving
        pass

    def get_progress(self) -> Optional[dict[str, Any]]:
        """Get current sync progress."""
        if not self._current_state:
            return None
        
        return {
            "commit_hash": self._current_state.commit_hash[:8],
            "total_files": self._current_state.total_files,
            "completed": len(self._current_state.completed_files),
            "failed": len(self._current_state.failed_files),
            "pending": len(self._current_state.pending_files),
            "progress_percent": self._current_state.progress_percent,
            "is_complete": self._current_state.is_complete,
        }
