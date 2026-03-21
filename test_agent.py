#!/usr/bin/env python
"""
Local test harness for the OLake Slack Community Agent.

Uses the **production** agent graph (agent.graph.create_agent_graph) — the same
workflow as main.py in prod. So any changes to the main agent are reflected here
and in production. Do not switch this to the CLI graph; keep testing the real graph.

Simulates a Slack thread (patched client, no real Slack posts).

Usage:
    python test_agent.py                          # interactive mode
    python test_agent.py --message "How do I set up CDC with Postgres?"
    python test_agent.py --user U99TESTUSER --channel C99TESTCHAN
    python test_agent.py --scenario cdc           # run a preset scenario

Each run = one Slack thread. Messages in the same run share thread_ts.
"""

import sys
import time
import uuid
import argparse
import textwrap
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

# Rich for live progress (thinking / search_intent / commands / files)
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text
from rich.tree import Tree

# ── pretty output helpers ──────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"
BLUE   = "\033[94m"
MAGENTA = "\033[95m"
WHITE  = "\033[97m"

# Box drawing characters
BOX_H = "─"
BOX_V = "│"
BOX_TL = "╭"
BOX_TR = "╮"
BOX_BL = "╰"
BOX_BR = "╯"
BOX_CROSS = "┼"

def header(text):
    print(f"\n{BOLD}{CYAN}{BOX_H*60}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{BOX_H*60}{RESET}")

def footer():
    print(f"\n{DIM}{BOX_H*60}{RESET}")

def user_msg(text):
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{BLUE}👤 USER{RESET}{DIM} (iteration){RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  {text}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")

def bot_msg(text):
    wrapped = textwrap.fill(text, 54)
    lines = wrapped.split('\n')
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{GREEN}🤖 BOT RESPONSE{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}{BOX_H*56}{BOX_V}")
    for line in lines:
        print(f"{BOX_V}  {line}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")

def separator():
    print(f"\n{DIM}{BOX_H*60}{RESET}")

def section_header(title):
    print(f"\n{BOLD}{CYAN}╔{'═'*58}╗{RESET}")
    print(f"{BOLD}{CYAN}║  {title.center(54)}  ║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*58}╝{RESET}")

def info(text):
    print(f"{DIM}  ℹ  {text}{RESET}")

def warn(text):
    print(f"{YELLOW}  ⚠  {text}{RESET}")

def error(text):
    print(f"{RED}  ✗  {text}{RESET}")

def success(text):
    print(f"{GREEN}  ✓  {text}{RESET}")


# ── pretty research files printer (codebase search: ripgrep + ast-grep via SearchParams) ─
def print_research_files(files: List[Any], iteration: int = None):
    """Pretty print research files from codebase search (unified search with SearchParams)."""
    if not files:
        print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
        print(f"{BOX_V} {BOLD}{MAGENTA}📁 FILES RETRIEVED{RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}{BOX_H*56}{BOX_V}")
        print(f"{BOX_V}  {DIM}No files found (codebase search){RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")
        return

    iter_label = f" (iteration {iteration})" if iteration else ""
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{MAGENTA}📁 FILES RETRIEVED{RESET}{DIM}{iter_label}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  Found {GREEN}{len(files)}{RESET} file(s) via ripgrep/ast-grep".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}{BOX_H*56}{BOX_V}")

    for i, f in enumerate(files[:5], 1):
        path = getattr(f, "path", str(f))[:45]
        score = len(getattr(f, "matches", []))
        source = getattr(f, "source", "ripgrep")
        reason = (getattr(f, "retrieval_reason", "") or "")[:80].replace("\n", " ")

        score_color = GREEN if score >= 0.7 else YELLOW if score >= 0.4 else RED
        icon = "🔍" if source == "ripgrep" else "🌲"
        print(f"{BOX_V}  {icon} [{i}] {path}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}     Score: {score_color}{score:.2%}{RESET}  |  {source}".ljust(58) + f"{BOX_V}")
        if reason:
            print(f"{BOX_V}     {DIM}{reason}...{RESET}".ljust(58) + f"{BOX_V}")
        if i < len(files) and i < 5:
            print(f"{BOX_V}  {DIM}{'─'*50}{RESET}".ljust(58) + f"{BOX_V}")

    if len(files) > 5:
        print(f"{BOX_V}  {DIM}... and {len(files) - 5} more file(s){RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")


# ── pretty decision printer ───────────────────────────────────────────────
def print_decision(intent: str, : float,
                   should_escalate: bool = False, escalation_reason: str = None):
    """Pretty print agent decision."""
    conf_color = GREEN if  >= 0.7 else YELLOW if  >= 0.4 else RED
    
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{CYAN}🧠 AGENT DECISION{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}{BOX_H*56}{BOX_V}")
    print(f"{BOX_V}  Intent:    {BOLD}{intent}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  : {conf_color}{:.0%}{RESET}".ljust(58) + f"{BOX_V}")
    
    if should_escalate:
        print(f"{BOX_V}  {RED}⚠ ESCALATION TRIGGERED{RESET}".ljust(58) + f"{BOX_V}")
        if escalation_reason:
            reason_text = textwrap.fill(f"Reason: {escalation_reason}", 48)
            for line in reason_text.split('\n'):
                print(f"{BOX_V}    {line}".ljust(58) + f"{BOX_V}")
    
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")


# ── pretty agent steps printer (which node ran + result) ───────────────────
def print_agent_steps(steps: List[Dict[str, Any]]) -> None:
    """Pretty print each graph step: node name and result summary."""
    if not steps:
        return
    section_header("AGENT STEPS (node → result)")
    for s in steps:
        if s.get("phase") != "end":
            continue
        node = s.get("node", "?")
        data = s.get("data") or {}
        err = data.get("error")
        if err:
            print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
            print(f"{BOX_V} {BOLD}{RED}✗ {node}{RESET}".ljust(58) + f"{BOX_V}")
            print(f"{BOX_V}  {RED}Error: {err[:48]}{RESET}".ljust(58) + f"{BOX_V}")
            print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")
            continue
        parts = []
        for k, v in data.items():
            if v is None:
                parts.append(f"  {k}=None")
            elif isinstance(v, bool):
                parts.append(f"  {k}={str(v).lower()}")
            elif isinstance(v, (int, float)):
                if isinstance(v, float) and 0 <= v <= 1:
                    parts.append(f"  {k}={v:.2f}")
                else:
                    parts.append(f"  {k}={v}")
            elif isinstance(v, list):
                parts.append(f"  {k}=[{len(v)} items]")
            elif isinstance(v, str) and len(v) > 40:
                parts.append(f"  {k}={v[:40]}…")
            else:
                parts.append(f"  {k}={v}")
        body = "\n".join(parts) if parts else "  (no summary)"
        print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
        print(f"{BOX_V} {BOLD}{GREEN}✓ {node}{RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}{BOX_H*56}{BOX_V}")
        for line in body.split("\n"):
            print(f"{BOX_V}{DIM}{line}{RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")
    footer()


# ── pretty final result printer ───────────────────────────────────────────
def print_final_result(response: str, latency: float, docs_count: int,
                       : float, 
                       clarification_questions: List[str] = None):
    """Pretty print final result with latency."""
    conf_color = GREEN if  >= 0.7 else YELLOW if  >= 0.4 else RED
    section_header("FINAL RESULT")
    
    # Response
    if response:
        wrapped = textwrap.fill(response, 54)
        lines = wrapped.split('\n')
        print(f"{BOX_TL}{BOX_H*58}{BOX_TR}")
        print(f"{BOX_V} {BOLD}{GREEN}💬 RESPONSE{RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}{BOX_H*56}{BOX_V}")
        for line in lines:
            print(f"{BOX_V}  {line}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")
    
    # Clarification questions
    if clarification_questions:
        print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
        print(f"{BOX_V} {BOLD}{YELLOW}❓ CLARIFICATION NEEDED{RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}{BOX_H*56}{BOX_V}")
        for i, q in enumerate(clarification_questions, 1):
            q_text = textwrap.fill(f"{i}. {q}", 52)
            for line in q_text.split('\n'):
                print(f"{BOX_V}  {line}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")
    
    # Latency and stats
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{WHITE}⏱ PERFORMANCE{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}{BOX_H*56}{BOX_V}")
    print(f"{BOX_V}  Total Latency:    {GREEN}{latency:.2f}s{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  Docs Retrieved:   {CYAN}{docs_count}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  Final : {conf_color}{:.0%}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")


# ── preset scenarios ───────────────────────────────────────────────────────
SCENARIOS = {
    "cdc": [
        "Hi, I'm trying to set up CDC with PostgreSQL but I'm getting errors in the replication slot.",
        "I created the replication slot using pgoutput. The error says wal_level is not set to logical.",
    ],
    "mysql": [
        "What sync modes does OLake support for MySQL?",
    ],
    "install": [
        "How do I install OLake? I'm on Ubuntu.",
        "Which version of Docker do I need?",
    ],
    "benchmark": [
        "What are the benchmarks for MongoDB full load?",
    ],
    "escalate": [
        "I found a critical bug in the CDC pipeline. Data is being lost silently.",
    ],
}

# ── build a fake Slack event ───────────────────────────────────────────────
def make_event(
    text: str,
    thread_ts: str,
    message_ts: Optional[str] = None,
) -> dict:
    ts = message_ts or f"{time.time():.6f}"
    return {
        "type": "event_callback",
        "team_id": "T_TEST",
        "event": {
            "type": "message",
            "subtype": None,
            "text": text,
            "ts": ts,
            "thread_ts": thread_ts,
        },
    }

# Frames for manual loading indicator (so it advances on each refresh; Rich Spinner resets when recreated)
_LOADING_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def _build_progress_display(events: List[Dict], still_running: bool, refresh_index: int = 0):
    """
    Build Rich renderable for live progress: per-iteration blocks with
    search intent (what it's searching and why), thinking, commands (pattern + repo from SearchParams),
    and files. Matches production deep_researcher emissions exactly.
    """
    # Streamed thinking chunks by iteration (for in-progress)
    streamed_by_iter: Dict[int, str] = {}
    for ev in events:
        if ev.get("type") == "thinking_chunk":
            it = ev.get("iteration", 0)
            streamed_by_iter[it] = streamed_by_iter.get(it, "") + (ev.get("delta") or "")

    # Group events into per-iteration blocks: [{"iter": N, "search_intent": str, "thinking": str, "preview": str, "commands": list, "files": list}]
    blocks: List[Dict[str, Any]] = []
    current_block: Optional[Dict[str, Any]] = None

    for ev in events:
        t = ev.get("type")
        if t == "thinking_done":
            it = ev.get("iteration", 0)
            current_block = {
                "iter": it,
                "search_intent": "",
                "thinking": ev.get("thinking", ""),
                "preview": ev.get("preview", ""),
                "commands": [],
                "paths": [],
            }
            blocks.append(current_block)
        elif t == "search_intent" and current_block is not None:
            current_block["search_intent"] = ev.get("text", "")
        elif t == "commands_ran" and current_block is not None:
            current_block["commands"] = ev.get("commands", [])
        elif t == "files_found" and current_block is not None:
            current_block["paths"] = ev.get("paths", [])

    started_iters = [ev["iteration"] for ev in events if ev.get("type") == "thinking_start"]
    done_iters = {ev["iteration"] for ev in events if ev.get("type") == "thinking_done"}
    current_iter = next((it for it in reversed(started_iters) if it not in done_iters), None)

    parts: List[Any] = []

    # Modern loading state until first iteration output is available (manual frames so it animates each refresh)
    if still_running and not blocks:
        frame = _LOADING_FRAMES[refresh_index % len(_LOADING_FRAMES)]
        return Panel(
            Text(f"{frame}  Researching....", style="cyan"),
            title="[bold]Research[/bold]",
            border_style="dim",
            padding=(1, 2),
        )

    # Status line when research is in progress (we have at least started)
    if still_running and current_iter is not None:
        streamed = streamed_by_iter.get(current_iter, "")
        if streamed.strip():
            preview = (streamed[:60] + "…") if len(streamed) > 60 else streamed
            parts.append(Group(
                Spinner("dots"),
                Text(f"  [cyan]Iteration {current_iter}[/cyan] — ", style="bold"),
                Text(preview, style="dim"),
            ))
        else:
            parts.append(Group(
                Spinner("dots"),
                Text(f"  [cyan]Iteration {current_iter}[/cyan] — waiting for model…", style="dim"),
            ))

    # Root tree: one section per iteration
    tree = Tree(
        "[bold cyan]Research progress[/bold cyan]",
        expanded=True,
        guide_style="dim",
    )

    # Completed iteration blocks
    for blk in blocks:
        it = blk.get("iter", 0)
        search_intent = (blk.get("search_intent") or "").strip() or "(no intent captured)"
        preview = (blk.get("preview") or "").strip() or "(no preview)"
        thinking = (blk.get("thinking") or "").strip()
        commands = blk.get("commands") or []
        paths = blk.get("paths") or []

        iter_label = f"[bold]Iteration {it}[/bold]"
        if search_intent and search_intent != "(no intent captured)":
            short = search_intent[:70] + "…" if len(search_intent) > 70 else search_intent
            iter_label += f" — [blue]{short}[/blue]"
        iter_branch = tree.add(iter_label, expanded=True)

        # What I'm searching and why
        iter_branch.add(Text("What I'm searching and why:", style="bold"))
        iter_branch.add(Text(search_intent, style="dim"))

        # Thinking (collapsible: preview in label, full text in child)
        think_label = f"Thinking: {preview}"
        think_branch = iter_branch.add(think_label, expanded=False)
        think_branch.add(Text(thinking or "(no thinking)", style="dim"))

        # Commands ran (each = one SearchParams: "pattern (repo=X)")
        if commands:
            cmd_branch = iter_branch.add("Commands ran:", expanded=False)
            for c in commands:
                cmd_branch.add(Text(c, style="dim"))

        # Files found (collapsible)
        count = len(paths)
        if count > 0:
            summary = ", ".join(paths[:3])
            if count > 3:
                summary += f" (+{count - 3} more)"
            files_branch = iter_branch.add(f"Files found ({count}): {summary}", expanded=False)
            for p in paths[:25]:
                files_branch.add(Text(p, style="dim"))
            if count > 25:
                files_branch.add(Text(f"... and {count - 25} more", style="dim"))
        else:
            iter_branch.add(Text("Files found: (none)", style="dim"))

    # In-progress iteration (streaming thinking)
    if current_iter is not None and current_iter not in {b["iter"] for b in blocks}:
        streamed = streamed_by_iter.get(current_iter, "")
        preview = (streamed[:60] + "…") if len(streamed) > 60 else (streamed or "Waiting for model…")
        prog_branch = tree.add(
            f"[bold]Iteration {current_iter}[/bold] [dim](in progress)[/dim] — {preview}",
            expanded=True,
        )
        prog_branch.add(Text(streamed or "…", style="dim"))

    if parts:
        parts.append(tree)
        return Group(*parts)
    return tree


def _patch_slack_for_local_testing():
    """
    Replace the live SlackClient with a local mock so API calls don't fail.
    All outbound messages are printed to the console instead.
    """
    try:
        import agent.slack_client as sc_module

        class _FakeSlackClient:
            """Mirrors the SlackClient interface. All API calls are no-ops or print."""

            def send_message(self, channel, text, thread_ts=None, blocks=None):
                print(f"\n{DIM}  [SLACK → #{channel}]{RESET}")
                print(f"  {text}")
                if blocks:
                    print(f"  [{len(blocks)} block(s)]")
                return {"ok": True, "ts": f"{time.time():.6f}", "channel": channel}

            def add_reaction(self, channel, timestamp, emoji):
                info(f"[SLACK] :{emoji}: reaction added on {timestamp}")

            def remove_reaction(self, channel, timestamp, emoji):
                pass

            def get_user_info(self):
                return {
                    "name": "local_test_user",
                    "real_name": "Local Test User",
                    "profile": {"email": "test@example.com"},
                }

            def get_thread_messages(self, channel, thread_ts, limit=10):
                return []

            def format_response_blocks(self, response_text, ,
                                       docs_cited=None, is_clarification=False,
                                       is_escalation=False):
                from agent.slack_client import SlackClient
                return SlackClient.format_response_blocks(
                    self, response_text, ,
                    docs_cited, is_clarification, is_escalation
                )

        fake = _FakeSlackClient()
        sc_module.create_slack_client = lambda *a, **kw: fake

        import agent.nodes.context_builder as cb
        if hasattr(cb, "slack_client"):
            cb.slack_client = fake
        import agent.nodes.solution_provider as sp
        if hasattr(sp, "slack_client"):
            sp.slack_client = fake

        info("Slack client patched for local testing ✓")
    except Exception as e:
        warn(f"Could not patch Slack client: {e}")


# ── run a single message through the agent graph ──────────────────────────
def run_message(
    text: str,
    thread_ts: str,
    graph,
) -> dict:
    from agent.state import create_initial_state

    event = make_event(text, thread_ts)
    state = create_initial_state(event)

    # Live progress (thinking / search_intent / commands / files) during deep_researcher
    progress_events: List[Dict] = []
    progress_lock = threading.Lock()

    def on_progress(ev: dict) -> None:
        with progress_lock:
            progress_events.append(ev)

    step_events: List[Dict[str, Any]] = []

    def on_step(phase: str, node_name: str, data: Any) -> None:
        step_events.append({"phase": phase, "node": node_name, "data": data})

    state["_cli_progress_callback"] = on_progress
    state["_step_log_callback"] = on_step

    result_holder: List[Optional[dict]] = [None]
    exc_holder: List[Optional[Exception]] = [None]

    def run_graph() -> None:
        try:
            result_holder[0] = graph.invoke(state)
        except Exception as e:
            exc_holder[0] = e

    start = time.time()
    graph_thread = threading.Thread(target=run_graph)
    graph_thread.start()

    refresh_count: List[int] = [0]

    def make_display():
        with progress_lock:
            events_snapshot = list(progress_events)
        refresh_count[0] += 1
        return _build_progress_display(
            events_snapshot, graph_thread.is_alive(), refresh_count[0]
        )

    console = Console()
    with Live(make_display(), refresh_per_second=8, console=console) as live:
        while graph_thread.is_alive():
            live.update(make_display())
            time.sleep(0.125)
        live.update(make_display())
    graph_thread.join()

    elapsed = time.time() - start

    if exc_holder[0] is not None:
        raise exc_holder[0]

    result = result_holder[0]
    return {"state": result, "elapsed": elapsed, "steps": step_events}


def print_result(result: dict, iteration: int = None):
    """Print result with pretty formatting."""
    state = result["state"]
    elapsed = result["elapsed"]
    steps = result.get("steps", [])

    # Which agents ran and their results (pretty-printed)
    print_agent_steps(steps)

    # Intent and decision
    intent = state.get("intent_type")
     = state.get("", 0.0)
    intent_str = intent.value if intent else "?"
    
    # Escalation
    should_escalate = state.get("should_escalate", False)
    escalation_reason = state.get("escalation_reason", "")
    
    # Print decision
    print_decision(
        intent=intent_str,
        =,
        should_escalate=should_escalate,
        escalation_reason=escalation_reason
    )
    
    # Search history (what was searched and why — 1–2 lines per iteration)
    search_history = state.get("search_history", [])
    if search_history:
        section_header("SEARCH INTENT (what was searched and why)")
        for i, entry in enumerate(search_history, 1):
            print(f"  {i}. {entry}")
        footer()

    # Research files (codebase search via SearchParams → ripgrep + ast-grep; no vectordb)
    research_files = state.get("research_files", [])
    print_research_files(research_files, iteration=iteration)

    # Error
    if state.get("error"):
        error(f"Agent error: {state['error']}")

    # Final result with latency
    response = state.get("response_text") or ""
    clarification_questions = state.get("clarification_questions", [])

    print_final_result(
        response=response,
        latency=elapsed,
        docs_count=len(research_files),
        =,
        clarification_questions=clarification_questions
    )


# ── main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="OLake Agent local test harness")
    parser.add_argument("--message", "-m", help="Single message to send")
    parser.add_argument("--user", default="U_LOCAL_TEST", help="Fake Slack user ID")
    parser.add_argument("--channel", default="C_LOCAL_TEST", help="Fake Slack channel ID")
    parser.add_argument("--scenario", "-s", choices=list(SCENARIOS.keys()),
                        help="Run a preset multi-message scenario")
    parser.add_argument("--thread-ts", help="Reuse an existing thread TS")
    args = parser.parse_args()

    # Disable agent console logging so Rich Live progress display is not overwritten by INFO lines
    from agent.logger import get_logger
    get_logger(enable_console=False)

    header("OLake Community Agent — Local Test Harness")

    # Patch Slack so local tests don't fail with channel_not_found / missing_scope
    _patch_slack_for_local_testing()

    info("Loading agent graph (may take a moment on first run)…")

    try:
        # Production graph only — same as main.py so local tests reflect prod behavior
        from agent.graph import get_agent_graph
        graph = get_agent_graph()
        success("Graph loaded ✓")
    except Exception as e:
        error(f"Failed to load graph: {e}")
        sys.exit(1)

    # Shared thread timestamp for this session
    thread_ts = args.thread_ts or f"{time.time():.6f}"
    info(f"Thread TS: {thread_ts}  |  User: {args.user}  |  Channel: {args.channel}")

    try:
        # ── scenario mode ──────────────────────────────────────────────────────
        if args.scenario:
            messages = SCENARIOS[args.scenario]
            header(f"Scenario: {args.scenario} ({len(messages)} message(s))")
            for i, msg in enumerate(messages, 1):
                user_msg(msg)
                result = run_message(msg, thread_ts, graph)
                print_result(result, iteration=i)
            separator()
            success("Scenario complete!")
            return

        # ── single message mode ────────────────────────────────────────────────
        if args.message:
            user_msg(args.message)
            result = run_message(args.message, thread_ts, graph)
            print_result(result)
            return

        # ── interactive thread mode ────────────────────────────────────────────
        header("Interactive Thread Mode  (Ctrl+C or type 'exit' to quit, 'new' for new thread)")
        print(f"{DIM}Each session = one Slack thread. All messages share the same thread_ts.{RESET}\n")

        iteration = 1
        while True:
            try:
                raw = input(f"{BOLD}You:{RESET} ").strip()
            except EOFError:
                break

            if not raw:
                continue
            if raw.lower() in ("exit", "quit", "q"):
                break
            if raw.lower() == "new":
                thread_ts = f"{time.time():.6f}"
                print(f"{DIM}  ↻ Started new thread: {thread_ts}{RESET}")
                iteration = 1
                continue

            user_msg(raw)
            result = run_message(raw, thread_ts, graph)
            print_result(result, iteration=iteration)
            iteration += 1

    except KeyboardInterrupt:
        pass

    print(f"\n{DIM}Session ended.{RESET}")


if __name__ == "__main__":
    main()
