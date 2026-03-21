"""
LangGraph workflow for OLake Slack Community Agent (production).

Topology:
  build_context
       └─ [org member in thread] → END silently
  → gate_filter
       ├─ [harmful or irrelevant] → END  (reply already sent by gate_filter)
       ├─ [not actionable]        → END  (silent — "thanks" / noise)
       └─ [pass]                  → deep_researcher → solution → END
"""

from langgraph.graph import StateGraph, END
from typing import Literal, Callable, Any, Dict

from agent.state import ConversationState
from agent.nodes.context_builder import build_context
from agent.nodes.gate_filter import gate_filter
from agent.nodes.deep_researcher import deep_researcher
from agent.nodes.solution_provider import solution_provider
from agent.logger import get_logger


# ---------------------------------------------------------------------------
# Step logging
# ---------------------------------------------------------------------------

def _step_summary(node_name: str, state: ConversationState) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if node_name == "build_context":
        summary["org_member_replied"] = state.get("org_member_replied", False)
        summary["thread_messages"] = len(state.get("thread_context") or [])
    elif node_name == "gate_filter":
        summary["is_relevant"] = state.get("is_relevant")
        summary["is_actionable"] = state.get("is_actionable")
        summary["is_harmful"] = state.get("is_harmful")
        summary["question_type"] = state.get("question_type")
    elif node_name == "deep_researcher":
        summary["research_files_count"] = len(state.get("research_files") or [])
        summary["search_iterations"] = len(state.get("search_history") or [])
        summary["is_conceptual"] = state.get("is_conceptual")
    elif node_name == "solution":
        summary["response_length"] = len(state.get("response_text") or "")
    return summary


def _wrap_node(node_name: str, node_fn: Callable[[ConversationState], ConversationState]):
    """Wrap a node to log step start/end."""

    def wrapped(state: ConversationState) -> ConversationState:
        logger = get_logger()
        callback = state.get("_step_log_callback")
        step_order = (state.get("_node_step_order") or 0) + 1
        try:
            logger.log_step_start(node_name)
            if callback:
                try:
                    callback("start", node_name, None)
                except Exception:
                    pass
            result = node_fn(state)
            summary = _step_summary(node_name, result)
            logger.log_step_end(node_name, summary=summary)
            if callback:
                try:
                    callback("end", node_name, summary)
                except Exception:
                    pass
            result["_node_step_order"] = step_order
            return result
        except Exception as e:
            err_msg = str(e)
            logger.log_step_end(node_name, summary=None, error=err_msg)
            if callback:
                try:
                    callback("end", node_name, {"error": err_msg})
                except Exception:
                    pass
            raise

    return wrapped


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_context(
    state: ConversationState,
) -> Literal["gate_filter", "__end__"]:
    """Exit silently if an org member is already in the thread."""
    if state.get("org_member_replied"):
        get_logger().logger.info("Org member in thread — bot staying silent.")
        return "__end__"
    return "gate_filter"


def route_after_gate(
    state: ConversationState,
) -> Literal["deep_researcher", "__end__"]:
    """
    Route based on gate_filter classification:
      - Blocked (harmful/irrelevant): reply already sent → END
      - Not actionable (noise):       silent → END
      - Everything else:              → deep_researcher (always)
    """
    if state.get("is_harmful") or not state.get("is_relevant", True):
        get_logger().logger.info(
            "[route_after_gate] Blocked (harmful=%s relevant=%s)",
            state.get("is_harmful"), state.get("is_relevant"),
        )
        return "__end__"

    if not state.get("is_actionable", True):
        get_logger().logger.info("[route_after_gate] Non-actionable message — silent END.")
        return "__end__"

    return "deep_researcher"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def create_agent_graph() -> StateGraph:
    logger = get_logger()
    logger.logger.info("Creating agent graph...")

    workflow = StateGraph(ConversationState)

    workflow.add_node("build_context",   _wrap_node("build_context",   build_context))
    workflow.add_node("gate_filter",     _wrap_node("gate_filter",     gate_filter))
    workflow.add_node("deep_researcher", _wrap_node("deep_researcher", deep_researcher))
    workflow.add_node("solution",        _wrap_node("solution",        solution_provider))

    workflow.set_entry_point("build_context")

    workflow.add_conditional_edges(
        "build_context",
        route_after_context,
        {"gate_filter": "gate_filter", "__end__": END},
    )
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
    logger.logger.info("Agent graph created successfully")
    return compiled


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_graph = None


def get_agent_graph():
    """Get or create the global agent graph (compiled once per process)."""
    global _graph
    if _graph is None:
        _graph = create_agent_graph()
    return _graph
