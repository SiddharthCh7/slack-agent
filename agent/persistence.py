"""
Database persistence for OLake Slack Community Agent.

Normalized schema:
  users            — one row per Slack user
  threads          — one row per Slack thread (or top-level message)
  messages         — one row per message; role = 'user' | 'agent'
  thread_summaries — running summary + summarised_through_ts cutoff per thread
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager

from agent.logger import get_logger


class Database:
    """SQLite database for agent persistence."""

    def __init__(self, db_path: str = "data/slack_agent.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger()
        self._init_database()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Create normalized schema (idempotent)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id      TEXT PRIMARY KEY,
                    username     TEXT,
                    display_name TEXT,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id  TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id  TEXT NOT NULL REFERENCES threads(thread_id),
                    user_id    TEXT REFERENCES users(user_id),
                    role       TEXT NOT NULL CHECK(role IN ('user', 'agent')),
                    content    TEXT NOT NULL,
                    message_ts TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_thread
                ON messages(thread_id, message_ts ASC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user
                ON messages(user_id, message_ts DESC)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thread_summaries (
                    thread_id              TEXT PRIMARY KEY REFERENCES threads(thread_id),
                    summary                TEXT NOT NULL,
                    summarised_through_ts  TEXT NOT NULL,
                    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self.logger.logger.debug("Persistence database (SQLite) ready")

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def upsert_user(
        self,
        user_id: str,
        username: str = "",
        display_name: str = "",
    ) -> None:
        """Insert or update a user record; always touches last_seen_at."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, username, display_name, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username     = excluded.username,
                    display_name = excluded.display_name,
                    last_seen_at = CURRENT_TIMESTAMP
            """, (user_id, username, display_name))

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def upsert_thread(self, thread_id: str, channel_id: str) -> None:
        """Insert or update a thread record; always touches updated_at."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO threads (thread_id, channel_id, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
            """, (thread_id, channel_id))

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def save_message(
        self,
        thread_id: str,
        user_id: Optional[str],
        role: str,
        content: str,
        message_ts: str,
    ) -> None:
        """Insert a single message row. Silently ignores duplicate message_ts."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO messages
                    (thread_id, user_id, role, content, message_ts)
                VALUES (?, ?, ?, ?, ?)
            """, (thread_id, user_id, role, content, message_ts))

    def get_thread_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return messages for a thread in chronological order (ASC by message_ts).
        When limit is given, returns the last `limit` messages.
        """
        with self.get_connection() as conn:
            if limit:
                rows = conn.execute("""
                    SELECT * FROM (
                        SELECT id, thread_id, user_id, role, content, message_ts, created_at
                        FROM messages
                        WHERE thread_id = ?
                        ORDER BY message_ts DESC
                        LIMIT ?
                    ) ORDER BY message_ts ASC
                """, (thread_id, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, thread_id, user_id, role, content, message_ts, created_at
                    FROM messages
                    WHERE thread_id = ?
                    ORDER BY message_ts ASC
                """, (thread_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_thread_messages_after(
        self,
        thread_id: str,
        after_ts: str,
    ) -> List[Dict[str, Any]]:
        """
        Return messages for a thread with message_ts > after_ts, ASC.
        Pass after_ts="" or "0" to get all messages (when no prior summary exists).
        """
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT id, thread_id, user_id, role, content, message_ts, created_at
                FROM messages
                WHERE thread_id = ? AND message_ts > ?
                ORDER BY message_ts ASC
            """, (thread_id, after_ts)).fetchall()
        return [dict(r) for r in rows]

    def get_user_messages(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return all messages by a user across all threads, most recent first."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT id, thread_id, user_id, role, content, message_ts, created_at
                FROM messages
                WHERE user_id = ?
                ORDER BY message_ts DESC
                LIMIT ?
            """, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Thread summaries
    # ------------------------------------------------------------------

    def get_thread_summary(self, thread_id: str) -> Tuple[Optional[str], str]:
        """
        Return (summary_text, summarised_through_ts).
        If no row exists, returns (None, "").
        """
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT summary, summarised_through_ts
                FROM thread_summaries
                WHERE thread_id = ?
            """, (thread_id,)).fetchone()
        if row:
            return row["summary"], row["summarised_through_ts"]
        return None, ""

    def upsert_thread_summary(
        self,
        thread_id: str,
        summary: str,
        summarised_through_ts: str,
    ) -> None:
        """Insert or overwrite the summary for a thread."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO thread_summaries
                    (thread_id, summary, summarised_through_ts, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    summary               = excluded.summary,
                    summarised_through_ts = excluded.summarised_through_ts,
                    updated_at            = CURRENT_TIMESTAMP
            """, (thread_id, summary, summarised_through_ts))


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_db: Optional[Database] = None


def get_database(db_path: Optional[str] = None) -> Database:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        from agent.config import Config
        _db = Database(db_path=db_path or Config.DATABASE_PATH)
    return _db
