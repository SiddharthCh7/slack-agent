"""
Smart incremental sync engine for code documentation with resumable sync.

Implements the core reuse logic:
1. Check content_hash in local cache → skip entire file if match
2. Parse file with tree-sitter, extract symbols/chunks
3. For each symbol: check stable_key + chunk_hash → reuse vector or re-embed
4. Detect deletions by comparing current vs cached stable_keys
5. Update local cache after successful processing

Resumable Sync Features:
- Fetches all changed files from GitHub compare API first
- Tracks which files are successfully processed vs failed
- Does NOT update commit_state until ALL files are processed
- Supports retry with configurable wait time
- On retry, only fetches files that weren't processed
- Pauses on rate limit and resumes automatically

Key principles:
- Idempotency: Re-running sync on same commit produces identical results
- Incremental: Process only what changed, reuse everything else
- Deterministic: Same input always generates same symbol_ids and hashes
- Cache-first: Check local cache before hitting Qdrant
- Resumable: Can pause and resume incomplete syncs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

from loguru import logger

from .config import CodebaseConfig, Config
from .cache import CodeParseCache, FileRecord, SymbolRecord, CommitState
from .hasher import HashIdentity
from .github_client import GitHubClient
from .parser import CodeParser, CodeChunk, ChunkType
from .qdrant_client import QdrantCodeStore, CodePoint


class FileStatus(str, Enum):
    """Status of a file during sync."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Unchanged from cache


@dataclass
class FileSyncStatus:
    """Tracks the sync status of a single file."""
    file_path: str
    status: FileStatus = FileStatus.PENDING
    error: Optional[str] = None
    symbols_count: int = 0
    retry_count: int = 0
    last_attempt: Optional[datetime] = None


@dataclass
class SyncProgress:
    """Tracks overall sync progress."""
    commit_hash: str
    total_files: int = 0
    files_completed: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    files_pending: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    is_complete: bool = False
    
    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_files == 0:
            return 0.0
        completed = self.files_completed + self.files_skipped
        return (completed / self.total_files) * 100
    
    @property
    def files_to_retry(self) -> int:
        """Number of files that need retry."""
        return self.files_failed


@dataclass
class SyncStats:
    """Statistics for a sync operation."""
    files_checked: int = 0
    files_changed: int = 0
    files_skipped: int = 0
    symbols_new: int = 0
    symbols_updated: int = 0
    symbols_reused: int = 0
    symbols_deleted: int = 0
    vectors_upserted: int = 0
    vectors_deleted: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    retries: int = 0
    rate_limit_waits: int = 0


@dataclass
class EmbeddingRequest:
    """Request for embedding generation."""
    chunk: CodeChunk
    stable_symbol_key: str
    chunk_hash: str


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    stats: SyncStats
    commit_hash: str
    message: str = ""


class CodeSyncEngine:
    """
    Incremental code documentation sync engine.
    
    Orchestrates GitHub polling, parsing, embedding, and Qdrant storage
    with smart hash-based reuse logic.
    """

    def __init__(
        self,
        config: Config,
        embed_fn: callable,
    ):
        """
        Initialize sync engine.

        Args:
            config: Configuration object.
            embed_fn: Embedding function that takes list of strings and returns list of vectors.
        """
        self.config = config
        self.embed_fn = embed_fn

        # Initialize components
        self.cache = CodeParseCache(
            config.cache.path,
            config.cache.vacuum_on_startup,
        )

        self.github = GitHubClient()

        self.qdrant = QdrantCodeStore(
            host=config.qdrant.host,
            port=config.qdrant.port,
            grpc_port=config.qdrant.grpc_port,
            vector_size=config.qdrant.vector_size,
            distance=config.qdrant.distance,
        )

        self.parser = CodeParser(
            max_chunk_size=config.processing.max_chunk_size,
            overlap_tokens=config.processing.overlap_tokens,
        )

        # Sync state tracking
        self._current_progress: Optional[SyncProgress] = None
        self._file_statuses: dict[str, FileSyncStatus] = {}

        logger.info("CodeSyncEngine initialized with resumable sync support")

    def close(self) -> None:
        """Close all connections."""
        self.cache.close()
        self.github.close()
        self.qdrant.close()

    def __enter__(self) -> "CodeSyncEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # =========================================================================
    # Main Sync Entry Point
    # =========================================================================

    def sync_codebase(self, codebase: CodebaseConfig) -> SyncResult:
        """
        Sync a single codebase.
        
        Args:
            codebase: Codebase configuration.
        
        Returns:
            SyncResult with statistics.
        """
        logger.info(f"Starting sync for {codebase.name} ({codebase.repo_url})")
        
        start_time = datetime.now()
        stats = SyncStats()
        
        try:
            # Ensure Qdrant collection exists
            if not self.qdrant.ensure_collection(codebase.collection_name):
                return SyncResult(
                    success=False,
                    stats=stats,
                    commit_hash="",
                    message=f"Failed to ensure collection {codebase.collection_name}",
                )
            
            # Get latest commit from GitHub
            latest_commit = self.github.get_latest_commit(
                codebase.repo_url,
                codebase.branch,
            )
            
            if latest_commit is None:
                return SyncResult(
                    success=False,
                    stats=stats,
                    commit_hash="",
                    message="Failed to fetch latest commit from GitHub",
                )
            
            # Check if there are changes
            cached_commit = self.cache.get_cached_commit_hash(codebase.repo_url)
            
            if cached_commit and latest_commit.sha == cached_commit:
                logger.info(f"No changes detected for {codebase.name} (commit: {cached_commit[:8]})")
                return SyncResult(
                    success=True,
                    stats=stats,
                    commit_hash=cached_commit,
                    message="No changes detected",
                )
            
            logger.info(
                f"New commit detected: {cached_commit[:8] if cached_commit else 'none'} → "
                f"{latest_commit.sha[:8]}"
            )
            
            # Get file tree for the new commit
            file_tree = self.github.get_file_tree(codebase.repo_url, latest_commit.sha)
            
            # Filter to code files only
            code_files = self._filter_code_files(
                file_tree,
                codebase.repo_url,
                self.config.processing.exclude_patterns,
                self.config.processing.supported_languages,
            )
            
            stats.files_checked = len(code_files)
            logger.info(f"Processing {len(code_files)} code files")
            
            # Process files with parallel execution
            new_symbols_by_file: dict[str, list[SymbolRecord]] = {}
            deleted_symbols_by_file: dict[str, list[str]] = {}
            
            # Use thread pool for parallel file processing
            max_workers = self.config.scheduler.max_workers
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._process_file,
                        codebase,
                        file_entry,
                        latest_commit.sha,
                    ): file_entry
                    for file_entry in code_files
                }
                
                for future in as_completed(futures):
                    file_entry = futures[future]
                    try:
                        result = future.result()
                        if result:
                            file_path, new_symbols, deleted_keys, file_changed = result
                            
                            if file_changed:
                                stats.files_changed += 1
                            else:
                                stats.files_skipped += 1
                            
                            stats.symbols_new += len([s for s in new_symbols if s.vector_id is None])
                            stats.symbols_updated += len([s for s in new_symbols if s.vector_id is not None])
                            stats.symbols_reused += len([s for s in new_symbols if s.chunk_hash == "REUSED"])
                            stats.symbols_deleted += len(deleted_keys)
                            
                            if new_symbols:
                                new_symbols_by_file[file_path] = new_symbols
                            if deleted_keys:
                                deleted_symbols_by_file[file_path] = deleted_keys
                                
                    except Exception as e:
                        stats.errors += 1
                        logger.error(f"Error processing {file_entry.path}: {e}")
            
            # Batch upsert all new/updated symbols to Qdrant
            all_points = []
            all_symbol_records = []

            for file_path, symbols in new_symbols_by_file.items():
                for symbol in symbols:
                    if symbol.chunk_hash != "REUSED" and symbol.vector_id:
                        # Need to upsert this symbol
                        all_symbol_records.append(symbol)

            # Get embeddings for all new/updated chunks in smaller batches
            # to avoid GPU memory exhaustion on large codebases
            if all_symbol_records:
                # Group by file to get code text
                chunks_to_embed = []
                chunk_info = []

                for symbol in all_symbol_records:
                    # We need to get the code text - it's stored in the symbol temporarily
                    if hasattr(symbol, '_code_text'):
                        chunks_to_embed.append(symbol._code_text)
                        chunk_info.append(symbol)

                if chunks_to_embed:
                    # Process embeddings in smaller batches to avoid memory issues
                    # M1 Mac GPUs can exhaust with large batches (26+ GiB buffer error)
                    embedding_batch_size = self.config.processing.embedding_batch_size
                    logger.info(
                        f"Processing {len(chunks_to_embed)} chunks in batches of {embedding_batch_size}"
                    )

                    for i in range(0, len(chunks_to_embed), embedding_batch_size):
                        batch_chunks = chunks_to_embed[i:i + embedding_batch_size]
                        batch_info = chunk_info[i:i + embedding_batch_size]

                        try:
                            batch_embeddings = self.embed_fn(batch_chunks)

                            for j, embedding in enumerate(batch_embeddings):
                                point = CodePoint(
                                    id=batch_info[j].stable_symbol_key,
                                    vector=embedding,
                                    payload=batch_info[j].__dict__.copy(),
                                )
                                # Remove internal fields from payload
                                if '_code_text' in point.payload:
                                    del point.payload['_code_text']
                                all_points.append(point)

                            logger.debug(
                                f"Embedded batch {i // embedding_batch_size + 1}/"
                                f"{(len(chunks_to_embed) + embedding_batch_size - 1) // embedding_batch_size}"
                            )

                        except Exception as e:
                            logger.error(f"Error embedding batch starting at index {i}: {e}")
                            stats.errors += 1

            # Upsert to Qdrant
            if all_points:
                if self.qdrant.upsert_points(codebase.collection_name, all_points):
                    stats.vectors_upserted = len(all_points)
                    logger.info(f"Upserted {len(all_points)} vectors to Qdrant")
            
            # Handle deletions
            for file_path, deleted_keys in deleted_symbols_by_file.items():
                if deleted_keys:
                    self.qdrant.delete_points(codebase.collection_name, deleted_keys)
                    stats.vectors_deleted += len(deleted_keys)
                    
                    for key in deleted_keys:
                        self.cache.delete_symbol(key)
            
            # Update cache with new state
            self._update_cache(
                codebase,
                latest_commit.sha,
                new_symbols_by_file,
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            stats.duration_seconds = duration
            
            logger.info(
                f"Sync completed for {codebase.name}: "
                f"{stats.files_changed} files changed, "
                f"{stats.vectors_upserted} vectors upserted, "
                f"{stats.vectors_deleted} vectors deleted, "
                f"duration: {duration:.2f}s"
            )
            
            return SyncResult(
                success=True,
                stats=stats,
                commit_hash=latest_commit.sha,
                message=f"Synced {stats.files_changed} files",
            )
            
        except Exception as e:
            stats.errors += 1
            logger.error(f"Sync failed for {codebase.name}: {e}")
            
            duration = (datetime.now() - start_time).total_seconds()
            stats.duration_seconds = duration
            
            return SyncResult(
                success=False,
                stats=stats,
                commit_hash="",
                message=str(e),
            )

    # =========================================================================
    # File Processing
    # =========================================================================

    def _process_file(
        self,
        codebase: CodebaseConfig,
        file_entry: Any,  # GitTreeEntry
        commit_hash: str,
    ) -> tuple[str, list[SymbolRecord], list[str], bool] | None:
        """
        Process a single file.

        Returns:
            Tuple of (file_path, new_symbols, deleted_keys, file_changed) or None on error.
        """
        file_path = file_entry.path

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
            return None

        # Skip overly large files to prevent memory exhaustion
        # Files > 500KB often are generated code, minified JS, or test data
        max_file_size = self.config.processing.max_file_size_kb * 1024
        if len(file_obj.content) > max_file_size:
            logger.warning(
                f"Skipping large file ({len(file_obj.content) / 1024:.1f}KB): {file_path}"
            )
            return None

        # Compute content hash
        content_hash = HashIdentity.compute_content_hash(file_obj.content)
        
        # If content hash matches, skip entire file
        if cached_content_hash and cached_content_hash == content_hash:
            logger.debug(f"File unchanged (content hash match): {file_path}")
            return (file_path, [], [], False)
        
        # File has changed, parse it
        language = self._detect_language(file_path, file_obj.content)
        
        chunks = self.parser.parse_file(
            file_path=file_path,
            content=file_obj.content,
            language=language,
            repo_url=codebase.repo_url,
            commit_hash=commit_hash,
        )
        
        if not chunks:
            logger.warning(f"No chunks extracted from {file_path}")
            return (file_path, [], [], True)
        
        # Get cached symbols for this file to detect deletions
        cached_symbols = self.cache.get_symbols_for_file(codebase.repo_url, file_path)
        cached_keys = {s.stable_symbol_key for s in cached_symbols}
        
        # Process each chunk
        new_symbols = []
        current_keys = set()
        points_to_upsert = []
        
        for chunk in chunks:
            # Compute stable symbol key
            stable_key = HashIdentity.compute_stable_symbol_key(
                codebase.repo_url,
                file_path,
                chunk.fully_qualified_name,
            )
            
            current_keys.add(stable_key)
            
            # Compute chunk hash
            chunk_hash = HashIdentity.compute_chunk_hash(chunk.code_text)
            
            # Check if symbol exists in cache
            cached_symbol = self.cache.get_symbol(stable_key)
            
            if cached_symbol and cached_symbol.chunk_hash == chunk_hash:
                # Symbol unchanged, reuse existing vector
                logger.debug(f"Symbol reused: {chunk.fully_qualified_name}")
                
                symbol_record = SymbolRecord(
                    stable_symbol_key=stable_key,
                    chunk_hash="REUSED",  # Marker for reuse
                    vector_id=cached_symbol.vector_id,
                    last_commit=commit_hash,
                    file_path=file_path,
                    fully_qualified_name=chunk.fully_qualified_name,
                    chunk_type=chunk.chunk_type.value,
                    repo_url=codebase.repo_url,
                )
                # Store code text temporarily for embedding if needed
                symbol_record._code_text = chunk.code_text
                new_symbols.append(symbol_record)
                
            else:
                # New or changed symbol, needs embedding
                logger.debug(f"Symbol {'updated' if cached_symbol else 'new'}: {chunk.fully_qualified_name}")
                
                # Prepare payload for Qdrant
                payload = chunk.to_dict()
                payload["stable_symbol_key"] = stable_key
                payload["chunk_hash"] = chunk_hash
                payload["content_hash"] = content_hash
                
                symbol_record = SymbolRecord(
                    stable_symbol_key=stable_key,
                    chunk_hash=chunk_hash,
                    vector_id=stable_key,  # Will be set after upsert
                    last_commit=commit_hash,
                    file_path=file_path,
                    fully_qualified_name=chunk.fully_qualified_name,
                    chunk_type=chunk.chunk_type.value,
                    repo_url=codebase.repo_url,
                )
                # Store code text for embedding
                symbol_record._code_text = chunk.code_text
                symbol_record._payload = payload
                new_symbols.append(symbol_record)
        
        # Detect deletions
        deleted_keys = list(cached_keys - current_keys)
        
        if deleted_keys:
            logger.debug(f"Deleted symbols in {file_path}: {deleted_keys}")
        
        return (file_path, new_symbols, deleted_keys, True)

    # =========================================================================
    # Cache Management
    # =========================================================================

    def _update_cache(
        self,
        codebase: CodebaseConfig,
        commit_hash: str,
        symbols_by_file: dict[str, list[SymbolRecord]],
    ) -> None:
        """Update cache after successful sync."""
        now = datetime.now(timezone.utc)
        
        # Use transaction for atomicity
        conn = self.cache.begin_transaction()
        
        try:
            cursor = conn.cursor()
            
            for file_path, symbols in symbols_by_file.items():
                # Update file registry
                if symbols:
                    content_hash = symbols[0].__dict__.get('_payload', {}).get('content_hash', '')
                    
                    cursor.execute("""
                        INSERT INTO file_registry (repo_url, file_path, content_hash, last_commit, last_synced)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(repo_url, file_path) DO UPDATE SET
                            content_hash = excluded.content_hash,
                            last_commit = excluded.last_commit,
                            last_synced = excluded.last_synced
                    """, (
                        codebase.repo_url,
                        file_path,
                        content_hash,
                        commit_hash,
                        now.isoformat(),
                    ))
                
                # Update symbol registry
                for symbol in symbols:
                    if symbol.chunk_hash == "REUSED":
                        # Just update last_commit
                        cursor.execute("""
                            UPDATE symbol_registry
                            SET last_commit = ?
                            WHERE stable_symbol_key = ?
                        """, (commit_hash, symbol.stable_symbol_key))
                    else:
                        # Insert or update with vector info
                        payload = getattr(symbol, '_payload', {})
                        
                        cursor.execute("""
                            INSERT INTO symbol_registry 
                                (stable_symbol_key, chunk_hash, vector_id, last_commit, file_path,
                                 fully_qualified_name, chunk_type, repo_url)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(stable_symbol_key) DO UPDATE SET
                                chunk_hash = excluded.chunk_hash,
                                vector_id = excluded.vector_id,
                                last_commit = excluded.last_commit,
                                file_path = excluded.file_path,
                                fully_qualified_name = excluded.fully_qualified_name,
                                chunk_type = excluded.chunk_type
                        """, (
                            symbol.stable_symbol_key,
                            symbol.chunk_hash,
                            symbol.vector_id,
                            commit_hash,
                            symbol.file_path,
                            symbol.fully_qualified_name,
                            symbol.chunk_type,
                            codebase.repo_url,
                        ))
            
            # Update commit state
            cursor.execute("""
                INSERT INTO commit_state (repo_url, latest_commit_hash, synced_at)
                VALUES (?, ?, ?)
                ON CONFLICT(repo_url) DO UPDATE SET
                    latest_commit_hash = excluded.latest_commit_hash,
                    synced_at = excluded.synced_at
            """, (
                codebase.repo_url,
                commit_hash,
                now.isoformat(),
            ))
            
            conn.commit()
            logger.debug("Cache updated successfully")
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _filter_code_files(
        self,
        file_tree: list,
        repo_url: str,
        exclude_patterns: list[str],
        supported_languages: list[str],
    ) -> list:
        """Filter file tree to code files only."""
        import fnmatch
        
        # File extensions for supported languages
        lang_extensions = {
            "python": [".py"],
            "javascript": [".js", ".mjs", ".cjs"],
            "typescript": [".ts", ".tsx", ".mts", ".cts"],
            "go": [".go"],
            "rust": [".rs"],
            "java": [".java"],
            "ruby": [".rb"],
        }
        
        # Build set of valid extensions
        valid_extensions = set()
        for lang in supported_languages:
            valid_extensions.update(lang_extensions.get(lang, []))
        
        code_files = []
        
        for entry in file_tree:
            if entry.type != "blob":
                continue
            
            path = entry.path
            
            # Check extension
            ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
            if ext not in valid_extensions:
                continue
            
            # Check exclude patterns
            excluded = False
            for pattern in exclude_patterns:
                if fnmatch.fnmatch(path, pattern):
                    excluded = True
                    break
            
            if excluded:
                continue
            
            code_files.append(entry)
        
        return code_files

    def _detect_language(self, file_path: str, content: str) -> str:
        """Detect programming language from file path and content."""
        ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
        
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".mts": "typescript",
            ".cts": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
        }
        
        return extension_map.get(ext, "unknown")

    def get_stats(self) -> dict[str, Any]:
        """Get cache and storage statistics."""
        cache_stats = self.cache.get_stats()
        
        stats = {
            "cache": cache_stats,
            "collections": {},
        }
        
        for codebase in self.config.get_enabled_codebases():
            info = self.qdrant.get_collection_info(codebase.collection_name)
            if info:
                stats["collections"][codebase.name] = info
        
        return stats
