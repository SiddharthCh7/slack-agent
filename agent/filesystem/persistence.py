"""
Database persistence for OLake Slack Community Agent.

Supports:
  - SQLite (default): file at DATABASE_PATH — local dev
  - PostgreSQL: DATABASE_URL — hosted or Docker (e.g. compose service)

Normalized schema:
  users            — one row per Slack user
  threads          — one row per Slack thread (or top-level message)
  messages         — one row per message; role = 'user' | 'agent'
  thread_summaries — running summary + summarised_through_ts cutoff per thread
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import urlparse

from agent.utils.logger import get_logger

Backend = Literal["sqlite", "postgres"]


def _postgres_dsn_from_url(url: str) -> str:
    """Normalize connection string for psycopg (accepts postgresql:// or postgres://)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError(
            f"DATABASE_URL must use postgresql:// or postgres:// scheme, got {parsed.scheme!r}"
        )
    return url


class Database:
    """
    Persistence backend: SQLite file or PostgreSQL (hosted / Docker).

    Use DATABASE_URL=postgresql://user:pass@host:5432/dbname for Postgres.
    If unset, uses SQLite at DATABASE_PATH.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        database_url: Optional[str] = None,
    ) -> None:
        self.logger = get_logger()

        url = (database_url or "").strip()
        if url:
            self._backend: Backend = "postgres"
            self._dsn = _postgres_dsn_from_url(url)
            self.db_path: Optional[Path] = None
        else:
            self._backend = "sqlite"
            self._dsn = ""
            path = db_path or "data/slack_agent.db"
            self.db_path = Path(path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_database()

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    @contextmanager
    def get_connection(self):
        if self._backend == "sqlite":
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            import psycopg
            from psycopg import Connection

            conn: Connection = psycopg.connect(self._dsn)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def check_connection(self) -> None:
        """
        Verify the database is reachable and accepting queries.

        Raises:
            RuntimeError: with a human-readable message if the connection fails.
        """
        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                if self._backend == "postgres":
                    cur.execute("SELECT 1")
                else:
                    cur.execute("SELECT 1")
        except Exception as exc:
            if self._backend == "postgres":
                from urllib.parse import urlparse
                parsed = urlparse(self._dsn)
                target = f"{parsed.hostname}:{parsed.port or 5432}/{(parsed.path or '').lstrip('/')}"
                raise RuntimeError(
                    f"Cannot connect to PostgreSQL at {target!r}: {exc}\n"
                    "Check that the database is running and DATABASE_URL is correct."
                ) from exc
            else:
                raise RuntimeError(
                    f"Cannot open SQLite database at {self.db_path!r}: {exc}"
                ) from exc

    def _init_database(self) -> None:
        """Create normalized schema (idempotent)."""
        if self._backend == "sqlite":
            self._init_sqlite_schema()
        else:
            self._init_postgres_schema()

    def _init_sqlite_schema(self) -> None:
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

    def _init_postgres_schema(self) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id      TEXT PRIMARY KEY,
                        username     TEXT,
                        display_name TEXT,
                        first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_seen_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS threads (
                        thread_id  TEXT PRIMARY KEY,
                        channel_id TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # No FKs on messages — matches SQLite default (PRAGMA foreign_keys off), so callers
                # need not upsert threads/users before save_message (see solution_provider).
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id         BIGSERIAL PRIMARY KEY,
                        thread_id  TEXT NOT NULL,
                        user_id    TEXT,
                        role       TEXT NOT NULL CHECK(role IN ('user', 'agent')),
                        content    TEXT NOT NULL,
                        message_ts TEXT NOT NULL UNIQUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_thread
                    ON messages(thread_id, message_ts ASC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_messages_user
                    ON messages(user_id, message_ts DESC)
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS thread_summaries (
                        thread_id              TEXT PRIMARY KEY,
                        summary                TEXT NOT NULL,
                        summarised_through_ts  TEXT NOT NULL,
                        updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
        self.logger.logger.debug("Persistence database (PostgreSQL) ready")

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
        sql = """
                INSERT INTO users (user_id, username, display_name, first_seen_at, last_seen_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username     = EXCLUDED.username,
                    display_name = EXCLUDED.display_name,
                    last_seen_at = CURRENT_TIMESTAMP
            """
        if self._backend == "sqlite":
            sql = sql.replace("%s", "?").replace("EXCLUDED", "excluded")
        with self.get_connection() as conn:
            if self._backend == "sqlite":
                conn.execute(sql, (user_id, username, display_name))
            else:
                with conn.cursor() as cur:
                    cur.execute(sql, (user_id, username, display_name))

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def upsert_thread(self, thread_id: str, channel_id: str) -> None:
        """Insert or update a thread record; always touches updated_at."""
        sql = """
                INSERT INTO threads (thread_id, channel_id, created_at, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP
            """
        if self._backend == "sqlite":
            sql = sql.replace("%s", "?")
        with self.get_connection() as conn:
            if self._backend == "sqlite":
                conn.execute(sql, (thread_id, channel_id))
            else:
                with conn.cursor() as cur:
                    cur.execute(sql, (thread_id, channel_id))

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
        if self._backend == "sqlite":
            sql = """
                INSERT OR IGNORE INTO messages
                    (thread_id, user_id, role, content, message_ts)
                VALUES (?, ?, ?, ?, ?)
            """
            with self.get_connection() as conn:
                conn.execute(sql, (thread_id, user_id, role, content, message_ts))
        else:
            sql = """
                INSERT INTO messages
                    (thread_id, user_id, role, content, message_ts)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (message_ts) DO NOTHING
            """
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (thread_id, user_id, role, content, message_ts))

    def get_thread_messages(
        self,
        thread_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return messages for a thread in chronological order (ASC by message_ts).
        When limit is given, returns the last `limit` messages.
        """
        if self._backend == "sqlite":
            with self.get_connection() as conn:
                if limit:
                    rows = conn.execute(
                        """
                        SELECT * FROM (
                            SELECT id, thread_id, user_id, role, content, message_ts, created_at
                            FROM messages
                            WHERE thread_id = ?
                            ORDER BY message_ts DESC
                            LIMIT ?
                        ) AS t ORDER BY message_ts ASC
                        """,
                        (thread_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, thread_id, user_id, role, content, message_ts, created_at
                        FROM messages
                        WHERE thread_id = ?
                        ORDER BY message_ts ASC
                        """,
                        (thread_id,),
                    ).fetchall()
            return [dict(r) for r in rows]

        from psycopg.rows import dict_row

        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if limit:
                    cur.execute(
                        """
                        SELECT * FROM (
                            SELECT id, thread_id, user_id, role, content, message_ts, created_at
                            FROM messages
                            WHERE thread_id = %s
                            ORDER BY message_ts DESC
                            LIMIT %s
                        ) AS t ORDER BY message_ts ASC
                        """,
                        (thread_id, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, thread_id, user_id, role, content, message_ts, created_at
                        FROM messages
                        WHERE thread_id = %s
                        ORDER BY message_ts ASC
                        """,
                        (thread_id,),
                    )
                rows = cur.fetchall()
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
        if self._backend == "sqlite":
            with self.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, thread_id, user_id, role, content, message_ts, created_at
                    FROM messages
                    WHERE thread_id = ? AND message_ts > ?
                    ORDER BY message_ts ASC
                    """,
                    (thread_id, after_ts),
                ).fetchall()
            return [dict(r) for r in rows]

        from psycopg.rows import dict_row

        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, thread_id, user_id, role, content, message_ts, created_at
                    FROM messages
                    WHERE thread_id = %s AND message_ts > %s
                    ORDER BY message_ts ASC
                    """,
                    (thread_id, after_ts),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_user_messages(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return all messages by a user across all threads, most recent first."""
        if self._backend == "sqlite":
            with self.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, thread_id, user_id, role, content, message_ts, created_at
                    FROM messages
                    WHERE user_id = ?
                    ORDER BY message_ts DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

        from psycopg.rows import dict_row

        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, thread_id, user_id, role, content, message_ts, created_at
                    FROM messages
                    WHERE user_id = %s
                    ORDER BY message_ts DESC
                    LIMIT %s
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Thread summaries
    # ------------------------------------------------------------------

    def get_thread_summary(self, thread_id: str) -> Tuple[Optional[str], str]:
        """
        Return (summary_text, summarised_through_ts).
        If no row exists, returns (None, "").
        """
        if self._backend == "sqlite":
            with self.get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT summary, summarised_through_ts
                    FROM thread_summaries
                    WHERE thread_id = ?
                    """,
                    (thread_id,),
                ).fetchone()
            if row:
                return row["summary"], row["summarised_through_ts"]
            return None, ""

        from psycopg.rows import dict_row

        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT summary, summarised_through_ts
                    FROM thread_summaries
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                row = cur.fetchone()
        if row:
            d = dict(row)
            return d["summary"], d["summarised_through_ts"]
        return None, ""

    def upsert_thread_summary(
        self,
        thread_id: str,
        summary: str,
        summarised_through_ts: str,
    ) -> None:
        """Insert or overwrite the summary for a thread."""
        sql = """
                INSERT INTO thread_summaries
                    (thread_id, summary, summarised_through_ts, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(thread_id) DO UPDATE SET
                    summary               = EXCLUDED.summary,
                    summarised_through_ts = EXCLUDED.summarised_through_ts,
                    updated_at            = CURRENT_TIMESTAMP
            """
        if self._backend == "sqlite":
            sql = sql.replace("%s", "?").replace("EXCLUDED", "excluded")
        with self.get_connection() as conn:
            if self._backend == "sqlite":
                conn.execute(sql, (thread_id, summary, summarised_through_ts))
            else:
                with conn.cursor() as cur:
                    cur.execute(sql, (thread_id, summary, summarised_through_ts))


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_db: Optional[Database] = None


def get_database(
    db_path: Optional[str] = None,
    database_url: Optional[str] = None,
) -> Database:
    """
    Get or create the global database instance.

    Backend selection:
      - If ``database_url`` is passed, or ``Config.DATABASE_URL`` is set → PostgreSQL
      - Else SQLite at ``db_path`` or ``Config.DATABASE_PATH``
    """
    global _db
    if _db is None:
        from agent.config import Config

        url = (database_url if database_url is not None else Config.DATABASE_URL) or ""
        url = url.strip()
        if url:
            _db = Database(database_url=url)
        else:
            _db = Database(db_path=db_path or Config.DATABASE_PATH)
    return _db
