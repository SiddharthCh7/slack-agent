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
from typing import Optional

# ── pretty output helpers ──────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"
BLUE   = "\033[94m"

def header(text):   print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}\n{BOLD}{CYAN}  {text}{RESET}\n{BOLD}{CYAN}{'─'*60}{RESET}")
def user_msg(text): print(f"\n{BOLD}{BLUE}👤 USER:{RESET} {text}")
def bot_msg(text):  print(f"\n{BOLD}{GREEN}🤖  BOT:{RESET}\n{textwrap.indent(textwrap.fill(text, 80), '    ')}")
def info(text):     print(f"{DIM}  ℹ  {text}{RESET}")
def warn(text):     print(f"{YELLOW}  ⚠  {text}{RESET}")
def error(text):    print(f"{RED}  ✗  {text}{RESET}")
def separator():    print(f"\n{DIM}{'─'*60}{RESET}")

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

            # ── public methods used by agent nodes ──────────────────────
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
                return []  # No prior thread in local tests

            def is_bot_message(self, event):
                return event.get("user") == self.bot_user_id

            def format_response_blocks(self, response_text, confidence,
                                       docs_cited=None, is_clarification=False,
                                       is_escalation=False):
                # Reuse real implementation for formatting
                from agent.slack_client import SlackClient
                return SlackClient.format_response_blocks(
                    self, response_text, confidence,
                    docs_cited, is_clarification, is_escalation
                )

        fake = _FakeSlackClient()

        # Override the module-level factory so any subsequent create_slack_client()
        # calls (e.g. from context_builder) get the fake too
        sc_module.create_slack_client = lambda *a, **kw: fake

        # Patch any already-imported references in other modules
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


def print_result(result: dict):
    state = result["state"]
    elapsed = result["elapsed"]
    separator()

    # Intent
    intent = state.get("intent_type")
    urgency = state.get("urgency")
    confidence = state.get("final_confidence", 0.0)
    info(f"Intent: {intent.value if intent else '?'} | Urgency: {urgency.value if urgency else '?'} | Confidence: {confidence:.0%} | Time: {elapsed:.1f}s")

    # Docs retrieved
    docs = state.get("retrieved_docs", [])
    if docs:
        info(f"Retrieved {len(docs)} doc chunk(s): {', '.join(d.title[:40] for d in docs[:3])}")
    else:
        info("No docs retrieved (keyword fallback or below threshold)")

    # Escalation flag
    if state.get("should_escalate"):
        warn(f"Escalation triggered → {state.get('escalation_reason', '')}")

    # Error
    if state.get("error"):
        error(f"Agent error: {state['error']}")

    # Response
    response = state.get("response_text") or ""
    if response:
        bot_msg(response)
    else:
        warn("No response text generated.")

    # Clarification questions
    for q in state.get("clarification_questions", []):
        print(f"    {YELLOW}❓ {q}{RESET}")


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
        info("Graph loaded ✓")
    except Exception as e:
        error(f"Failed to load graph: {e}")
        sys.exit(1)

    # Shared thread timestamp for this session
    thread_ts = args.thread_ts or f"{time.time():.6f}"
    info(f"Thread TS: {thread_ts}  |  User: {args.user}  |  Channel: {args.channel}")

    # ── scenario mode ──────────────────────────────────────────────────────
    if args.scenario:
        messages = SCENARIOS[args.scenario]
        header(f"Scenario: {args.scenario} ({len(messages)} message(s))")
        for msg in messages:
            user_msg(msg)
            result = run_message(msg, args.user, args.channel, thread_ts, graph)
            print_result(result)
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

    try:
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
                continue

            result = run_message(raw, args.user, args.channel, thread_ts, graph)
            print_result(result)

    except KeyboardInterrupt:
        pass

    print(f"\n{DIM}Session ended.{RESET}")


if __name__ == "__main__":
    main()
