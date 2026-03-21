"""
Read-only database layer for the evaluation dashboard.
Uses the same SQLite DB as the agent; no writes.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from eval_app.config import DATABASE_PATH

# Channel/user patterns that indicate local test (test_agent.py)
LOCAL_TEST_CHANNELS = {"", "C_LOCAL_TEST", "C99TESTCHAN"}
LOCAL_TEST_USER_PREFIX = "U_LOCAL_TEST"
LOCAL_TEST_CHANNEL_PREFIX = "C99"


def _is_local_test(channel_id: Optional[str], user_id: Optional[str]) -> bool:
    """Classify row as from local test (test_agent.py) vs Slack."""
    ch = (channel_id or "").strip()
    uid = (user_id or "").strip()
    if ch in LOCAL_TEST_CHANNELS:
        return True
    if uid == LOCAL_TEST_USER_PREFIX or uid.startswith(LOCAL_TEST_USER_PREFIX + "."):
        return True
    if ch.startswith(LOCAL_TEST_CHANNEL_PREFIX):
        return True
    return False


def _row_to_item(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert DB row to API item with computed source and parsed JSON fields."""
    d = dict(row)
    # Normalize types
    if d.get("needs_clarification") is not None:
        d["needs_clarification"] = bool(d["needs_clarification"])
    if d.get("escalated") is not None:
        d["escalated"] = bool(d["escalated"])
    if d.get("resolved") is not None:
        d["resolved"] = bool(d["resolved"])
    if d.get("created_at"):
        d["created_at"] = str(d["created_at"])
    d["source"] = "local_test" if _is_local_test(d.get("channel_id"), d.get("user_id")) else "slack"
    # Parse JSON fields for node-style display
    for key, out_key in [("retrieval_queries", "retrieval_queries_list"), ("retrieval_file_paths", "retrieval_file_paths_list")]:
        val = d.get(key)
        if val and isinstance(val, str):
            try:
                d[out_key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[out_key] = [val] if val.strip() else []
        else:
            d[out_key] = []
    return d


@contextmanager
def get_connection():
    """Context manager for read-only DB connection."""
    path = Path(DATABASE_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _status_condition(status: str) -> tuple[str, list]:
    """Return (SQL fragment, params) for status filter."""
    if status == "all":
        return "1=1", []
    if status == "resolved":
        return "resolved = 1", []
    if status == "escalated":
        return "escalated = 1", []
    if status == "needs_clarification":
        return "needs_clarification = 1", []
    if status == "no_response":
        return "(response_text IS NULL OR response_text = '')", []
    return "1=1", []


def list_conversations(
    sort: str = "created_at_desc",
    status: str = "all",
    source: str = "all",
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """
    List conversations with optional filters and sort.
    Returns (items, total_count).
    """
    status_sql, status_params = _status_condition(status)
    search_sql = ""
    search_params: list = []
    if q and q.strip():
        search_sql = " AND (user_query LIKE ? OR response_text LIKE ?)"
        term = f"%{q.strip()}%"
        search_params = [term, term]

    order = "created_at DESC" if sort == "created_at_desc" else "created_at ASC"
    base_sql = "FROM conversations WHERE " + status_sql + search_sql
    params = status_params + search_params

    # When filtering by source we must filter in Python (computed field), so fetch
    # a larger window, filter, then slice for the page.
    use_source_filter = source and source not in ("all", "")
    fetch_limit = limit + offset if not use_source_filter else 10000
    fetch_offset = 0 if not use_source_filter else 0

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id, message_ts, thread_ts, channel_id, user_id, user_query,
                   intent_type, response_text, ,
                   needs_clarification, escalated, escalation_reason,
                   docs_cited, reasoning_summary, processing_time,
                   created_at, resolved, resolved_at,
                   retrieval_queries, retrieval_file_paths
            {base_sql}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            params + [fetch_limit, fetch_offset],
        )
        rows = cursor.fetchall()

    items = [_row_to_item(r) for r in rows]

    if use_source_filter:
        items = [x for x in items if x.get("source") == source]
        total = len(items)
        items = items[offset : offset + limit]
    else:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) {base_sql}", params)
            total = cursor.fetchone()[0]

    return items, total


def get_conversation(conversation_id: int) -> Optional[Dict[str, Any]]:
    """Get a single conversation by id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, message_ts, thread_ts, channel_id, user_id, user_query,
                   intent_type, response_text, ,
                   needs_clarification, escalated, escalation_reason,
                   docs_cited, reasoning_summary, processing_time,
                   created_at, resolved, resolved_at,
                   retrieval_queries, retrieval_file_paths
            FROM conversations WHERE id = ?
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    return _row_to_item(row)


def get_node_outputs(message_ts: str) -> List[Dict[str, Any]]:
    """Return node output lineage for a conversation (ordered by step_order)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT node_name, step_order, output_json, created_at
                FROM node_outputs
                WHERE message_ts = ?
                ORDER BY step_order ASC
                """,
                (message_ts,),
            )
            rows = cursor.fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for row in rows:
        out.append({
            "node_name": row["node_name"],
            "step_order": row["step_order"],
            "output_json": json.loads(row["output_json"]) if row["output_json"] else {},
            "created_at": str(row["created_at"]) if row["created_at"] else None,
        })
    return out


def get_node_outputs_bulk(message_ts_list: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Return node outputs for multiple message_ts keys. Keys without any outputs get []."""
    if not message_ts_list:
        return {}
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(message_ts_list))
            cursor.execute(
                f"""
                SELECT message_ts, node_name, step_order, output_json, created_at
                FROM node_outputs
                WHERE message_ts IN ({placeholders})
                ORDER BY message_ts, step_order ASC
                """,
                message_ts_list,
            )
            rows = cursor.fetchall()
    except sqlite3.OperationalError:
        return {m: [] for m in message_ts_list}
    by_msg: Dict[str, List[Dict[str, Any]]] = {m: [] for m in message_ts_list}
    for row in rows:
        by_msg[row["message_ts"]].append({
            "node_name": row["node_name"],
            "step_order": row["step_order"],
            "output_json": json.loads(row["output_json"]) if row["output_json"] else {},
            "created_at": str(row["created_at"]) if row["created_at"] else None,
        })
    return by_msg


def get_stats(source: Optional[str] = None) -> Dict[str, Any]:
    """Get aggregate stats. If source is 'slack' or 'local_test', filter by computed source."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(*) as total_conversations,
                SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved_count,
                SUM(CASE WHEN escalated = 1 THEN 1 ELSE 0 END) as escalated_count,
                AVG() as avg_,
                AVG(processing_time) as avg_processing_time
            FROM conversations
        """)
        row = cursor.fetchone()
        stats = dict(row) if row else {}
        stats["total_conversations"] = stats.get("total_conversations") or 0
        stats["resolved_count"] = stats.get("resolved_count") or 0
        stats["escalated_count"] = stats.get("escalated_count") or 0
        stats["avg_"] = stats.get("avg_") or 0.0
        stats["avg_processing_time"] = stats.get("avg_processing_time") or 0.0

        cursor.execute("SELECT COUNT(DISTINCT user_id) as unique_users FROM conversations")
        row = cursor.fetchone()
        if row:
            stats["unique_users"] = row["unique_users"]
        else:
            stats["unique_users"] = 0

    # If filtering by source, we need to compute from all rows (no source column)
    if source and source in ("slack", "local_test"):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, channel_id, user_id, resolved, escalated, , processing_time
                FROM conversations
            """)
            rows = cursor.fetchall()
        filtered = [
            r for r in rows
            if _is_local_test(r["channel_id"], r["user_id"]) == (source == "local_test")
        ]
        n = len(filtered)
        resolved_count = sum(1 for r in filtered if r["resolved"])
        escalated_count = sum(1 for r in filtered if r["escalated"])
        confs = [r[""] for r in filtered if r[""] is not None]
        times = [r["processing_time"] for r in filtered if r["processing_time"] is not None]
        stats = {
            "total_conversations": n,
            "resolved_count": resolved_count or 0,
            "escalated_count": escalated_count or 0,
            "avg_": sum(confs) / len(confs) if confs else 0,
            "avg_processing_time": sum(times) / len(times) if times else 0,
            "unique_users": len(set(r["user_id"] for r in filtered)),
        }

    return stats
