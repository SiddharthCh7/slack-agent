"""
Team Resolver — loads olake-team.json and provides org-member detection,
Slack mention resolution, and smart escalation routing.

JSON format (v2 — key IS the slack_name, case-sensitive):
{
  "Engineering": {
    "shubham": { "role": "CTO", "desc": "..." },
    "Ankit Sharma": { "role": "Tech Lead", "desc": "..." }
  },
  "DevOps": { ... },
  "Product": { ... }
}

Slack name-to-ID cache is built at startup from users.list so that
@mentions resolve to <@USERID> (reliable pings, not just @name text).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File path
# ---------------------------------------------------------------------------

TEAM_FILE_PATH = Path(__file__).parent.parent / "olake-team.json"

# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

_team_data: Dict = {}           # raw JSON data
_all_members: List[Dict] = []   # flattened list of {slack_name, role, desc, dept}
_slack_name_to_id: Dict[str, str] = {}   # slack_name (case-sensitive) → Slack user ID
_bot_user_id: Optional[str] = None

# ---------------------------------------------------------------------------
# Department → escalation keywords
# ---------------------------------------------------------------------------

_DEPT_KEYWORDS: Dict[str, List[str]] = {
    "Engineering": [
        "bug", "error", "crash", "exception", "pipeline", "connector",
        "cdc", "wal", "replication", "slot", "binlog", "oplog",
        "performance", "slow", "timeout", "schema", "type", "arrow",
        "writer", "iceberg", "parquet", "s3", "gcs", "kafka",
        "race condition", "segfault", "docker", "kubernetes", "helm",
    ],
    "DevOps": [
        "devops", "infra", "deploy", "deployment", "ci/cd", "server",
        "vm", "ec2", "cloud", "network", "port", "firewall", "ssl",
        "certificate", "memory", "cpu", "disk", "storage",
    ],
    "Product": [
        "feature", "request", "roadmap", "ux", "ui", "dashboard",
        "suggestion", "feedback", "docs", "documentation", "pricing",
        "plan", "integration request",
    ],
}


# ---------------------------------------------------------------------------
# Startup functions
# ---------------------------------------------------------------------------

def load_team() -> Dict:
    """Load (or reload) team data from olake-team.json."""
    global _team_data, _all_members
    try:
        raw = json.loads(TEAM_FILE_PATH.read_text())
        _team_data = raw
        _all_members = []
        for dept, members in raw.items():
            for slack_name, info in members.items():
                _all_members.append({
                    "slack_name": slack_name,
                    "role": info.get("role", ""),
                    "desc": info.get("desc", ""),
                    "dept": dept,
                })
        log.info(f"Loaded {len(_all_members)} team members from {TEAM_FILE_PATH}")
        return raw
    except Exception as e:
        log.error(f"Failed to load {TEAM_FILE_PATH}: {e}")
        return {}


def build_name_to_id_cache(slack_users: List[Dict]) -> None:
    """
    Populate slack_name → user_id map from Slack's users.list response.

    Tries to match on display_name, real_name, and name (username)
    against each member's slack_name key (case-insensitive initial match,
    stored case-sensitively).
    """
    global _slack_name_to_id
    # Build reverse lookup from Slack: display_name/real_name → user_id
    name_to_id: Dict[str, str] = {}
    for u in slack_users:
        uid = u.get("id", "")
        profile = u.get("profile", {})
        for field in ("display_name", "real_name", "name"):
            val = (profile.get(field) or u.get(field) or "").strip()
            if val:
                name_to_id[val.lower()] = uid

    cache: Dict[str, str] = {}
    for member in _all_members:
        sn = member["slack_name"]
        uid = name_to_id.get(sn.lower())
        if uid:
            cache[sn] = uid
        else:
            log.warning(f"Could not resolve Slack user ID for slack_name='{sn}'")

    _slack_name_to_id = cache
    log.info(f"Resolved {len(cache)}/{len(_all_members)} team members to Slack IDs")


def set_bot_user_id(user_id: str) -> None:
    """Store the bot's own Slack user ID (from auth.test)."""
    global _bot_user_id
    _bot_user_id = user_id
    log.info(f"Bot user ID set to {user_id}")


def get_bot_user_id() -> Optional[str]:
    """Return the bot's own Slack user ID."""
    return _bot_user_id


# ---------------------------------------------------------------------------
# Querying helpers
# ---------------------------------------------------------------------------

def get_all_slack_names() -> Set[str]:
    """Return set of all team slack_name values (case-sensitive keys)."""
    return {m["slack_name"] for m in _all_members}


def get_all_members_flat() -> List[Dict]:
    """Return flattened list of all team members."""
    if not _all_members:
        load_team()
    return list(_all_members)


def is_org_member_by_name(display_name: str) -> bool:
    """
    True if display_name matches any team member's slack_name (case-insensitive).
    Used as a fallback when user_id is unavailable.
    """
    if not _all_members:
        load_team()
    dn_lower = display_name.strip().lower()
    return any(m["slack_name"].lower() == dn_lower for m in _all_members)


def is_org_member_by_id(user_id: str) -> bool:
    """True if user_id matches any resolved Slack user ID in the team cache."""
    return bool(user_id) and user_id in _slack_name_to_id.values()


def resolve_mention(slack_name: str) -> str:
    """
    Return '<@USERID>' if slack_name is in the cache, else '@slack_name'.
    Always falls back gracefully so escalation messages never break.
    """
    uid = _slack_name_to_id.get(slack_name)
    return f"<@{uid}>" if uid else f"@{slack_name}"


# ---------------------------------------------------------------------------
# Escalation routing
# ---------------------------------------------------------------------------

def get_escalation_targets(
    issue_text: str = "",
    dept_override: Optional[str] = None,
) -> List[Dict]:
    """
    Determine which team members to escalate to.

    Priority:
    1. dept_override if provided and valid
    2. Keyword matching against _DEPT_KEYWORDS
    3. Fallback: Engineering department
    """
    if not _all_members:
        load_team()

    # Use override if valid
    if dept_override and dept_override in _team_data:
        return [m for m in _all_members if m["dept"] == dept_override]

    # Keyword matching
    text_lower = issue_text.lower()
    dept_scores: Dict[str, int] = {d: 0 for d in _team_data}
    for dept, keywords in _DEPT_KEYWORDS.items():
        if dept not in dept_scores:
            dept_scores[dept] = 0
        for kw in keywords:
            if kw in text_lower:
                dept_scores[dept] += 1

    best_dept = max(dept_scores, key=dept_scores.__getitem__)

    # If no keyword matched, fallback to Engineering
    if dept_scores[best_dept] == 0:
        best_dept = "Engineering"

    return [m for m in _all_members if m["dept"] == best_dept]


def format_escalation_message(
    targets: List[Dict],
    issue_summary: str = "",
) -> str:
    """
    Build the in-thread escalation message with proper @mentions.
    """
    if not targets:
        return "Flagging this for the OLake team — someone will assist shortly."

    mention_parts = []
    for t in targets:
        mention = resolve_mention(t["slack_name"])
        role_hint = f"_{t.get('desc', t.get('role', ''))}_ " if t.get("desc") else ""
        mention_parts.append(f"{mention}\n{role_hint}")

    header = f"Flagging this for the team — {' '.join(m for m in [resolve_mention(t['slack_name']) for t in targets])}"

    lines = [header]
    for t in targets:
        desc = t.get("desc", t.get("role", ""))
        if desc:
            lines.append(f"_{desc}_")

    if issue_summary:
        lines.append(f"\n*Issue:* {issue_summary[:200]}")

    return "\n".join(lines)
