"""
Git clone-based sync for efficient initial repository processing.

Workflow:
1. Check if repo exists in cache (via commit_state)
2. If NOT exists:
   - Clone with git clone --depth 1 (shallow clone)
   - Process all files locally (no API calls)
   - Delete cloned repo after processing
3. If EXISTS:
   - Use GitHub API for incremental updates

This is much more efficient for initial sync:
- No rate limits (local file access)
- Faster (single clone vs hundreds of API calls)
- Cheaper (no API quota usage)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Callable

from loguru import logger

from .config import CodebaseConfig, Config, SyncConfig
from .cache import CodeParseCache, FileRecord, SymbolRecord, CommitState
from .hasher import HashIdentity
from .parser import CodeParser, CodeChunk
from .qdrant_client import QdrantCodeStore, CodePoint


@dataclass
class CloneResult:
    """Result of git clone operation."""
    success: bool
    repo_path: Path
    commit_hash: str
    error: Optional[str] = None


@dataclass
class LocalSyncResult:
    """Result of local file sync."""
    files_processed: int
    files_skipped: int
    symbols_count: int
    vectors_upserted: int
    errors: int


class GitCloneSync:
    """
    Efficient sync using git clone for initial repository processing.
    
    Usage:
        sync = GitCloneSync(cache, qdrant, parser, embed_fn, config)
        result = sync.sync_codebase(codebase)
    """
    
    def __init__(
        self,
        cache: CodeParseCache,
        qdrant: QdrantCodeStore,
        parser: CodeParser,
        embed_fn: Callable,
        config: Config,
        temp_dir: Optional[Path] = None,
    ):
        """
        Initialize git clone sync.

        Args:
            cache: SQLite cache for tracking state.
            qdrant: Qdrant vector store.
            parser: Code parser.
            embed_fn: Embedding function.
            config: Full configuration object.
            temp_dir: Directory for cloning (default: system temp).
        """
        self.cache = cache
        self.qdrant = qdrant
        self.parser = parser
        self.embed_fn = embed_fn
        self.config = config
        self.temp_dir = temp_dir or Path(tempfile.gettempdir()) / "codeparse_clones"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"GitCloneSync initialized (temp dir: {self.temp_dir})")

    def should_clone(self, repo_url: str) -> bool:
        """
        Check if we should clone the repo (no cached data).
        
        Args:
            repo_url: Repository URL.
        
        Returns:
            True if no cached data exists (should clone).
        """
        commit_state = self.cache.get_commit_state(repo_url)
        should_clone = commit_state is None
        
        if should_clone:
            logger.info(f"No cached data for {repo_url}, will clone")
        else:
            logger.info(f"Cached data exists for {repo_url} (commit: {commit_state.latest_commit_hash[:8]}), using API")
        
        return should_clone

    def sync_codebase(self, codebase: CodebaseConfig) -> LocalSyncResult:
        """
        Sync a codebase using git clone.
        
        Args:
            codebase: Codebase configuration.
        
        Returns:
            Sync result with statistics.
        """
        logger.info(f"Starting git clone sync for {codebase.name}")
        
        # Check if we should clone
        if not self.should_clone(codebase.repo_url):
            logger.info(f"Using GitHub API for incremental sync")
            # Fall back to API-based sync
            return self._api_sync(codebase)
        
        # Clone the repository
        clone_result = self._clone_repo(codebase.repo_url, codebase.branch)
        
        if not clone_result.success:
            logger.error(f"Clone failed: {clone_result.error}")
            return LocalSyncResult(
                files_processed=0,
                files_skipped=0,
                symbols_count=0,
                vectors_upserted=0,
                errors=1,
            )
        
        try:
            # Process the cloned repo
            result = self._process_local_repo(
                codebase,
                clone_result.repo_path,
                clone_result.commit_hash,
            )
            
            logger.info(
                f"Local sync complete: {result.files_processed} files, "
                f"{result.symbols_count} symbols, {result.vectors_upserted} vectors"
            )
            
            return result
            
        finally:
            # Always clean up
            self._cleanup_repo(clone_result.repo_path)

    def _clone_repo(self, repo_url: str, branch: str = "main") -> CloneResult:
        """
        Clone repository with --depth 1 (shallow clone).
        
        Args:
            repo_url: Repository URL.
            branch: Branch to clone.
        
        Returns:
            CloneResult with repo path and commit hash.
        """
        # Create temp directory for this repo
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        
        clone_path = self.temp_dir / f"{repo_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        clone_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Cloning {repo_url} (branch: {branch}) to {clone_path}")
        
        try:
            # Git clone with --depth 1 (shallow clone, fastest)
            cmd = [
                "git", "clone",
                "--depth", "1",  # Only latest commit
                "--single-branch",  # Only specified branch
                "--branch", branch,
                "--quiet",  # Suppress output
                repo_url,
                str(clone_path),
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Clone failed"
                logger.error(f"Git clone failed: {error_msg}")
                
                # Clean up failed clone
                if clone_path.exists():
                    shutil.rmtree(clone_path)
                
                return CloneResult(
                    success=False,
                    repo_path=clone_path,
                    commit_hash="",
                    error=error_msg,
                )
            
            # Get commit hash
            commit_hash = self._get_commit_hash(clone_path)
            
            logger.info(f"Clone successful: {repo_url} @ {commit_hash[:8]}")
            
            return CloneResult(
                success=True,
                repo_path=clone_path,
                commit_hash=commit_hash,
            )
            
        except subprocess.TimeoutExpired:
            logger.error(f"Git clone timed out (5 minutes)")
            if clone_path.exists():
                shutil.rmtree(clone_path)
            
            return CloneResult(
                success=False,
                repo_path=clone_path,
                commit_hash="",
                error="Clone timed out",
            )
        except Exception as e:
            logger.error(f"Git clone error: {e}")
            if clone_path.exists():
                shutil.rmtree(clone_path)
            
            return CloneResult(
                success=False,
                repo_path=clone_path,
                commit_hash="",
                error=str(e),
            )

    def _get_commit_hash(self, repo_path: Path) -> str:
        """Get current commit hash from cloned repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception as e:
            logger.warning(f"Could not get commit hash: {e}")
            return "unknown"

    def _process_local_repo(
        self,
        codebase: CodebaseConfig,
        repo_path: Path,
        commit_hash: str,
    ) -> LocalSyncResult:
        """
        Process all files in cloned repository.
        
        Args:
            codebase: Codebase configuration.
            repo_path: Path to cloned repo.
            commit_hash: Current commit hash.
        
        Returns:
            LocalSyncResult with statistics.
        """
        logger.info(f"Processing local repo at {repo_path}")
        
        # Ensure Qdrant collection exists
        if not self.qdrant.ensure_collection(codebase.collection_name):
            return LocalSyncResult(0, 0, 0, 0, 1)
        
        stats = {
            "files_processed": 0,
            "files_skipped": 0,
            "symbols_count": 0,
            "vectors_upserted": 0,
            "errors": 0,
        }
        
        # Find all code files
        code_files = self._find_code_files(repo_path)
        logger.info(f"Found {len(code_files)} code files")
        
        # Process files in batches
        batch_size = 100
        all_points = []
        
        for i, file_path in enumerate(code_files):
            try:
                # Read file content
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                # Skip overly large files to prevent memory exhaustion
                max_file_size = self.config.processing.max_file_size_kb * 1024
                if len(content) > max_file_size:
                    logger.debug(
                        f"Skipping large file ({len(content) / 1024:.1f}KB): {file_path}"
                    )
                    stats["files_skipped"] += 1
                    continue

                # Compute content hash
                content_hash = HashIdentity.compute_content_hash(content)
                
                # Check cache
                cached_hash = self.cache.get_file_content_hash(codebase.repo_url, str(file_path.relative_to(repo_path)))
                
                if cached_hash and cached_hash == content_hash:
                    stats["files_skipped"] += 1
                    continue
                
                # Parse file
                rel_path = str(file_path.relative_to(repo_path))
                language = self._detect_language(file_path)
                
                try:
                    chunks = self.parser.parse_file(
                        file_path=rel_path,
                        content=content,
                        language=language,
                        repo_url=codebase.repo_url,
                        commit_hash=commit_hash,
                    )
                except Exception as parse_error:
                    # Log parse error but continue with other files
                    logger.warning(
                        f"Parse failed for {rel_path}: {parse_error}. "
                        f"Skipping this file."
                    )
                    stats["errors"] += 1
                    continue
                
                if not chunks:
                    logger.debug(f"No chunks extracted from {rel_path}")
                    stats["files_skipped"] += 1
                    continue
                
                # Process chunks
                for chunk in chunks:
                    stable_key = HashIdentity.compute_stable_symbol_key(
                        codebase.repo_url,
                        rel_path,
                        chunk.fully_qualified_name,
                    )
                    chunk_hash = HashIdentity.compute_chunk_hash(chunk.code_text)
                    
                    # Check if symbol exists and unchanged
                    cached_symbol = self.cache.get_symbol(stable_key)
                    
                    if cached_symbol and cached_symbol.chunk_hash == chunk_hash:
                        # Reuse existing vector
                        continue
                    
                    # New or changed symbol - prepare for embedding
                    payload = chunk.to_dict()
                    payload["stable_symbol_key"] = stable_key
                    payload["chunk_hash"] = chunk_hash
                    payload["content_hash"] = content_hash
                    
                    all_points.append(CodePoint(
                        id=stable_key,
                        vector=[],  # Will be filled after embedding
                        payload=payload,
                    ))
                    
                    # Update cache
                    self.cache.upsert_symbol(SymbolRecord(
                        stable_symbol_key=stable_key,
                        chunk_hash=chunk_hash,
                        vector_id=stable_key,
                        last_commit=commit_hash,
                        file_path=rel_path,
                        fully_qualified_name=chunk.fully_qualified_name,
                        chunk_type=chunk.chunk_type.value,
                        repo_url=codebase.repo_url,
                    ))
                
                # Update file registry
                self.cache.upsert_file(FileRecord(
                    repo_url=codebase.repo_url,
                    file_path=rel_path,
                    content_hash=content_hash,
                    last_commit=commit_hash,
                    last_synced=datetime.now(timezone.utc),
                ))
                
                stats["files_processed"] += 1
                stats["symbols_count"] += len(chunks)
                
                # Batch upsert to Qdrant
                if len(all_points) >= batch_size:
                    self._upsert_batch(codebase, all_points)
                    stats["vectors_upserted"] += len(all_points)
                    all_points = []
                
                # Progress logging
                if (i + 1) % 50 == 0:
                    logger.info(f"Progress: {i + 1}/{len(code_files)} files")
                
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
                stats["errors"] += 1
        
        # Upsert remaining points
        if all_points:
            self._upsert_batch(codebase, all_points)
            stats["vectors_upserted"] += len(all_points)
        
        # Update commit state
        self.cache.upsert_commit_state(CommitState(
            repo_url=codebase.repo_url,
            latest_commit_hash=commit_hash,
            synced_at=datetime.now(timezone.utc),
        ))
        
        return LocalSyncResult(
            files_processed=stats["files_processed"],
            files_skipped=stats["files_skipped"],
            symbols_count=stats["symbols_count"],
            vectors_upserted=stats["vectors_upserted"],
            errors=stats["errors"],
        )

    def _upsert_batch(
        self,
        codebase: CodebaseConfig,
        points: list[CodePoint],
    ) -> None:
        """Embed and upsert a batch of points to Qdrant."""
        if not points:
            return
        
        # Extract code texts for embedding
        code_texts = [p.payload.get("code_text", "") for p in points]
        
        # Generate embeddings
        embeddings = self.embed_fn(code_texts)
        
        # Assign embeddings to points
        for i, point in enumerate(points):
            point.vector = embeddings[i]
        
        # Upsert to Qdrant
        self.qdrant.upsert_points(codebase.collection_name, points, batch_size=100)

    def _find_code_files(self, repo_path: Path) -> list[Path]:
        """
        Find all code files in repository.
        
        Args:
            repo_path: Path to cloned repo.
        
        Returns:
            List of code file paths.
        """
        # File extensions to include
        extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".go", ".rs", ".java", ".rb",
            ".c", ".cpp", ".h", ".hpp",
            ".cs", ".php", ".swift", ".kt",
        }
        
        # Directories to exclude
        exclude_dirs = {
            "__pycache__", "node_modules", "vendor",
            ".git", ".venv", "venv", "env",
            "dist", "build", "target", "out",
            ".pytest_cache", ".mypy_cache",
        }
        
        # Patterns to exclude
        exclude_patterns = {
            "*.min.js", "*.bundle.js", "*.config.js",
        }
        
        code_files = []
        
        for root, dirs, files in os.walk(repo_path):
            # Remove excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                file_path = Path(root) / file
                
                # Check extension
                if file_path.suffix not in extensions:
                    continue
                
                # Check patterns
                if any(file_path.match(pattern) for pattern in exclude_patterns):
                    continue
                
                code_files.append(file_path)
        
        return code_files

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
        }
        ext = file_path.suffix.lower()
        return ext_map.get(ext, "unknown")

    def _cleanup_repo(self, repo_path: Path) -> None:
        """Delete cloned repository."""
        try:
            if repo_path.exists():
                shutil.rmtree(repo_path)
                logger.info(f"Cleaned up cloned repo: {repo_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up {repo_path}: {e}")

    def _api_sync(self, codebase: CodebaseConfig) -> LocalSyncResult:
        """
        Fall back to API-based sync for repos with cached data.
        
        This is a placeholder - in production, you'd call the existing
        CodeSyncEngine.sync_codebase() method.
        """
        logger.warning("API-based sync not implemented in GitCloneSync")
        logger.warning("Use CodeSyncEngine for incremental updates")
        
        return LocalSyncResult(0, 0, 0, 0, 1)

    def clear_codebase_data(self, codebase: CodebaseConfig) -> bool:
        """
        Clear all cached data for a codebase.
        
        Args:
            codebase: Codebase configuration.
        
        Returns:
            True if cleared successfully.
        """
        logger.info(f"Clearing all data for {codebase.name}")
        
        try:
            # Clear cache
            self.cache.clear_repo_data(codebase.repo_url)
            
            # Clear Qdrant collection
            self.qdrant.delete_collection(codebase.collection_name)
            
            logger.info(f"Cleared all data for {codebase.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to clear data: {e}")
            return False
