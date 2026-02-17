"""
LangGraph workflow for OLake Slack Community Agent.
"""

from langgraph.graph import StateGraph, END
from typing import Literal

from agent.state import ConversationState, create_initial_state
from agent.nodes.intent_analyzer import analyze_intent_sync
from agent.nodes.context_builder import build_context
from agent.nodes.doc_retriever import doc_retriever
from agent.nodes.deep_reasoner import deep_reasoner_sync
from agent.nodes.solution_provider import solution_provider
from agent.nodes.clarification_asker import clarification_asker_sync
from agent.nodes.escalation_handler import escalation_handler
from agent.logger import get_logger


def route_after_reasoning(state: ConversationState) -> Literal["solution", "clarification", "escalation"]:
    """
    Route after deep reasoning based on results.
    
    Returns:
        Next node name
    """
    if state.get("needs_clarification"):
        return "clarification"
    elif state.get("should_escalate"):
        return "escalation"
    else:
        return "solution"


def create_agent_graph() -> StateGraph:
    """
    Create the LangGraph workflow for the Slack agent.
    
    Workflow:
    1. Analyze Intent
    2. Build Context (load user history + thread)
    3. Retrieve Documentation
    4. Deep Reasoning (multi-iteration)
    5. Route to:
       - Solution Provider (if confident)
       - Clarification Asker (if needs more info)
       - Escalation Handler (if can't handle)
    """
    logger = get_logger()
    logger.logger.info("Creating agent graph...")
    
    # Create graph
    workflow = StateGraph(ConversationState)
    
    # Add nodes
    workflow.add_node("analyze_intent", analyze_intent_sync)
    workflow.add_node("build_context", build_context)
    workflow.add_node("retrieve_docs", doc_retriever)
    workflow.add_node("deep_reasoning", deep_reasoner_sync)
    workflow.add_node("solution", solution_provider)
    workflow.add_node("clarification", clarification_asker_sync)
    workflow.add_node("escalation", escalation_handler)
    
    # Set entry point
    workflow.set_entry_point("analyze_intent")
    
    # Add edges
    workflow.add_edge("analyze_intent", "build_context")
    workflow.add_edge("build_context", "retrieve_docs")
    workflow.add_edge("retrieve_docs", "deep_reasoning")
    
    # Conditional routing after reasoning
    workflow.add_conditional_edges(
        "deep_reasoning",
        route_after_reasoning,
        {
            "solution": "solution",
            "clarification": "clarification",
            "escalation": "escalation"
        }
    )
    
    # All paths end after their respective handlers
    workflow.add_edge("solution", END)
    workflow.add_edge("clarification", END)
    workflow.add_edge("escalation", END)
    
    logger.logger.info("Agent graph created successfully")
    
    return workflow.compile()


# Global graph instance
_graph = None


def get_agent_graph():
    """Get or create the global agent graph."""
    global _graph
    if _graph is None:
        _graph = create_agent_graph()
    return _graph
