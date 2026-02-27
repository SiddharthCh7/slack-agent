"""
SQLite cache layer for the code documentation system.

Provides fast local hash registry to minimize Qdrant API calls.
Tables:
  - file_registry: file_path → content_hash, last_commit, last_synced
  - symbol_registry: stable_symbol_key → chunk_hash, vector_id, last_commit, file_path
  - commit_state: repo_url → latest_commit_hash, synced_at
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger


@dataclass
class FileRecord:
    """Represents a file registry entry."""
    file_path: str
    content_hash: str
    last_commit: str
    last_synced: datetime
    repo_url: str = ""


@dataclass
class SymbolRecord:
    """Represents a symbol registry entry."""
    stable_symbol_key: str
    chunk_hash: str
    vector_id: Optional[str]
    last_commit: str
    file_path: str
    repo_url: str = ""
    fully_qualified_name: str = ""
    chunk_type: str = ""


@dataclass
class CommitState:
    """Represents commit state for a repository."""
    repo_url: str
    latest_commit_hash: str
    synced_at: datetime


class CodeParseCache:
    """
    SQLite-backed cache for code parsing state.
    
    Thread-safe with connection pooling via context manager.
    """

    def __init__(self, db_path: str | Path, vacuum_on_startup: bool = False):
        """
        Initialize cache database.
        
        Args:
            db_path: Path to SQLite database file.
            vacuum_on_startup: If True, run VACUUM on startup to optimize.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initializing cache at {self.db_path}")
        self._init_db()
        
        if vacuum_on_startup:
            self._vacuum()

    @contextmanager
    def _get_connection(self):
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # File registry table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_registry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_url TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    last_commit TEXT NOT NULL,
                    last_synced TEXT NOT NULL,
                    UNIQUE(repo_url, file_path)
                )
            """)
            
            # Symbol registry table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS symbol_registry (
                    stable_symbol_key TEXT PRIMARY KEY,
                    chunk_hash TEXT NOT NULL,
                    vector_id TEXT,
                    last_commit TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    fully_qualified_name TEXT,
                    chunk_type TEXT,
                    repo_url TEXT NOT NULL
                )
            """)
            
            # Commit state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS commit_state (
                    repo_url TEXT PRIMARY KEY,
                    latest_commit_hash TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                )
            """)
            
            # Create indexes for fast lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_file_registry_repo_path 
                ON file_registry(repo_url, file_path)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_registry_file 
                ON symbol_registry(repo_url, file_path)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_registry_vector 
                ON symbol_registry(vector_id) WHERE vector_id IS NOT NULL
            """)

    def _vacuum(self) -> None:
        """Run VACUUM to optimize database file."""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
        logger.debug("Cache database vacuumed")

    # =========================================================================
    # File Registry Operations
    # =========================================================================

    def upsert_file(self, record: FileRecord) -> None:
        """Insert or update a file record."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO file_registry (repo_url, file_path, content_hash, last_commit, last_synced)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repo_url, file_path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    last_commit = excluded.last_commit,
                    last_synced = excluded.last_synced
            """, (
                record.repo_url,
                record.file_path,
                record.content_hash,
                record.last_commit,
                record.last_synced.isoformat(),
            ))

    def get_file(self, repo_url: str, file_path: str) -> FileRecord | None:
        """Get a file record by repo and path."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT repo_url, file_path, content_hash, last_commit, last_synced
                FROM file_registry
                WHERE repo_url = ? AND file_path = ?
            """, (repo_url, file_path))
            
            row = cursor.fetchone()
            if row:
                return FileRecord(
                    repo_url=row["repo_url"],
                    file_path=row["file_path"],
                    content_hash=row["content_hash"],
                    last_commit=row["last_commit"],
                    last_synced=datetime.fromisoformat(row["last_synced"]),
                )
            return None

    def get_file_content_hash(self, repo_url: str, file_path: str) -> str | None:
        """Quick lookup of content hash for a file."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT content_hash FROM file_registry
                WHERE repo_url = ? AND file_path = ?
            """, (repo_url, file_path))
            row = cursor.fetchone()
            return row["content_hash"] if row else None

    def get_files_for_commit(self, repo_url: str, commit_hash: str) -> list[FileRecord]:
        """Get all files synced at a specific commit."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT repo_url, file_path, content_hash, last_commit, last_synced
                FROM file_registry
                WHERE repo_url = ? AND last_commit = ?
            """, (repo_url, commit_hash))
            
            return [
                FileRecord(
                    repo_url=row["repo_url"],
                    file_path=row["file_path"],
                    content_hash=row["content_hash"],
                    last_commit=row["last_commit"],
                    last_synced=datetime.fromisoformat(row["last_synced"]),
                )
                for row in cursor.fetchall()
            ]

    def delete_file(self, repo_url: str, file_path: str) -> bool:
        """Delete a file record. Returns True if deleted."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM file_registry
                WHERE repo_url = ? AND file_path = ?
            """, (repo_url, file_path))
            return cursor.rowcount > 0

    def get_all_files_for_repo(self, repo_url: str) -> list[FileRecord]:
        """Get all file records for a repository."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT repo_url, file_path, content_hash, last_commit, last_synced
                FROM file_registry
                WHERE repo_url = ?
            """, (repo_url,))
            
            return [
                FileRecord(
                    repo_url=row["repo_url"],
                    file_path=row["file_path"],
                    content_hash=row["content_hash"],
                    last_commit=row["last_commit"],
                    last_synced=datetime.fromisoformat(row["last_synced"]),
                )
                for row in cursor.fetchall()
            ]

    # =========================================================================
    # Symbol Registry Operations
    # =========================================================================

    def upsert_symbol(self, record: SymbolRecord) -> None:
        """Insert or update a symbol record."""
        with self._get_connection() as conn:
            conn.execute("""
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
                record.stable_symbol_key,
                record.chunk_hash,
                record.vector_id,
                record.last_commit,
                record.file_path,
                record.fully_qualified_name,
                record.chunk_type,
                record.repo_url,
            ))

    def get_symbol(self, stable_symbol_key: str) -> SymbolRecord | None:
        """Get a symbol record by stable key."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT stable_symbol_key, chunk_hash, vector_id, last_commit, 
                       file_path, fully_qualified_name, chunk_type, repo_url
                FROM symbol_registry
                WHERE stable_symbol_key = ?
            """, (stable_symbol_key,))
            
            row = cursor.fetchone()
            if row:
                return SymbolRecord(
                    stable_symbol_key=row["stable_symbol_key"],
                    chunk_hash=row["chunk_hash"],
                    vector_id=row["vector_id"],
                    last_commit=row["last_commit"],
                    file_path=row["file_path"],
                    fully_qualified_name=row["fully_qualified_name"] or "",
                    chunk_type=row["chunk_type"] or "",
                    repo_url=row["repo_url"],
                )
            return None

    def get_symbols_for_file(self, repo_url: str, file_path: str) -> list[SymbolRecord]:
        """Get all symbols for a specific file."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT stable_symbol_key, chunk_hash, vector_id, last_commit, 
                       file_path, fully_qualified_name, chunk_type, repo_url
                FROM symbol_registry
                WHERE repo_url = ? AND file_path = ?
            """, (repo_url, file_path))
            
            return [
                SymbolRecord(
                    stable_symbol_key=row["stable_symbol_key"],
                    chunk_hash=row["chunk_hash"],
                    vector_id=row["vector_id"],
                    last_commit=row["last_commit"],
                    file_path=row["file_path"],
                    fully_qualified_name=row["fully_qualified_name"] or "",
                    chunk_type=row["chunk_type"] or "",
                    repo_url=row["repo_url"],
                )
                for row in cursor.fetchall()
            ]

    def delete_symbol(self, stable_symbol_key: str) -> bool:
        """Delete a symbol record. Returns True if deleted."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM symbol_registry
                WHERE stable_symbol_key = ?
            """, (stable_symbol_key,))
            return cursor.rowcount > 0

    def delete_symbols_for_file(self, repo_url: str, file_path: str) -> int:
        """Delete all symbols for a file. Returns count of deleted records."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM symbol_registry
                WHERE repo_url = ? AND file_path = ?
            """, (repo_url, file_path))
            return cursor.rowcount

    def get_symbol_vector_id(self, stable_symbol_key: str) -> str | None:
        """Quick lookup of vector ID for a symbol."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT vector_id FROM symbol_registry
                WHERE stable_symbol_key = ?
            """, (stable_symbol_key,))
            row = cursor.fetchone()
            return row["vector_id"] if row else None

    # =========================================================================
    # Commit State Operations
    # =========================================================================

    def upsert_commit_state(self, state: CommitState) -> None:
        """Insert or update commit state for a repository."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO commit_state (repo_url, latest_commit_hash, synced_at)
                VALUES (?, ?, ?)
                ON CONFLICT(repo_url) DO UPDATE SET
                    latest_commit_hash = excluded.latest_commit_hash,
                    synced_at = excluded.synced_at
            """, (
                state.repo_url,
                state.latest_commit_hash,
                state.synced_at.isoformat(),
            ))

    def get_commit_state(self, repo_url: str) -> CommitState | None:
        """Get commit state for a repository."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT repo_url, latest_commit_hash, synced_at
                FROM commit_state
                WHERE repo_url = ?
            """, (repo_url,))
            
            row = cursor.fetchone()
            if row:
                return CommitState(
                    repo_url=row["repo_url"],
                    latest_commit_hash=row["latest_commit_hash"],
                    synced_at=datetime.fromisoformat(row["synced_at"]),
                )
            return None

    def get_cached_commit_hash(self, repo_url: str) -> str | None:
        """Quick lookup of cached commit hash."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT latest_commit_hash FROM commit_state
                WHERE repo_url = ?
            """, (repo_url,))
            row = cursor.fetchone()
            return row["latest_commit_hash"] if row else None

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def begin_transaction(self) -> sqlite3.Connection:
        """
        Begin a manual transaction for bulk operations.
        Call commit() or rollback() on the returned connection.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def clear_repo_data(self, repo_url: str) -> None:
        """Clear all cached data for a repository."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM file_registry WHERE repo_url = ?", (repo_url,))
            conn.execute("DELETE FROM symbol_registry WHERE repo_url = ?", (repo_url,))
            conn.execute("DELETE FROM commit_state WHERE repo_url = ?", (repo_url,))

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._get_connection() as conn:
            stats = {}
            
            cursor = conn.execute("SELECT COUNT(*) FROM file_registry")
            stats["file_count"] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM symbol_registry")
            stats["symbol_count"] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM commit_state")
            stats["repo_count"] = cursor.fetchone()[0]
            
            # Get database size
            cursor = conn.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor = conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            stats["db_size_bytes"] = page_count * page_size
            
            return stats

    def close(self) -> None:
        """Close any open connections (cleanup)."""
        # Connections are managed via context manager, so this is mainly for clarity
        pass
