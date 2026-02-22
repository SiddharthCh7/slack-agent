#!/usr/bin/env python
"""
Local test harness for the OLake Slack Community Agent.

Simulates a Slack thread conversation without needing a running Slack workspace
or webhook server. Uses the real LangGraph agent graph end-to-end.

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
from datetime import datetime
from typing import Optional, List, Dict, Any

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


# ── pretty docs printer ────────────────────────────────────────────────────
def print_docs_retrieved(docs: List[Any], iteration: int = None):
    """Pretty print retrieved documentation."""
    if not docs:
        print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
        print(f"{BOX_V} {BOLD}{MAGENTA}📄 DOCS RETRIEVED{RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}{BOX_H*56}{BOX_V}")
        print(f"{BOX_V}  {DIM}No docs retrieved (below threshold or fallback){RESET}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")
        return
    
    iter_label = f" (iteration {iteration})" if iteration else ""
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{MAGENTA}📄 DOCS RETRIEVED{RESET}{DIM}{iter_label}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  Found {GREEN}{len(docs)}{RESET} relevant document(s)".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}{BOX_H*56}{BOX_V}")
    
    for i, doc in enumerate(docs[:5], 1):  # Show top 5
        title = getattr(doc, 'title', 'Unknown')[:45]
        score = getattr(doc, 'relevance_score', 0)
        source = getattr(doc, 'source_type', 'docs')
        content = getattr(doc, 'content', '')[:120].replace('\n', ' ')
        
        source_icon = "📖" if source == "docs" else "💻"
        score_color = GREEN if score >= 0.7 else YELLOW if score >= 0.4 else RED
        
        print(f"{BOX_V}  {source_icon} [{i}] {title}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}     Score: {score_color}{score:.2%}{RESET}  |  Type: {source}".ljust(58) + f"{BOX_V}")
        print(f"{BOX_V}     {DIM}«{content}...»{RESET}".ljust(58) + f"{BOX_V}")
        if i < len(docs) and i < 5:
            print(f"{BOX_V}  {DIM}{'─'*50}{RESET}".ljust(58) + f"{BOX_V}")
    
    if len(docs) > 5:
        print(f"{BOX_V}  {DIM}... and {len(docs) - 5} more document(s){RESET}".ljust(58) + f"{BOX_V}")
    
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")


# ── pretty decision printer ───────────────────────────────────────────────
def print_decision(intent: str, urgency: str, confidence: float, 
                   should_escalate: bool = False, escalation_reason: str = None):
    """Pretty print agent decision."""
    conf_color = GREEN if confidence >= 0.7 else YELLOW if confidence >= 0.4 else RED
    
    print(f"\n{BOX_TL}{BOX_H*58}{BOX_TR}")
    print(f"{BOX_V} {BOLD}{CYAN}🧠 AGENT DECISION{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}{BOX_H*56}{BOX_V}")
    print(f"{BOX_V}  Intent:    {BOLD}{intent}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  Urgency:   {BOLD}{urgency}{RESET}".ljust(58) + f"{BOX_V}")
    print(f"{BOX_V}  Confidence: {conf_color}{confidence:.0%}{RESET}".ljust(58) + f"{BOX_V}")
    
    if should_escalate:
        print(f"{BOX_V}  {RED}⚠ ESCALATION TRIGGERED{RESET}".ljust(58) + f"{BOX_V}")
        if escalation_reason:
            reason_text = textwrap.fill(f"Reason: {escalation_reason}", 48)
            for line in reason_text.split('\n'):
                print(f"{BOX_V}    {line}".ljust(58) + f"{BOX_V}")
    
    print(f"{BOX_BL}{BOX_H*58}{BOX_BR}")


# ── pretty final result printer ───────────────────────────────────────────
def print_final_result(response: str, latency: float, docs_count: int,
                       confidence: float, 
                       clarification_questions: List[str] = None):
    """Pretty print final result with latency."""
    conf_color = GREEN if confidence >= 0.7 else YELLOW if confidence >= 0.4 else RED
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
    print(f"{BOX_V}  Final Confidence: {conf_color}{confidence:.0%}{RESET}".ljust(58) + f"{BOX_V}")
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
    user_id: str,
    channel_id: str,
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
            "user": user_id,
            "channel": channel_id,
            "ts": ts,
            "thread_ts": thread_ts,
        },
    }

def _patch_slack_for_local_testing():
    """
    Replace the live SlackClient with a local mock so API calls don't fail.
    All outbound messages are printed to the console instead.
    """
    try:
        import agent.slack_client as sc_module

        class _FakeSlackClient:
            """Mirrors the SlackClient interface. All API calls are no-ops or print."""

            def __init__(self):
                self.bot_user_id = "U_BOT_TEST"

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

            def get_user_info(self, user_id):
                return {
                    "id": user_id,
                    "name": "local_test_user",
                    "real_name": "Local Test User",
                    "profile": {"email": "test@example.com"},
                }

            def get_thread_messages(self, channel, thread_ts, limit=10):
                return []

            def is_bot_message(self, event):
                return event.get("user") == self.bot_user_id

            def format_response_blocks(self, response_text, confidence,
                                       docs_cited=None, is_clarification=False,
                                       is_escalation=False):
                from agent.slack_client import SlackClient
                return SlackClient.format_response_blocks(
                    self, response_text, confidence,
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
        import agent.nodes.escalation_handler as eh
        if hasattr(eh, "slack_client"):
            eh.slack_client = fake
        import agent.nodes.clarification_asker as ca
        if hasattr(ca, "slack_client"):
            ca.slack_client = fake

        info("Slack client patched for local testing ✓")
    except Exception as e:
        warn(f"Could not patch Slack client: {e}")


# ── run a single message through the agent graph ──────────────────────────
def run_message(
    text: str,
    user_id: str,
    channel_id: str,
    thread_ts: str,
    graph,
) -> dict:
    from agent.state import create_initial_state

    event = make_event(text, user_id, channel_id, thread_ts)
    state = create_initial_state(event)

    start = time.time()
    result = graph.invoke(state)
    elapsed = time.time() - start

    return {"state": result, "elapsed": elapsed}


def print_result(result: dict, iteration: int = None):
    """Print result with pretty formatting."""
    state = result["state"]
    elapsed = result["elapsed"]
    
    # Intent and decision
    intent = state.get("intent_type")
    urgency = state.get("urgency")
    confidence = state.get("final_confidence", 0.0)
    intent_str = intent.value if intent else "?"
    urgency_str = urgency.value if urgency else "?"
    
    # Escalation
    should_escalate = state.get("should_escalate", False)
    escalation_reason = state.get("escalation_reason", "")
    
    # Print decision
    print_decision(
        intent=intent_str,
        urgency=urgency_str,
        confidence=confidence,
        should_escalate=should_escalate,
        escalation_reason=escalation_reason
    )
    
    # Docs retrieved
    docs = state.get("retrieved_docs", [])
    print_docs_retrieved(docs, iteration=iteration)
    
    # Error
    if state.get("error"):
        error(f"Agent error: {state['error']}")
    
    # Final result with latency
    response = state.get("response_text") or ""
    clarification_questions = state.get("clarification_questions", [])
    
    print_final_result(
        response=response,
        latency=elapsed,
        docs_count=len(docs),
        confidence=confidence,
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

    header("OLake Community Agent — Local Test Harness")

    # Patch Slack so local tests don't fail with channel_not_found / missing_scope
    _patch_slack_for_local_testing()

    info("Loading agent graph (may take a moment on first run)…")

    try:
        from agent.graph import create_agent_graph
        graph = create_agent_graph()
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
                result = run_message(msg, args.user, args.channel, thread_ts, graph)
                print_result(result, iteration=i)
            separator()
            success("Scenario complete!")
            return

        # ── single message mode ────────────────────────────────────────────────
        if args.message:
            user_msg(args.message)
            result = run_message(args.message, args.user, args.channel, thread_ts, graph)
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
            result = run_message(raw, args.user, args.channel, thread_ts, graph)
            print_result(result, iteration=iteration)
            iteration += 1

    except KeyboardInterrupt:
        pass

    finally:
        # Cleanup: close HTTP client properly to avoid event loop errors
        try:
            from agent.rag_client import close_client
            close_client()
        except Exception:
            pass

    print(f"\n{DIM}Session ended.{RESET}")


if __name__ == "__main__":
    main()
