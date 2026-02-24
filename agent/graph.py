"""
LangGraph workflow for OLake Slack Community Agent.

Topology:
  analyze_intent
      → problem_decomposer          [NEW] breaks issue into queries & sub-questions
      → build_context
           └─ [org member in thread] → END silently
      → retrieve_docs               [loops up to max_retrieval_iterations]
      → deep_reasoning              [ANSWER | CLARIFY | RETRIEVE_MORE]
           ├─ RETRIEVE_MORE (iterations < max) → retrieve_docs (loop)
           ├─ RETRIEVE_MORE (iterations >= max) → solution or clarification
           ├─ ANSWER  → solution
           └─ CLARIFY → clarification
      solution      → END
      clarification → END
      escalation    → END
"""

from langgraph.graph import StateGraph, END
from typing import Literal

from agent.state import ConversationState
from agent.nodes.intent_analyzer import analyze_intent_sync
from agent.nodes.problem_decomposer import problem_decomposer_sync
from agent.nodes.context_builder import build_context
from agent.nodes.doc_retriever import doc_retriever
from agent.nodes.deep_reasoner import deep_reasoner_sync
from agent.nodes.solution_provider import solution_provider
from agent.nodes.clarification_asker import clarification_asker_sync
from agent.nodes.escalation_handler import escalation_handler
from agent.nodes.low_confidence_tagger import low_confidence_tagger
from agent.logger import get_logger


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_context(
    state: ConversationState,
) -> Literal["retrieve_docs", "__end__"]:
    """After context build: exit silently if an org member is in the thread."""
    if state.get("org_member_replied"):
        get_logger().logger.info("Org member in thread — bot staying silent.")
        return "__end__"
    return "retrieve_docs"


def route_after_reasoning(
    state: ConversationState,
) -> Literal["solution", "clarification", "escalation", "retrieve_docs", "low_confidence_tagger"]:
    """
    Route after each deep_reasoning iteration.

    RETRIEVE_MORE:
      - RAG unavailable: skip loop (keyword fallback returns identical results)
      - Iterations remaining: loop back to retrieve_docs
      - Cap reached: fall through to solution or clarification
    CLARIFY → clarification (agent decided it needs to ask questions)
    ANSWER  → solution (if confidence >= 50%) or low_confidence_tagger (if < 50%)
    """
    decision    = state.get("reasoner_decision", "ANSWER").upper()
    iterations  = state.get("retrieval_iterations", 0)
    max_iters   = state.get("max_retrieval_iterations", 3)
    confidence  = state.get("final_confidence", 0.0)
    rag_up      = state.get("rag_service_available")  # None/True/False

    if state.get("should_escalate"):
        return "escalation"

    # If reasoner wants MORE retrieval, let it retrieve (don't short-circuit to tagger)
    if decision == "RETRIEVE_MORE":
        if rag_up is not False and iterations < max_iters:
            return "retrieve_docs"
        # Cap reached or RAG is down — now decide based on confidence
        if confidence < 0.5:
            return "low_confidence_tagger"
        return "clarification" if confidence < 0.4 else "solution"

    # CLARIFY means agent decided it needs to ask questions — let it clarify
    if decision == "CLARIFY":
        return "clarification"

    # decision == "ANSWER" — check if confidence is too low to answer
    if confidence < 0.5:
        return "low_confidence_tagger"

    return "solution"


# ---------------------------------------------------------------------------
# Doc retriever wrapper that increments retrieval_iterations
# and merges new search queries from the reasoner into the state
# ---------------------------------------------------------------------------

def retrieve_docs_with_counter(state: ConversationState) -> ConversationState:
    """
    Wraps doc_retriever to:
      1. Merge new_search_queries (from deep_reasoner) into search_queries
      2. Track all queries in retrieval_history to avoid re-querying the same thing
      3. Store a summary of what was found for each query (for the reasoner)
      4. Increment retrieval_iterations counter
    """
    # Merge reasoner-requested queries into the active query set
    new_qs = state.get("new_search_queries", [])
    existing_qs = state.get("search_queries", [])
    history = state.get("retrieval_history", [])
    
    # Track which queries are new (for summary generation)
    queries_this_iteration = new_qs if new_qs else existing_qs[:3]

    if new_qs:
        # Prepend new queries so they take priority
        merged = list(dict.fromkeys(new_qs + existing_qs))
        state["search_queries"] = merged
        state["new_search_queries"] = []

    # Store doc count before retrieval (to know what was added)
    docs_before = len(state.get("retrieved_docs", []))

    # Run actual retrieval
    state = doc_retriever(state)

    # Build a summary of what was retrieved this iteration
    docs_after = len(state.get("retrieved_docs", []))
    new_docs_count = docs_after - docs_before
    retrieved_docs = state.get("retrieved_docs", [])
    
    # Summarize the newly retrieved docs
    if new_docs_count > 0 and retrieved_docs:
        new_docs = retrieved_docs[-new_docs_count:] if new_docs_count <= len(retrieved_docs) else retrieved_docs
        doc_summary = "; ".join([f"{d.title}" for d in new_docs[:5]])
    else:
        doc_summary = "(No new docs retrieved)"
    
    # Store iteration summary for the reasoner to use
    iteration_summary = {
        "queries": queries_this_iteration,
        "docs_found": new_docs_count,
        "doc_summary": doc_summary,
    }
    
    # Append to retrieval_summaries list
    summaries = state.get("retrieval_summaries", [])
    summaries.append(iteration_summary)
    state["retrieval_summaries"] = summaries

    # Update retrieval accounting
    state["retrieval_iterations"] = state.get("retrieval_iterations", 0) + 1
    new_history = list(dict.fromkeys(history + state.get("search_queries", [])))
    state["retrieval_history"] = new_history

    return state


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def create_agent_graph() -> StateGraph:
    """
    Build and compile the LangGraph agent workflow.

    Node sequence:
      analyze_intent → problem_decomposer → build_context → retrieve_docs
      → deep_reasoning → [route] → solution | clarification | escalation

    The retrieve_docs ↔ deep_reasoning loop repeats up to max_retrieval_iterations.
    """
    logger = get_logger()
    logger.logger.info("Creating agent graph...")

    workflow = StateGraph(ConversationState)

    # ── Nodes ────────────────────────────────────────────────────────────
    # workflow.add_node("analyze_intent",    analyze_intent_sync)
    workflow.add_node("problem_decomposer", problem_decomposer_sync)
    workflow.add_node("build_context",     build_context)
    workflow.add_node("retrieve_docs",     retrieve_docs_with_counter)
    workflow.add_node("deep_reasoning",    deep_reasoner_sync)
    workflow.add_node("solution",          solution_provider)
    workflow.add_node("clarification",     clarification_asker_sync)
    workflow.add_node("escalation",        escalation_handler)
    workflow.add_node("low_confidence_tagger", low_confidence_tagger)

    # ── Entry ─────────────────────────────────────────────────────────────
    workflow.set_entry_point("problem_decomposer")

    # ── Fixed edges ───────────────────────────────────────────────────────
    # workflow.add_edge("analyze_intent",    "problem_decomposer")
    workflow.add_edge("problem_decomposer", "build_context")

    # After context: exit silently if org member is in the thread
    workflow.add_conditional_edges(
        "build_context",
        route_after_context,
        {
            "retrieve_docs": "retrieve_docs",
            "__end__": END,
        },
    )

    workflow.add_edge("retrieve_docs", "deep_reasoning")

    # After reasoning: ANSWER / CLARIFY / loop RETRIEVE_MORE / LOW_CONFIDENCE
    workflow.add_conditional_edges(
        "deep_reasoning",
        route_after_reasoning,
        {
            "retrieve_docs": "retrieve_docs",   # loop
            "solution":      "solution",
            "clarification": "clarification",
            "escalation":    "escalation",
            "low_confidence_tagger": "low_confidence_tagger",
        },
    )

    workflow.add_edge("solution",      END)
    workflow.add_edge("clarification", END)
    workflow.add_edge("escalation",    END)
    workflow.add_edge("low_confidence_tagger", END)

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
