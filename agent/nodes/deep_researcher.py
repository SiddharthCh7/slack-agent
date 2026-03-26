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
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.filesystem.codebase_search import RgSearchError, read_file
from agent.filesystem.research_search_actions import action_to_label, execute_search_action
from agent.config import ABOUT_PRODUCT, ABOUT_REPOS, AGENT_NAME, COMPANY_NAME, Config
from agent.utils.llm import get_chat_completion
from agent.utils.logger import get_logger
from agent.state import ConversationState, ResearchFile
from agent.utils.parser import parse_planner_json

log = logging.getLogger(__name__)


class DeepResearcherRunLog:
    """
    One log file per deep_researcher run: every LLM invocation with full prompts,
    context, and raw model output. Subsystems: main planner, reflection, history compaction.
    """

    def __init__(self, log_dir: Optional[str] = None) -> None:
        base = Path(log_dir or Config.LOG_DIR)
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = base / f"deep_researcher_{ts}.log"
        self._fh = open(self.path, "w", encoding="utf-8")
        self._emit(
            "Deep Researcher — session log\n"
            f"File: {self.path}\n"
            f"Started (local): {datetime.now().isoformat()}\n"
        )
        self._emit("=" * 80 + "\n\n")

    def _emit(self, text: str) -> None:
        self._fh.write(text)
        self._fh.flush()

    def _banner(self, title: str) -> None:
        self._emit("\n" + "─" * 80 + "\n")
        self._emit(title + "\n")
        self._emit("─" * 80 + "\n")

    def log_session_start(
        self,
        *,
        user_query: str,
        thread_summary: Optional[str],
        thread_context: List[Dict[str, Any]],
        max_iterations: int,
    ) -> None:
        self._banner("SESSION INPUT (before any model calls)")
        self._emit(f"max_iterations: {max_iterations}\n")
        self._emit(f"user_query ({len(user_query)} chars):\n{user_query}\n\n")
        summary = (thread_summary or "").strip() or "(none)"
        self._emit(f"thread_summary ({len(summary)} chars):\n{summary}\n\n")
        self._emit(
            f"thread_context: {len(thread_context)} message(s)\n"
            + json.dumps(thread_context, indent=2, ensure_ascii=False)
            + "\n\n"
        )

    def log_subsystem_note(
        self,
        subsystem: str,
        *,
        iteration: Optional[int],
        message: str,
    ) -> None:
        it = f" | iteration {iteration}" if iteration is not None else ""
        self._banner(f"[{subsystem}]{it} — note")
        self._emit(message.rstrip() + "\n\n")

    def log_llm_invocation(
        self,
        subsystem: str,
        *,
        description: str,
        temperature: float,
        system_prompt: str,
        user_content: str,
        model_output: str,
        iteration: Optional[int] = None,
        extra_after_output: Optional[str] = None,
    ) -> None:
        it = f" | iteration {iteration}" if iteration is not None else ""
        self._banner(f"SUBSYSTEM: {subsystem}{it}")
        self._emit(f"Role: {description}\n")
        self._emit(f"Temperature: {temperature}\n")
        self._emit(f"System prompt length: {len(system_prompt)} chars\n")
        self._emit(f"User message length: {len(user_content)} chars\n")
        self._emit(f"Model output length: {len(model_output or '')} chars\n\n")
        self._emit("--- SYSTEM PROMPT (full context the model receives as system) ---\n")
        self._emit(system_prompt)
        self._emit("\n\n--- USER MESSAGE (full context the model receives as user) ---\n")
        self._emit(user_content)
        self._emit("\n\n--- MODEL OUTPUT (raw completion) ---\n")
        self._emit(model_output or "")
        self._emit("\n")
        if extra_after_output:
            self._emit("\n--- EXTRA ---\n")
            self._emit(extra_after_output.rstrip() + "\n")
        self._emit("\n")

    def log_exception(self, exc: BaseException) -> None:
        self._banner("SESSION ERROR")
        self._emit(f"{type(exc).__name__}: {exc}\n\n")

    def close(self) -> None:
        if self._fh is not None:
            self._emit("\n" + "=" * 80 + "\n")
            self._emit(f"Session ended: {datetime.now().isoformat()}\n")
            self._fh.close()
            self._fh = None


# ---------------------------------------------------------------------------
# Stuck-detector and reflection constants
# ---------------------------------------------------------------------------

# Inject a SYSTEM NOTE into the next iteration when the same pattern is seen this many times.
_SAME_PATTERN_WARN_THRESHOLD = 2
# Force actions=[] (immediate hand-off) when the same pattern is seen this many times.
# Lowered from 3 to 2 to catch loops earlier and avoid wasted iterations.
_SAME_PATTERN_FORCE_PIVOT = 3
# Inject a SYSTEM NOTE after this many consecutive iterations that added zero new files.
_ZERO_NEW_FILES_INJECT_THRESHOLD = 3
# Force exit (hand-off) after this many consecutive zero-gain iterations.
_ZERO_NEW_FILES_FORCE_EXIT = 5
# Fire the metacognitive reflection LLM call after this many consecutive zero-gain iterations.
_REFLECTION_AFTER_ITERS = 3
# Compact raw history entries older than the last window into a single summary block.
_HISTORY_COMPACT_INTERVAL = 8

# ---------------------------------------------------------------------------
# System prompt (static — describes the agent role and tool contract only)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are {agent_name}, a senior support engineer at {company_name}. Think and reason explicitly \
in first person: use "I" in your reasoning (e.g. "I need to search for ...", \
"Now I will look for ...", "I should target ...").

About {company_name}:
{about_product}

Repositories available for search:
{about_repos}

Your job: Research the codebase to find the information needed to answer the \
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

GO NAMING — when searching Go codebases: use PascalCase for exported \
identifiers (ExpireSnapshot) and camelCase for unexported (expireSnapshot). \
Never use Python-style snake_case — it will NOT match.

PATTERN QUALITY RULES:
- Default to path="all" for error strings, config keys, docs, or anything cross-cutting. \
  Use a named repo (e.g. "olake", "olake-docs") only when you already have a reason to narrow down.
- Compound terms over single words: "topic.*retention" not "retention"
- One regex covering all related variants beats multiple narrow searches
- Use SEARCH HISTORY to avoid repeating searches that already returned useful results

GO-TO Strategy to peform smart searches:
1. Search for the pattern once with path="all". If it returns 0 results: this is a probable indication \
that the pattern is not in the codebase. Do NOT retry the same pattern.
2. Immediately pivot to searching for PARTIAL TOKENS and Go identifiers related to the feature: \
struct field names, function names, config keys, doc file paths for the relevant writer/format.
3. If the data is not found even after multiple iterations, stop searching for it and return actions: [] immediately. \
Write in your "thinking": "Pattern not found in codebase. Handing off with bounded answer." \
The solution provider will produce a practical answer from docs and product knowledge. \
Do NOT wait until the iteration limit — stop as soon as you have enough signal.

CRITICAL — STOPPING RULES:
- Only return empty actions [] if the answer (including any specific URL, value, or fact the user \
asked for) is EXPLICITLY AND VERBATIM present in the conversation context above. \
Do NOT assume something was previously provided if you cannot quote it from the context. \
If the exact information is not visible in the context, search for it.

CRITICAL — OUTPUT RULES:
1. Your ENTIRE response must be a single JSON object. No prose, no preamble, no explanation \
before or after the JSON. Start your response with {{ and end with }}.
2. Do NOT write "I need to..." or any natural language before the JSON.
3. Use "thinking" for what you are planning to do next. \
   Use "conclusion_so_far" for a cumulative first-person narrative of what you have found \
   and not found across all previous iterations.

OUTPUT FORMAT (valid JSON only — nothing else):
{{
  "conclusion_so_far": "Cumulative first-person narrative (I found / I did not find ...). \
Update this every iteration by incorporating results from the previous iteration's searches. \
On the first iteration write: 'I am starting the research — no findings yet.'",
  "thinking": "What I am planning to search next and why.",
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
- conclusion_so_far and search_intent are REQUIRED every time.
- conclusion_so_far must be in first person using "I". Cover: what I searched, what I found \
  (file paths, facts, code snippets), and what I did not find (patterns that returned 0 results). \
  Build on the previous iteration's conclusion — do not start from scratch each time.
- Max 6 actions per iteration.
- Prefer search_code first, then read_file on promising files.
- Return empty actions [] when you have enough information to answer accurately.
- Set is_conceptual true only for general-knowledge questions that need no code search; \
  leave actions empty in that case.\
"""


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=AGENT_NAME,
        company_name=COMPANY_NAME,
        about_product=(ABOUT_PRODUCT or "").strip(),
        about_repos=(ABOUT_REPOS or "").strip(),
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
    conclusion_so_far: Optional[str] = None,
    system_note: Optional[str] = None,
    recent_reads: Optional[List[tuple]] = None,
) -> str:
    summary_block = (thread_summary or "").strip() or "(none — no prior conversation summary)"
    context_block = _format_thread_context(thread_context)
    history_block = _format_search_history(search_history_entries)

    conclusions_block = ""
    if conclusion_so_far and conclusion_so_far.strip():
        conclusions_block = (
            f"\n---\nMY CONCLUSIONS SO FAR (carry this forward and update it):\n"
            f"{conclusion_so_far.strip()}\n"
        )

    note_block = ""
    if system_note:
        note_block = f"\n---\nSYSTEM NOTE: {system_note}\n"

    # Survive history compaction: always include the last 3 read_file results verbatim
    # so the planner never needs to re-read a file it already fetched this session.
    recent_reads_block = ""
    if recent_reads:
        parts = [
            f"=== {label} ===\n{content}"
            for label, content in recent_reads
        ]
        recent_reads_block = (
            "\n---\nRECENTLY READ FILE CONTENT "
            "(last reads — check here before issuing another read_file for the same range):\n"
            + "\n\n".join(parts)
            + "\n"
        )

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
{recent_reads_block}{note_block}
---
Based on the above, decide what to search next.
"""

# ---------------------------------------------------------------------------
# Compact history summariser
# ---------------------------------------------------------------------------

_COMPACT_HISTORY_SYSTEM = """\
You are a compact summariser for a codebase research session.
Given a list of search iterations, produce a tight bullet-point summary that preserves:
- Every pattern/symbol that was searched (with hit count or "0 results")
- Every file that was found (file path only, one per line)
- Any facts definitively established (e.g. "string not found in codebase — likely runtime-assembled")

Output ONLY the bullet list. No headings, no preamble, no JSON.
Keep the total output under 40 lines. Be concise — omit repeated findings.
"""


async def _compact_history(
    entries: List[str],
    user_query: str,
    run_log: Optional[DeepResearcherRunLog] = None,
    iteration: Optional[int] = None,
) -> str:
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
        out = f"[Compacted summary — {len(entries)} iteration(s)]\n{(summary or '').strip()}"
        if run_log:
            run_log.log_llm_invocation(
                "History compaction",
                description="Summarise older search iterations into a compact bullet list (replaces raw history head)",
                temperature=0.0,
                system_prompt=_COMPACT_HISTORY_SYSTEM,
                user_content=user_msg,
                model_output=summary or "",
                iteration=iteration,
            )
        return out
    except Exception as exc:
        if run_log:
            run_log.log_subsystem_note(
                "History compaction",
                iteration=iteration,
                message=f"LLM compaction failed; using raw joined entries. Error: {exc!r}",
            )
        log.warning("[DeepResearcher] history compaction failed: %s", exc)
        return "\n\n".join(entries)  # fall back to raw on failure


# ---------------------------------------------------------------------------
# Reflection system
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Stuck-detector helpers
# ---------------------------------------------------------------------------

def _normalize_pattern(action: Dict[str, Any]) -> str:
    """
    Produce a normalized fingerprint for a search action so we can detect
    when the planner is repeating the same query.  Lowercases and strips
    leading/trailing whitespace and quote characters.
    
    Includes tool + path in the key to distinguish searches with same pattern
    but different scopes (e.g., search_code vs find_definitions, or path="all" vs specific repo).
    """
    tool = action.get("tool", "")
    raw = action.get("pattern") or action.get("symbol", "")
    path = action.get("path", "all")
    # Normalize: tool|path|pattern for more accurate deduplication
    normalized = f"{tool}|{path}|{raw}".lower().strip().strip("\"'")
    return normalized


# ---------------------------------------------------------------------------
# Deep Researcher Node
# ---------------------------------------------------------------------------

class DeepResearcher:
    """
    Alex — Senior OLake Support Engineer.

    Iterative planner + searcher. Full read_file content and recent reads are
    fed back to the planner each iteration; search results use compact previews.
    """

    def __init__(self, max_iterations: int = 12):
        self.max_iterations = max_iterations
        self._system_prompt = _build_system_prompt()
        self._run_log: Optional[DeepResearcherRunLog] = None

    def __call__(self, state: ConversationState) -> ConversationState:
        logger = get_logger()

        user_query: str = state.get("user_query") or ""
        thread_summary: Optional[str] = state.get("thread_summary")
        thread_context: List[Dict[str, Any]] = state.get("thread_context") or []

        all_research_files: Dict[str, ResearchFile] = {}
        search_history_entries: List[str] = []
        thinking_log: List[str] = []
        current_conclusion: str = ""
        last_is_conceptual: bool = False
        # Tracks the last 3 read_file results as (label, content) tuples so they
        # survive history compaction and are always visible to the planner.
        recent_reads: List[tuple] = []

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

        run_log: Optional[DeepResearcherRunLog] = None
        try:
            run_log = DeepResearcherRunLog()
            self._run_log = run_log
            log.info("[DeepResearcher] session log file: %s", run_log.path)
            print(f"[DeepResearcher] Session log: {run_log.path}")
            run_log.log_session_start(
                user_query=user_query,
                thread_summary=thread_summary,
                thread_context=thread_context,
                max_iterations=self.max_iterations,
            )

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
                    reflection_actions = self._run_reflection(
                        user_query, search_history_entries, iteration=iteration
                    )
                    reflection_fired_this_window = True
                    if reflection_actions is not None and len(reflection_actions) == 0:
                        print("[DeepResearcher]   🔍 Reflection returned [] — handing off")
                        log.info("[DeepResearcher] reflection returns empty — stopping")
                        break

                # --- If reflection gave us actions, skip the planner this turn ---
                if reflection_actions is not None:
                    run_log.log_subsystem_note(
                        "Reflection system",
                        iteration=iteration,
                        message=(
                            "Deep researcher (main) planner was NOT run this iteration. "
                            "Executing tool actions from the reflection LLM pass "
                            "(see the most recent 'SUBSYSTEM: Reflection system' block above)."
                        ),
                    )
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
                        conclusion_so_far=current_conclusion or None,
                        system_note=pending_system_note,
                        recent_reads=recent_reads or None,
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
                        _extra_main = f"parse_planner_json error: {result['error']}"
                    else:
                        _extra_main = json.dumps(
                            {
                                "conclusion_so_far": result.get("conclusion_so_far"),
                                "thinking": result.get("thinking"),
                                "search_intent": result.get("search_intent"),
                                "actions": result.get("actions"),
                                "is_conceptual": result.get("is_conceptual"),
                                "search_params": result.get("search_params"),
                            },
                            indent=2,
                            ensure_ascii=False,
                        )
                    run_log.log_llm_invocation(
                        "Deep researcher (main)",
                        description="Iterative codebase planner — JSON with conclusion_so_far, thinking, search_intent, actions",
                        temperature=0.3,
                        system_prompt=self._system_prompt,
                        user_content=user_message,
                        model_output=response or "",
                        iteration=iteration,
                        extra_after_output=_extra_main,
                    )

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
                    new_conclusion: str = result.get("conclusion_so_far", "").strip()
                    actions: List[Dict[str, Any]] = result.get("actions") or []
                    if not actions and (result.get("search_params") or []):
                        actions = _legacy_search_params_to_actions(result.get("search_params") or [])
                    is_conceptual: bool = bool(result.get("is_conceptual", False))
                    last_is_conceptual = is_conceptual

                    if new_conclusion:
                        current_conclusion = new_conclusion

                    print(f"[DeepResearcher]   📋 Conclusion: {new_conclusion[:120]}")
                    print(f"[DeepResearcher]   💭 Thinking:   {thinking.strip()[:120]}")
                    print(f"[DeepResearcher]   🎯 Intent:     {search_intent}")
                    print(f"[DeepResearcher]   is_conceptual={is_conceptual}  actions={len(actions)}")
                    log.info("[DeepResearcher] iter=%d conclusion=%s... thinking=%s... intent=%s params=%d conceptual=%s",
                             iteration, new_conclusion[:60], thinking[:60], search_intent[:60], len(actions), is_conceptual)

                    thinking_log.append(f"Iteration {iteration}: {thinking}")

                    if is_conceptual or not actions:
                        reason = "conceptual question" if is_conceptual else "planner has enough info"
                        print(f"[DeepResearcher]   ✓ Done ({reason}) — stopping search loop")
                        log.info("[DeepResearcher] done after iter=%d reason=%s", iteration, reason)
                        # When the planner decided it can answer from context (no actions, no files),
                        # flag as conceptual so SolutionProvider proceeds to LLM generation instead
                        # of the "no files found" early-exit path.
                        if not actions and not is_conceptual:
                            last_is_conceptual = True
                        break

                    # --- Pattern-repeat stuck detector ---
                    for action in actions:
                        key = _normalize_pattern(action)
                        if key:
                            pattern_seen_counts[key] = pattern_seen_counts.get(key, 0) + 1
                            count = pattern_seen_counts[key]
                            print(f"[DeepResearcher]   🔍 Pattern tracker: {key[:70]!r} seen {count}x")
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
                        # force-pivot triggered; record thinking but keep current_conclusion as-is
                        thinking_log.append(f"Iteration {iteration}: {thinking}")
                        log.info("[DeepResearcher] force-pivot break iter=%d", iteration)
                        break

                for i, action in enumerate(actions, 1):
                    print(f"[DeepResearcher]   📦 Action {i}: {action_to_label(action)}")
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

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(execute_search_action, action, iteration)
                        for action in search_actions
                    ]
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
                    label = action_to_label(action)
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
                        # Track full content in recent_reads — it survives compaction and
                        # is injected verbatim into every subsequent iteration's user message.
                        recent_reads.append((label, file_text or ""))
                        recent_reads = recent_reads[-3:]  # keep last 3 reads only
                        # History entry uses a capped preview to avoid ballooning context.
                        # The full content is always accessible via the recent_reads block.
                        _HISTORY_READ_CAP = 50
                        _hist_lines = (file_text or "").splitlines()
                        _hist_preview = "\n".join(_hist_lines[:_HISTORY_READ_CAP])
                        if len(_hist_lines) > _HISTORY_READ_CAP:
                            _hist_preview += (
                                f"\n… [{len(_hist_lines) - _HISTORY_READ_CAP} more lines — "
                                "full content available in RECENTLY READ FILE CONTENT block above]"
                            )
                        action_blocks.append(
                            f"Iteration {iteration} — {label}\n  → {line_count} lines read:\n{_hist_preview}"
                        )
                    except Exception as read_err:
                        action_blocks.append(
                            f"Iteration {iteration} — {label}\n  → error: {read_err}"
                        )
                        log.warning("[DeepResearcher] read_file failed iter=%d: %s", iteration, read_err)

                for action in unknown_actions:
                    label = action_to_label(action)
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
                    f"  Thinking: {(thinking or '').strip()[:300]}\n"
                    f"  Actions: {len(actions)} tool calls\n"
                    f"  Results: {added_this_iter} new files found\n"
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
                        compacted = asyncio.run(
                            _compact_history(head, user_query, run_log, iteration=iteration)
                        )
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

            run_log.log_subsystem_note(
                "Deep researcher (main)",
                iteration=None,
                message=(
                    "Search loop exited (normal completion, break, or max iterations). "
                    f"total_research_files={len(all_research_files)} "
                    f"search_history_entries={len(search_history_entries)}"
                ),
            )

        except Exception as e:
            print(f"\n[DeepResearcher] ✗ Unexpected error: {e}")
            log.warning("[DeepResearcher] unexpected error: %s", e, exc_info=True)
            if run_log:
                run_log.log_exception(e)
            state["research_done"] = True
            state["research_error"] = True
            state["response_text"] = f"An error occurred while researching: {e}"
            return state
        finally:
            self._run_log = None
            if run_log is not None:
                run_log.close()

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
        *,
        iteration: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fire a cheap metacognitive LLM call to diagnose why searches failed
        and produce a fresh set of actions. Returns None on error, [] to hand off.
        """
        reflection_msg = _build_reflection_message(user_query, search_history_entries)
        rl = self._run_log
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
                _extra = f"parse_planner_json error: {parsed['error']}"
            else:
                _extra = json.dumps(
                    {
                        "diagnosis": parsed.get("diagnosis"),
                        "actions": parsed.get("actions"),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            if rl:
                rl.log_llm_invocation(
                    "Reflection system",
                    description="Metacognitive pass — diagnose failed searches; propose 0-3 alternative actions (JSON)",
                    temperature=0.2,
                    system_prompt=_REFLECTION_SYSTEM,
                    user_content=reflection_msg,
                    model_output=response or "",
                    iteration=iteration,
                    extra_after_output=_extra,
                )
            if "error" in parsed:
                log.warning("[DeepResearcher] reflection parse error: %s", parsed["error"])
                return None
            diagnosis = parsed.get("diagnosis", "")
            actions = parsed.get("actions") or []
            print(f"[DeepResearcher]   🔍 Reflection diagnosis: {diagnosis[:200]}")
            log.info("[DeepResearcher] reflection diagnosis=%s actions=%d", diagnosis[:120], len(actions))
            return actions
        except Exception as e:
            if rl:
                rl.log_subsystem_note(
                    "Reflection system",
                    iteration=iteration,
                    message=f"Reflection LLM call failed: {e!r}",
                )
            log.warning("[DeepResearcher] reflection call failed: %s", e)
            return None


# ---------------------------------------------------------------------------
# Synchronous wrapper for LangGraph
# ---------------------------------------------------------------------------

def deep_researcher(state: ConversationState) -> ConversationState:
    """LangGraph node entry point for the deep researcher."""
    return DeepResearcher()(state)
