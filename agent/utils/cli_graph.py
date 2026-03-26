"""
LangGraph workflow for CLI mode.

Topology:
  cli_context_builder → gate_filter → deep_researcher → solution → END

Note: gate_filter's Slack reply is silently skipped in CLI mode (no Slack credentials).
Blocked/non-actionable messages still reach END without a solution node call.
"""

from langgraph.graph import StateGraph, END
from typing import Literal

from agent.state import ConversationState
from agent.nodes.gate_filter import gate_filter
from agent.nodes.deep_researcher import deep_researcher
from agent.nodes.cli import build_cli_context, cli_solution_provider
from agent.utils.logger import get_logger


def route_after_gate(
    state: ConversationState,
) -> Literal["deep_researcher", "__end__"]:
    if state.get("is_harmful") or not state.get("is_relevant", True):
        return "__end__"
    if not state.get("is_actionable", True):
        return "__end__"
    return "deep_researcher"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def create_cli_agent_graph() -> StateGraph:
    logger = get_logger()
    logger.logger.info("Creating CLI agent graph...")

    workflow = StateGraph(ConversationState)

    workflow.add_node("cli_context_builder", build_cli_context)
    workflow.add_node("gate_filter",         gate_filter)
    workflow.add_node("deep_researcher",     deep_researcher)
    workflow.add_node("solution",            cli_solution_provider)

    workflow.set_entry_point("cli_context_builder")

    workflow.add_edge("cli_context_builder", "gate_filter")
    workflow.add_conditional_edges(
        "gate_filter",
        route_after_gate,
        {
            "deep_researcher": "deep_researcher",
            "__end__":         END,
        },
    )
    workflow.add_edge("deep_researcher", "solution")
    workflow.add_edge("solution", END)

    compiled = workflow.compile()
    logger.logger.info("CLI agent graph created successfully")
    return compiled


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_cli_graph = None


def get_cli_agent_graph():
    """Get or create the global CLI agent graph (compiled once per process)."""
    global _cli_graph
    if _cli_graph is None:
        _cli_graph = create_cli_agent_graph()
    return _cli_graph
