"""
Read-only database layer for the evaluation dashboard.

Reads the same database as the agent (SQLite or PostgreSQL) using the shared
persistence backend. No writes are performed here.

Schema used (from agent/filesystem/persistence.py):
  threads          — thread_id, channel_id, created_at, updated_at
  messages         — id, thread_id, user_id, role, content, message_ts, created_at
  thread_summaries — thread_id, summary, summarised_through_ts, updated_at
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from agent.filesystem.persistence import get_database

# Channel/user patterns that indicate a local test run (test_agent.py)
_LOCAL_TEST_CHANNELS = {"", "C_LOCAL_TEST", "C99TESTCHAN"}
_LOCAL_TEST_USER_PREFIX = "U_LOCAL_TEST"
_LOCAL_TEST_CHANNEL_PREFIX = "C99"


def _source_of(channel_id: Optional[str], user_id: Optional[str]) -> str:
    ch = (channel_id or "").strip()
    uid = (user_id or "").strip()
    if (
        ch in _LOCAL_TEST_CHANNELS
        or ch.startswith(_LOCAL_TEST_CHANNEL_PREFIX)
        or uid == _LOCAL_TEST_USER_PREFIX
        or uid.startswith(_LOCAL_TEST_USER_PREFIX + ".")
    ):
        return "local_test"
    return "slack"


def _enrich(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add computed fields to a raw DB row."""
    row["source"] = _source_of(row.get("channel_id"), row.get("user_id"))
    if row.get("created_at"):
        row["created_at"] = str(row["created_at"])
    return row


# ---------------------------------------------------------------------------
# Thread / conversation listing
# ---------------------------------------------------------------------------

def list_conversations(
    sort: str = "created_at_desc",
    status: str = "all",
    source: str = "all",
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    List threads with their most-recent user question and agent reply.
    Returns (items, total_count).

    Each item contains:
      thread_id, channel_id, created_at, updated_at,
      user_query (last user message), response_text (last agent reply),
      user_id, message_ts, source
    """
    db = get_database()

    # Fetch all threads (lightweight — threads table has no large text)
    threads = db.get_connection.__self__  # type: ignore[attr-defined]

    # We'll do the aggregation manually so it works on both SQLite and PG.
    # Load threads, then lazily fetch the relevant messages.
    raw_threads = _fetch_threads(db)

    # Attach user_query and response_text from messages
    items: List[Dict[str, Any]] = []
    for t in raw_threads:
        msgs = db.get_thread_messages(t["thread_id"])
        user_msgs = [m for m in msgs if m["role"] == "user"]
        agent_msgs = [m for m in msgs if m["role"] == "agent"]

        last_user = user_msgs[-1] if user_msgs else {}
        last_agent = agent_msgs[-1] if agent_msgs else {}

        item: Dict[str, Any] = {
            "thread_id": t["thread_id"],
            "channel_id": t.get("channel_id", ""),
            "created_at": str(t.get("created_at", "")),
            "updated_at": str(t.get("updated_at", "")),
            "message_ts": last_user.get("message_ts", t["thread_id"]),
            "user_id": last_user.get("user_id"),
            "user_query": last_user.get("content", ""),
            "response_text": last_agent.get("content", ""),
            "message_count": len(msgs),
        }
        items.append(_enrich(item))

    # Filter
    if source and source not in ("all", ""):
        items = [x for x in items if x["source"] == source]

    if q and q.strip():
        term = q.strip().lower()
        items = [
            x for x in items
            if term in (x.get("user_query") or "").lower()
            or term in (x.get("response_text") or "").lower()
        ]

    total = len(items)

    # Sort
    reverse = sort != "created_at_asc"
    items.sort(key=lambda x: x.get("created_at", ""), reverse=reverse)

    # Paginate
    items = items[offset: offset + limit]

    return items, total


def _fetch_threads(db) -> List[Dict[str, Any]]:
    """Return all threads ordered by updated_at DESC."""
    if db._backend == "sqlite":
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT thread_id, channel_id, created_at, updated_at "
                "FROM threads ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    else:
        from psycopg.rows import dict_row
        with db.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT thread_id, channel_id, created_at, updated_at "
                    "FROM threads ORDER BY updated_at DESC"
                )
                return [dict(r) for r in cur.fetchall()]


def get_conversation(thread_id: str) -> Optional[Dict[str, Any]]:
    """Get a single conversation (thread + messages) by thread_id."""
    db = get_database()
    msgs = db.get_thread_messages(thread_id)
    if not msgs:
        return None

    user_msgs = [m for m in msgs if m["role"] == "user"]
    agent_msgs = [m for m in msgs if m["role"] == "agent"]
    last_user = user_msgs[-1] if user_msgs else {}
    last_agent = agent_msgs[-1] if agent_msgs else {}

    summary_text, _ = db.get_thread_summary(thread_id)

    item: Dict[str, Any] = {
        "thread_id": thread_id,
        "channel_id": msgs[0].get("channel_id", ""),
        "created_at": str(msgs[0].get("created_at", "")),
        "message_ts": last_user.get("message_ts", thread_id),
        "user_id": last_user.get("user_id"),
        "user_query": last_user.get("content", ""),
        "response_text": last_agent.get("content", ""),
        "summary": summary_text or "",
        "messages": msgs,
        "message_count": len(msgs),
    }
    return _enrich(item)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(source: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate statistics over the messages table."""
    db = get_database()

    if db._backend == "sqlite":
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT thread_id) as total_threads, "
                "COUNT(*) as total_messages, "
                "COUNT(DISTINCT user_id) as unique_users "
                "FROM messages"
            ).fetchone()
            stats = dict(row) if row else {}

            agent_row = conn.execute(
                "SELECT COUNT(*) as agent_messages FROM messages WHERE role='agent'"
            ).fetchone()
            stats["agent_messages"] = dict(agent_row)["agent_messages"] if agent_row else 0
    else:
        from psycopg.rows import dict_row
        with db.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT COUNT(DISTINCT thread_id) as total_threads, "
                    "COUNT(*) as total_messages, "
                    "COUNT(DISTINCT user_id) as unique_users "
                    "FROM messages"
                )
                stats = dict(cur.fetchone() or {})
                cur.execute(
                    "SELECT COUNT(*) as agent_messages FROM messages WHERE role='agent'"
                )
                row = cur.fetchone()
                stats["agent_messages"] = dict(row)["agent_messages"] if row else 0

    return {
        "total_threads": stats.get("total_threads") or 0,
        "total_messages": stats.get("total_messages") or 0,
        "agent_messages": stats.get("agent_messages") or 0,
        "unique_users": stats.get("unique_users") or 0,
    }


# ---------------------------------------------------------------------------
# Node output stubs (kept for template compatibility — no node_outputs table)
# ---------------------------------------------------------------------------

def get_node_outputs(message_ts: str) -> List[Dict[str, Any]]:
    return []


def get_node_outputs_bulk(message_ts_list: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    return {m: [] for m in message_ts_list}
