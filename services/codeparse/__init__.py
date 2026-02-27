"""
Incremental Code Documentation System

Monitors GitHub repositories, parses code changes with tree-sitter,
and stores embeddings in Qdrant vector database with smart incremental updates.

Features:
- Resumable sync with retry support
- Rate limit handling with automatic pause/resume
- Progress tracking for incomplete syncs
"""

from .config import (
    Config,
    CodebaseConfig,
    ProcessingConfig,
    CacheConfig,
    QdrantConfig,
    SchedulerConfig,
    SyncConfig,
)
from .cache import CodeParseCache, FileRecord, SymbolRecord, CommitState
from .hasher import HashIdentity, compute_hash_identity
from .github_client import GitHubClient, GitHubFile, GitTreeEntry, CommitInfo
from .parser import CodeParser, CodeChunk, ChunkType
from .qdrant_client import QdrantCodeStore, CodePoint
from .sync import CodeSyncEngine, SyncResult, SyncStats
from .resumable_sync import ResumableSyncManager, ResumableSyncState
from .git_clone_sync import GitCloneSync, CloneResult, LocalSyncResult
from .search import CodeSearcher, SearchResult
from .scheduler import CodeparseScheduler, create_scheduler
from .utils import (
    setup_logging,
    setup_detailed_logging,
    retry,
    timed_operation,
    CodeParseError,
    GitHubAPIError,
    ParseError,
    QdrantError,
    CacheError,
    EmbeddingError,
    SyncError,
    ConfigError,
)

__all__ = [
    # Config
    "Config",
    "CodebaseConfig",
    "ProcessingConfig",
    "CacheConfig",
    "QdrantConfig",
    "SchedulerConfig",
    "SyncConfig",
    # Cache
    "CodeParseCache",
    "FileRecord",
    "SymbolRecord",
    "CommitState",
    # Hashing
    "HashIdentity",
    "compute_hash_identity",
    # GitHub
    "GitHubClient",
    "GitHubFile",
    "GitTreeEntry",
    "CommitInfo",
    # Parser
    "CodeParser",
    "CodeChunk",
    "ChunkType",
    # Qdrant
    "QdrantCodeStore",
    "CodePoint",
    # Sync
    "CodeSyncEngine",
    "SyncResult",
    "SyncStats",
    "ResumableSyncManager",
    "ResumableSyncState",
    "GitCloneSync",
    "CloneResult",
    "LocalSyncResult",
    # Search
    "CodeSearcher",
    "SearchResult",
    # Scheduler
    "CodeparseScheduler",
    "create_scheduler",
    # Utils
    "setup_logging",
    "setup_detailed_logging",
    "retry",
    "timed_operation",
    "CodeParseError",
    "GitHubAPIError",
    "ParseError",
    "QdrantError",
    "CacheError",
    "EmbeddingError",
    "SyncError",
    "ConfigError",
]
