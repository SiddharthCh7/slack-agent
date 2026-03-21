"""
Deep Researcher Node.

Alex plans a sequence of tool actions each iteration:
  - search_code
  - find_files_with_symbol
  - find_definitions
  - read_file

Search history explicitly records both positive and zero-result actions so the planner
can avoid repeating dead-end searches in later iterations.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from agent.codebase_search import (
    RgSearchError,
    SearchHit,
    search_code,
    find_files_with_symbol,
    find_definitions,
    read_file,
)
from agent.config import ABOUT_OLAKE, ABOUT_OLAKE_REPO_INFO
from agent.llm import get_chat_completion
from agent.logger import get_logger
from agent.state import ConversationState, ResearchFile
from agent.utils.parser import parse_planner_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stuck-detector and reflection constants
# ---------------------------------------------------------------------------

# Inject a SYSTEM NOTE into the next iteration when the same pattern is seen this many times.
_SAME_PATTERN_WARN_THRESHOLD = 2
# Force actions=[] (immediate hand-off) when the same pattern is seen this many times.
_SAME_PATTERN_FORCE_PIVOT = 3
# Inject a SYSTEM NOTE after this many consecutive iterations that added zero new files.
_ZERO_NEW_FILES_INJECT_THRESHOLD = 3
# Force exit (hand-off) after this many consecutive zero-gain iterations.
_ZERO_NEW_FILES_FORCE_EXIT = 5
# Fire the metacognitive reflection LLM call after this many consecutive zero-gain iterations.
_REFLECTION_AFTER_ITERS = 3
# Compact raw history entries older than the last window into a single summary block.
_HISTORY_COMPACT_INTERVAL = 4

# ---------------------------------------------------------------------------
# System prompt (static — describes the agent role and tool contract only)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are Alex, a senior support engineer at OLake/Datazip. Think and reason explicitly \
in first person: use "I" in your reasoning (e.g. "I need to search for ...", \
"I will look for ...", "I should target ...").

About OLake:
{about_olake}

Repositories available for search:
{about_olake_repo_info}

Your job: Research the OLake codebase to find the information needed to answer the \
user's question. There is NO vector search and NO semantic search.

TOOLS YOU CAN CALL:
1) search_code(pattern, path, file_type=None, context_lines=15)
   - Regex/code search with line numbers and context snippets.
   - Use this first for broad discovery.
   - path="all" searches ALL cloned repos at once. Use this by default unless you \
already know which specific repo contains the answer.
2) find_files_with_symbol(symbol, path)
   - Cheap symbol-to-files lookup (returns file paths only).
   - Supports path="all".
3) find_definitions(symbol, path, lang)
   - Find likely declarations/definitions for a symbol.
   - Supports path="all".
4) read_file(path, start_line=None, end_line=None)
   - Read a bounded line range from a specific file.
   - If you already have a file+line hit from search_code, use read_file next.

GO/OLAKE NAMING — CRITICAL: OLake is written in Go. Use PascalCase for exported \
identifiers (ExpireSnapshot) and camelCase for unexported (expireSnapshot). \
Never use Python-style snake_case — it will NOT match.

PATTERN QUALITY RULES:
- Default to path="all" for error strings, config keys, docs, or anything cross-cutting. \
  Use a named repo (e.g. "olake", "olake-docs") only when you already have a reason to narrow down.
- Compound terms over single words: "topic.*retention" not "retention"
- One regex covering all related variants beats multiple narrow searches
- Use SEARCH HISTORY to avoid repeating searches that already returned useful results

ERROR STRING SEARCH PROTOCOL:
When the user reports a CLI/runtime error message:
1. Search for it once with path="all". If it returns 0 results: this is DEFINITIVE EVIDENCE \
the string is runtime-generated (e.g. fmt.Sprintf("... %%s", name)), docs-only, or from a \
dependency. Do NOT retry the same string.
2. Immediately pivot to searching for PARTIAL TOKENS and Go identifiers related to the feature: \
struct field names, function names, config keys, doc file paths for the relevant writer/format.
3. Reason through this hypothesis list explicitly in your "thinking":
   a. String assembled at runtime in Go source (most common)
   b. String exists only in olake-docs / website
   c. String comes from a third-party library
   d. Feature is version-gated or behind a flag

STOPPING RULE — READ THIS CAREFULLY:
Once you have confirmed the user's error string is not in the codebase (0-result search \
across all repos), STOP searching for it and return actions: [] immediately. \
Write in your "thinking": "String not found in codebase. Handing off with bounded answer." \
The solution provider will produce a practical answer from docs and product knowledge. \
Do NOT wait until the iteration limit — stop as soon as you have enough signal.

CRITICAL — OUTPUT RULES:
1. Your ENTIRE response must be a single JSON object. No prose, no preamble, no explanation \
before or after the JSON. Start your response with {{ and end with }}.
2. Do NOT write "I need to..." or any natural language before the JSON.
3. Put ALL your reasoning inside the "thinking" field.

OUTPUT FORMAT (valid JSON only — nothing else):
{{
  "thinking": "First-person reasoning: what I know so far and what gap I'm filling.",
  "search_intent": "One or two lines: what I am searching and why.",
  "actions": [
    {{
      "tool": "search_code",
      "pattern": "LSN.*not.*updated|post.*cdc.*error",
      "path": "all",
      "file_type": "go",
      "context_lines": 3
    }},
    {{
      "tool": "read_file",
      "path": "olake/pkg/waljs/replicator.go",
      "start_line": 150,
      "end_line": 210
    }}
  ],
  "is_conceptual": false
}}

RULES:
- search_intent is REQUIRED every time.
- Max 6 actions per iteration.
- Prefer search_code first, then read_file on promising files.
- Return empty actions [] when you have enough information to answer accurately.
- Set is_conceptual true only for general-knowledge questions that need no code search; \
  leave actions empty in that case.\
"""


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        about_olake=(ABOUT_OLAKE or "").strip(),
        about_olake_repo_info=(ABOUT_OLAKE_REPO_INFO or "").strip(),
    )


# ---------------------------------------------------------------------------
# User message (dynamic — rebuilt each iteration with current context)
# ---------------------------------------------------------------------------

def _format_thread_context(thread_context: List[Dict[str, Any]]) -> str:
    """Render [{role, content, message_ts}] as a readable transcript."""
    if not thread_context:
        return "(none)"
    lines: List[str] = []
    for msg in thread_context:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        label = "User" if role == "user" else "Agent"
        lines.append(f"{label}: {content}")
    return "\n".join(lines) if lines else "(none)"


def _format_search_history(entries: List[str]) -> str:
    if not entries:
        return "(none — this is the first search iteration)"
    return "\n\n".join(entries)


def _build_user_message(
    user_query: str,
    thread_summary: Optional[str],
    thread_context: List[Dict[str, Any]],
    search_history_entries: List[str],
    conclusions_log: Optional[List[str]] = None,
    system_note: Optional[str] = None,
) -> str:
    summary_block = (thread_summary or "").strip() or "(none — no prior conversation summary)"
    context_block = _format_thread_context(thread_context)
    history_block = _format_search_history(search_history_entries)

    conclusions_block = ""
    if conclusions_log:
        # Most-recent-first, capped at 8, so the freshest findings are at the top.
        recent = list(reversed(conclusions_log[-8:]))
        bullet_lines = "\n".join(f"- {c}" for c in recent)
        conclusions_block = f"\n---\nWHAT I HAVE CONCLUDED SO FAR (most recent first):\n{bullet_lines}\n"

    note_block = ""
    if system_note:
        note_block = f"\n---\nSYSTEM NOTE: {system_note}\n"

    return f"""\
USER QUESTION:
{user_query}

---
CONVERSATION CONTEXT:

Prior conversation summary (older turns, already compressed):
{summary_block}

Recent messages in this thread (not yet in summary):
{context_block}
{conclusions_block}
---
SEARCH HISTORY (what you've searched and found so far this session — compact):
{history_block}
{note_block}
---
Based on the above, decide what to search next.
Return empty actions [] if you already have enough to answer accurately.\
"""


_COMPACT_HISTORY_SYSTEM = """\
You are a compact summariser for a codebase research session.
Given a list of search iterations, produce a tight bullet-point summary that preserves:
- Every pattern/symbol that was searched (with hit count or "0 results")
- Every file that was found (file path only, one per line)
- Any facts definitively established (e.g. "string not found in codebase — likely runtime-assembled")

Output ONLY the bullet list. No headings, no preamble, no JSON.
Keep the total output under 40 lines. Be concise — omit repeated findings.
"""


async def _compact_history(entries: List[str], user_query: str) -> str:
    """Collapse a list of raw history entries into a compact bullet summary via LLM."""
    joined = "\n\n".join(entries)
    user_msg = f"USER QUESTION: {user_query}\n\nSEARCH ITERATIONS TO SUMMARISE:\n{joined}"
    try:
        print(f"(DeepResearcher: _compact_history) Input characters count: {len(user_msg) + len(_COMPACT_HISTORY_SYSTEM)}")
        summary = await get_chat_completion(
            messages=[
                {"role": "system", "content": _COMPACT_HISTORY_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
        )
        return f"[Compacted summary — {len(entries)} iteration(s)]\n{(summary or '').strip()}"
    except Exception as exc:
        log.warning("[DeepResearcher] history compaction failed: %s", exc)
        return "\n\n".join(entries)  # fall back to raw on failure


_REFLECTION_SYSTEM = """\
You are a search strategist reviewing a failed research session.
Your ENTIRE response must be a single JSON object with exactly two keys:
  "diagnosis": one sentence explaining why the searches above failed to find the answer.
  "actions": a JSON array of 0-3 new search actions using the same schema as the main planner \
(tool, pattern/symbol, path, file_type, context_lines). Use path="all" unless you have a \
specific reason. Return an empty array [] if you believe no more searching will help.

Start your response with {{ and end with }}. No prose before or after.
"""


def _build_reflection_message(user_query: str, search_history_entries: List[str]) -> str:
    history_block = _format_search_history(search_history_entries)
    return f"""\
USER QUESTION:
{user_query}

SEARCHES PERFORMED SO FAR:
{history_block}

Given the searches above and their results, diagnose in one sentence why they failed \
to find useful code. Then propose 1-3 actions that take a fundamentally different approach, \
or return [] if no further searching is warranted.\
"""


# ---------------------------------------------------------------------------
# Search history entry formatter
# ---------------------------------------------------------------------------

def _action_to_label(action: Dict[str, Any]) -> str:
    tool = action.get("tool", "")
    if tool == "search_code":
        return (
            f'search_code("{action.get("pattern", "")}", "{action.get("path", "")}", '
            f'file_type="{action.get("file_type")}", context_lines={action.get("context_lines", 15)})'
        )
    if tool == "find_files_with_symbol":
        return f'find_files_with_symbol("{action.get("symbol", "")}", "{action.get("path", "")}")'
    if tool == "find_definitions":
        return f'find_definitions("{action.get("symbol", "")}", "{action.get("path", "")}", "{action.get("lang", "")}")'
    if tool == "read_file":
        return (
            f'read_file("{action.get("path", "")}", {action.get("start_line")}, '
            f'{action.get("end_line")})'
        )
    return f"unknown_tool({tool})"


def _legacy_search_params_to_actions(search_params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backward compatibility if model returns old search_params schema."""
    actions: List[Dict[str, Any]] = []
    for sp in search_params:
        actions.append(
            {
                "tool": "search_code",
                "pattern": sp.get("pattern", ""),
                "path": sp.get("repo", "olake"),
                "file_type": (sp.get("file_types") or [None])[0],
                "context_lines": sp.get("context_lines", 15),
            }
        )
    return actions


def _group_hits_to_research_files(
    hits: List[SearchHit],
    tool_label: str,
    search_pattern: str,
) -> List[ResearchFile]:
    grouped: Dict[str, List[SearchHit]] = {}
    for h in hits:
        grouped.setdefault(h.path, []).append(h)

    files: List[ResearchFile] = []
    for path, file_hits in grouped.items():
        file_hits = sorted(file_hits, key=lambda x: x.line)
        content_chunks = [h.context for h in file_hits[:8] if h.context]
        content = "\n\n".join(content_chunks)
        matches = [f"{h.line}|{h.text}" for h in file_hits[:15]]
        files.append(
            ResearchFile(
                path=path,
                content=content,
                matches=matches,
                retrieval_reason=f"Found via {tool_label}",
                search_pattern=search_pattern,
            )
        )
    return files


# ---------------------------------------------------------------------------
# Stuck-detector helpers
# ---------------------------------------------------------------------------

def _normalize_pattern(action: Dict[str, Any]) -> str:
    """
    Produce a normalized fingerprint for a search action so we can detect
    when the planner is repeating the same query.  Lowercases and strips
    leading/trailing whitespace and quote characters.
    """
    raw = action.get("pattern") or action.get("symbol") or ""
    return raw.lower().strip().strip("\"'")


# ---------------------------------------------------------------------------
# Deep Researcher Node
# ---------------------------------------------------------------------------

class DeepResearcher:
    """
    Alex — Senior OLake Support Engineer.

    Iterative planner + searcher. Keeps raw file content OUT of the planner's
    context; only compact descriptions flow back into each iteration.
    """

    def __init__(self, max_iterations: int = 20):
        self.max_iterations = max_iterations
        self._system_prompt = _build_system_prompt()

    def __call__(self, state: ConversationState) -> ConversationState:
        logger = get_logger()

        user_query: str = state.get("user_query") or ""
        thread_summary: Optional[str] = state.get("thread_summary")
        thread_context: List[Dict[str, Any]] = state.get("thread_context") or []

        all_research_files: Dict[str, ResearchFile] = {}
        search_history_entries: List[str] = []
        thinking_log: List[str] = []
        conclusions_log: List[str] = []
        last_is_conceptual: bool = False

        # --- Stuck-detector state ---
        consecutive_zero_new_files: int = 0
        pattern_seen_counts: Dict[str, int] = {}
        # Tracks zero-gain iterations within the current window for the reflection pass.
        reflection_fired_this_window: bool = False
        pending_system_note: Optional[str] = None
        # Patterns that returned 0 results across all repos (for research_summary).
        null_result_patterns: List[str] = []

        _SEP = "─" * 60
        print(f"\n{_SEP}")
        print(f"[DeepResearcher] Starting  query={user_query[:120]!r}")
        print(f"[DeepResearcher] Context: {len(thread_context)} messages | summary={'yes' if thread_summary else 'no'}")
        print(_SEP)
        log.info("[DeepResearcher] start — query len=%d context=%d", len(user_query), len(thread_context))

        try:
            for iteration in range(1, self.max_iterations + 1):
                print(f"\n[DeepResearcher] ── Iteration {iteration}/{self.max_iterations} ──────────────────────────")
                log.info("[DeepResearcher] iteration %d", iteration)

                # --- Force exit if hard stuck-detector threshold hit ---
                if consecutive_zero_new_files >= _ZERO_NEW_FILES_FORCE_EXIT:
                    print(f"[DeepResearcher]   ⚠ Force-exit: {consecutive_zero_new_files} consecutive zero-gain iters")
                    log.info("[DeepResearcher] force-exit zero_new_files=%d", consecutive_zero_new_files)
                    break

                # --- Reflection pass: fire when threshold hit, once per zero-gain window ---
                reflection_actions: Optional[List[Dict[str, Any]]] = None
                if (
                    consecutive_zero_new_files >= _REFLECTION_AFTER_ITERS
                    and not reflection_fired_this_window
                ):
                    print(f"[DeepResearcher]   🔍 Firing reflection pass (zero_gain={consecutive_zero_new_files})")
                    log.info("[DeepResearcher] reflection pass iter=%d", iteration)
                    reflection_actions = self._run_reflection(user_query, search_history_entries)
                    reflection_fired_this_window = True
                    if reflection_actions is not None and len(reflection_actions) == 0:
                        print("[DeepResearcher]   🔍 Reflection returned [] — handing off")
                        log.info("[DeepResearcher] reflection returns empty — stopping")
                        break

                # --- If reflection gave us actions, skip the planner this turn ---
                if reflection_actions is not None:
                    actions = reflection_actions
                    thinking = "(reflection pass)"
                    search_intent = "Reflection-guided pivot strategy"
                    is_conceptual = False
                else:
                    user_message = _build_user_message(
                        user_query=user_query,
                        thread_summary=thread_summary,
                        thread_context=thread_context,
                        search_history_entries=search_history_entries,
                        conclusions_log=conclusions_log,
                        system_note=pending_system_note,
                    )
                    pending_system_note = None  # consumed

                    print(f"(DeepResearcher) Input characters count: {len(user_message) + len(self._system_prompt)}")

                    response = asyncio.run(get_chat_completion(
                        messages=[
                            {"role": "system", "content": self._system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        temperature=0.3,
                    ))

                    print(f"[DeepResearcher]   LLM raw ({len(response or '')} chars): {(response or '')[:200]!r}")
                    log.debug("[DeepResearcher] raw LLM response iter=%d: %s", iteration, (response or "")[:300])

                    result = parse_planner_json(response)

                    if "error" in result:
                        print(f"[DeepResearcher]   ✗ Parse error: {result['error']}")
                        log.warning("[DeepResearcher] Planner parse error iter=%d: %s", iteration, result["error"])
                        state["research_done"] = True
                        state["research_error"] = True
                        state["response_text"] = (
                            "I wasn't able to plan the research due to a model output error."
                        )
                        return state

                    thinking: str = result.get("thinking", "")
                    search_intent: str = result.get("search_intent", "")
                    actions: List[Dict[str, Any]] = result.get("actions") or []
                    if not actions and (result.get("search_params") or []):
                        actions = _legacy_search_params_to_actions(result.get("search_params") or [])
                    is_conceptual: bool = bool(result.get("is_conceptual", False))
                    last_is_conceptual = is_conceptual

                    print(f"[DeepResearcher]   💭 Thinking: {thinking.strip()}")
                    print(f"[DeepResearcher]   🎯 Intent:   {search_intent}")
                    print(f"[DeepResearcher]   is_conceptual={is_conceptual}  actions={len(actions)}")
                    log.info("[DeepResearcher] iter=%d thinking=%s... intent=%s params=%d conceptual=%s",
                             iteration, thinking[:80], search_intent[:60], len(actions), is_conceptual)

                    thinking_log.append(f"Iteration {iteration}: {thinking}")
                    if thinking.strip():
                        conclusions_log.append(f"Iter {iteration}: {thinking.strip()[:300]}")

                    if is_conceptual or not actions:
                        reason = "conceptual question" if is_conceptual else "planner has enough info"
                        print(f"[DeepResearcher]   ✓ Done ({reason}) — stopping search loop")
                        log.info("[DeepResearcher] done after iter=%d reason=%s", iteration, reason)
                        break

                    # --- Pattern-repeat stuck detector ---
                    for action in actions:
                        key = _normalize_pattern(action)
                        if key:
                            pattern_seen_counts[key] = pattern_seen_counts.get(key, 0) + 1
                            count = pattern_seen_counts[key]
                            if count >= _SAME_PATTERN_FORCE_PIVOT:
                                print(f"[DeepResearcher]   ⚠ Force-pivot: pattern seen {count}x — {key[:80]!r}")
                                log.info("[DeepResearcher] force-pivot pattern=%r count=%d", key[:80], count)
                                pending_system_note = (
                                    f"Pattern {key!r} has been searched {count} times with no new results. "
                                    "You MUST try a completely different approach: use partial tokens, "
                                    "different Go identifiers, or return actions:[] to hand off."
                                )
                                actions = []  # force hand-off this turn
                                break
                            if count == _SAME_PATTERN_WARN_THRESHOLD:
                                print(f"[DeepResearcher]   ⚡ Pattern repeat warn ({count}x): {key[:80]!r}")
                                pending_system_note = (
                                    f"WARNING: Pattern {key!r} has already been searched {count - 1} times "
                                    "with no useful results. Retrying it again is very unlikely to help — "
                                    "pivot to a different strategy."
                                )

                    if not actions:
                        # force-pivot triggered; still record the thinking before stopping
                        thinking_log.append(f"Iteration {iteration}: {thinking}")
                        if thinking.strip():
                            conclusions_log.append(f"Iter {iteration}: {thinking.strip()[:300]}")
                        log.info("[DeepResearcher] force-pivot break iter=%d", iteration)
                        break

                for i, action in enumerate(actions, 1):
                    print(f"[DeepResearcher]   📦 Action {i}: {_action_to_label(action)}")
                log.info("[DeepResearcher] iter=%d running %d actions", iteration, len(actions))

                action_blocks: List[str] = []
                new_file_count_before = len(all_research_files)

                # Run search-like actions in parallel; read_file actions are sequential.
                search_actions = [
                    a for a in actions
                    if a.get("tool") in {"search_code", "find_files_with_symbol", "find_definitions"}
                ]
                read_actions = [a for a in actions if a.get("tool") == "read_file"]
                unknown_actions = [
                    a for a in actions
                    if a.get("tool") not in {"search_code", "find_files_with_symbol", "find_definitions", "read_file"}
                ]

                def _execute_search_action(action: Dict[str, Any], _iter: int = iteration) -> tuple[Dict[str, Any], List[ResearchFile], str]:
                    tool = action.get("tool")
                    label = _action_to_label(action)
                    if tool == "search_code":
                        hits = search_code(
                            pattern=action.get("pattern", ""),
                            path=action.get("path", "all"),
                            file_type=action.get("file_type"),
                            context_lines=int(action.get("context_lines", 15)),
                        )
                        files = _group_hits_to_research_files(
                            hits=hits,
                            tool_label=label,
                            search_pattern=str(action.get("pattern", "")),
                        )
                        if not hits:
                            block = f"Iteration {_iter} — {label}\n  → 0 results"
                        else:
                            preview = "\n".join(
                                f"  {h.path}:{h.line}  → {h.text[:180]}"
                                for h in hits[:5]
                            )
                            block = f"Iteration {_iter} — {label}\n{preview}"
                        return action, files, block

                    if tool == "find_definitions":
                        hits = find_definitions(
                            symbol=action.get("symbol", ""),
                            path=action.get("path", "all"),
                            lang=action.get("lang", "go"),
                        )
                        files = _group_hits_to_research_files(
                            hits=hits,
                            tool_label=label,
                            search_pattern=str(action.get("symbol", "")),
                        )
                        if not hits:
                            block = f"Iteration {_iter} — {label}\n  → 0 results"
                        else:
                            preview = "\n".join(
                                f"  {h.path}:{h.line}  → {h.text[:180]}"
                                for h in hits[:5]
                            )
                            block = f"Iteration {_iter} — {label}\n{preview}"
                        return action, files, block

                    if tool == "find_files_with_symbol":
                        files_found = find_files_with_symbol(
                            symbol=action.get("symbol", ""),
                            path=action.get("path", "all"),
                        )
                        files: List[ResearchFile] = []
                        for p in files_found[:20]:
                            files.append(
                                ResearchFile(
                                    path=p,
                                    content="",
                                    matches=[f"symbol: {action.get('symbol', '')}"],
                                    retrieval_reason=f"Found via {label}",
                                    search_pattern=str(action.get("symbol", "")),
                                )
                            )
                        if not files_found:
                            block = f"Iteration {_iter} — {label}\n  → 0 results"
                        else:
                            preview = "\n".join(f"  {p}" for p in files_found[:5])
                            block = f"Iteration {_iter} — {label}\n{preview}"
                        return action, files, block

                    return action, [], f"Iteration {_iter} — {label}\n  → unsupported tool"

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [executor.submit(_execute_search_action, action) for action in search_actions]
                    for future in futures:
                        try:
                            done_action, files, block = future.result()
                            action_blocks.append(block)
                            # Track patterns that returned zero results for research_summary.
                            if "→ 0 results" in block:
                                pat = done_action.get("pattern") or done_action.get("symbol", "")
                                if pat:
                                    null_result_patterns.append(pat)
                            for rf in files:
                                # If same file is revisited, keep richer/later content.
                                if rf.path in all_research_files:
                                    existing = all_research_files[rf.path]
                                    merged_matches = list(dict.fromkeys((existing.matches or []) + (rf.matches or [])))
                                    existing.matches = merged_matches[:20]
                                    if len(rf.content or "") > len(existing.content or ""):
                                        existing.content = rf.content
                                    existing.retrieval_reason = rf.retrieval_reason
                                    existing.search_pattern = rf.search_pattern
                                else:
                                    all_research_files[rf.path] = rf
                        except RgSearchError as rg_err:
                            # Surface rg tool errors in history so the planner sees them,
                            # distinguishable from genuine 0-match results.
                            action_blocks.append(
                                f"Iteration {iteration} — rg error (tool failure, not zero results): {rg_err}"
                            )
                            log.warning("[DeepResearcher] rg error iter=%d: %s", iteration, rg_err)
                        except Exception as search_err:
                            action_blocks.append(
                                f"Iteration {iteration} — search error: {search_err}"
                            )
                            log.warning("[DeepResearcher] search failed iter=%d: %s", iteration, search_err)

                for action in read_actions:
                    label = _action_to_label(action)
                    try:
                        file_text = read_file(
                            path=action.get("path", ""),
                            start_line=action.get("start_line"),
                            end_line=action.get("end_line"),
                        )
                        line_count = len((file_text or "").splitlines())
                        rf = ResearchFile(
                            path=str(action.get("path", "")),
                            content=file_text,
                            matches=[],
                            retrieval_reason=f"Read via {label}",
                            search_pattern=f"read_file:{action.get('path', '')}",
                        )
                        all_research_files[rf.path] = rf
                        _preview_lines = (file_text or "").splitlines()[:12]
                        _preview = "\n".join(f"  {ln}" for ln in _preview_lines)
                        if line_count > 12:
                            _preview += "\n  … (truncated)"
                        action_blocks.append(
                            f"Iteration {iteration} — {label}\n  → {line_count} lines read (preview: {_preview})"
                        )
                    except Exception as read_err:
                        action_blocks.append(
                            f"Iteration {iteration} — {label}\n  → error: {read_err}"
                        )
                        log.warning("[DeepResearcher] read_file failed iter=%d: %s", iteration, read_err)

                for action in unknown_actions:
                    label = _action_to_label(action)
                    action_blocks.append(f"Iteration {iteration} — {label}\n  → unsupported tool")

                total_files = len(all_research_files)
                added_this_iter = total_files - new_file_count_before
                print(f"[DeepResearcher]   📁 Added {added_this_iter} file(s) (total: {total_files})")
                for p in list(all_research_files.keys())[:8]:
                    print(f"                      • {p}")
                if total_files > 8:
                    print(f"[DeepResearcher]      … and {total_files - 8} more")
                log.info("[DeepResearcher] iter=%d added_files=%d total=%d",
                         iteration, added_this_iter, total_files)

                history_entry = (
                    f"Iteration {iteration}\n"
                    f"  Intent: {search_intent}\n"
                    f"  Thinking: {(thinking or '').strip()[:220]}\n\n"
                    + "\n\n".join(action_blocks)
                )
                search_history_entries.append(history_entry)

                # --- History compaction: collapse older entries every N iterations ---
                if len(search_history_entries) % _HISTORY_COMPACT_INTERVAL == 0:
                    tail = search_history_entries[-_HISTORY_COMPACT_INTERVAL:]
                    head = search_history_entries[:-_HISTORY_COMPACT_INTERVAL]
                    if head:
                        print(f"[DeepResearcher]   📦 Compacting {len(head)} older history entries…")
                        log.info("[DeepResearcher] compacting %d history entries iter=%d", len(head), iteration)
                        compacted = asyncio.run(_compact_history(head, user_query))
                        search_history_entries = [compacted] + tail

                # --- Update stuck-detector state ---
                if added_this_iter == 0:
                    consecutive_zero_new_files += 1
                    if consecutive_zero_new_files == _ZERO_NEW_FILES_INJECT_THRESHOLD:
                        pending_system_note = (
                            f"The last {consecutive_zero_new_files} iterations added zero new files. "
                            "You MUST change strategy: use path='all', try partial token patterns, "
                            "search doc file paths, or return actions:[] to hand off with a bounded answer."
                        )
                        print(f"[DeepResearcher]   ⚡ Zero-gain inject note (streak={consecutive_zero_new_files})")
                else:
                    # Reset window state on any progress.
                    consecutive_zero_new_files = 0
                    reflection_fired_this_window = False

        except Exception as e:
            print(f"\n[DeepResearcher] ✗ Unexpected error: {e}")
            log.warning("[DeepResearcher] unexpected error: %s", e, exc_info=True)
            state["research_done"] = True
            state["research_error"] = True
            state["response_text"] = f"An error occurred while researching: {e}"
            return state

        print(f"\n[DeepResearcher] ✓ Complete — {len(all_research_files)} files, {len(search_history_entries)} iterations")
        print(_SEP)
        log.info("[DeepResearcher] complete: files=%d iterations=%d",
                 len(all_research_files), len(search_history_entries))

        # Build a compact research_summary for the solution provider.
        all_patterns = [
            _normalize_pattern(a)
            for entry in search_history_entries
            for a in []  # patterns are embedded in entry text; use null_result_patterns directly
        ]
        repos_used = sorted({
            a.get("path", "all")
            for entry in (state.get("search_history") or [])
            for a in []
        }) or ["all"]
        unique_null = list(dict.fromkeys(null_result_patterns))
        research_summary = (
            f"Searched: {len(search_history_entries)} iteration(s) across all repos\n"
            f"Found: {len(all_research_files)} file(s) with relevant content\n"
            + (f"Null results (0 hits across all repos): {', '.join(unique_null[:10])}\n" if unique_null else "")
        )

        state["research_files"] = list(all_research_files.values())
        state["thinking_log"] = thinking_log
        state["search_history"] = search_history_entries
        state["research_summary"] = research_summary
        state["research_done"] = True
        state["is_conceptual"] = last_is_conceptual
        return state

    def _run_reflection(
        self,
        user_query: str,
        search_history_entries: List[str],
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fire a cheap metacognitive LLM call to diagnose why searches failed
        and produce a fresh set of actions. Returns None on error, [] to hand off.
        """
        reflection_msg = _build_reflection_message(user_query, search_history_entries)
        try:
            print(f"(DeepResearcher: _run_reflection) Input characters count: {len(reflection_msg) + len(_REFLECTION_SYSTEM)}")
            response = asyncio.run(get_chat_completion(
                messages=[
                    {"role": "system", "content": _REFLECTION_SYSTEM},
                    {"role": "user", "content": reflection_msg},
                ],
                temperature=0.2,
            ))
            parsed = parse_planner_json(response)
            if "error" in parsed:
                log.warning("[DeepResearcher] reflection parse error: %s", parsed["error"])
                return None
            diagnosis = parsed.get("diagnosis", "")
            actions = parsed.get("actions") or []
            print(f"[DeepResearcher]   🔍 Reflection diagnosis: {diagnosis[:200]}")
            log.info("[DeepResearcher] reflection diagnosis=%s actions=%d", diagnosis[:120], len(actions))
            return actions
        except Exception as e:
            log.warning("[DeepResearcher] reflection call failed: %s", e)
            return None


# ---------------------------------------------------------------------------
# Synchronous wrapper for LangGraph
# ---------------------------------------------------------------------------

def deep_researcher(state: ConversationState) -> ConversationState:
    """LangGraph node entry point for the deep researcher."""
    return DeepResearcher()(state)
