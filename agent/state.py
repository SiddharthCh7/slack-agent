"""
State management for OLake Slack Community Agent.

Defines state schema for conversation handling with LangGraph.
"""

from typing import TypedDict, List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ResearchFile:
    """A file retrieved during codebase research."""
    path: str
    content: str
    matches: List[str]        # matching lines/snippets
    retrieval_reason: str     # why this file was retrieved
    search_pattern: Optional[str] = None  # pattern used for retrieval


class ConversationState(TypedDict):
    """
    State for the Slack community agent conversation graph.

    All fields use LangGraph's default last-write-wins reducer.
    No add_messages — that reducer is only for LangChain message objects.
    """
    # Slack event data
    event: Dict[str, Any]
    channel_id: str
    user_id: str
    user_query: str
    thread_ts: Optional[str]
    message_ts: str

    # Thread context loaded from DB by context_builder
    # Each item: {role, content, message_ts}
    thread_context: List[Dict[str, Any]]
    thread_summary: Optional[str]

    # Gate filter signals (set by gate_filter node)
    is_relevant: bool
    is_actionable: bool
    is_harmful: bool
    question_type: Optional[str]    # conceptual|how-to|bug-report|feature-request
    block_reason: Optional[str]

    # Signals set by deep_researcher
    is_conceptual: bool

    # Deep Research results
    thinking_log: List[str]
    search_history: List[str]
    research_files: List[ResearchFile]
    research_summary: Optional[str]   # compact summary of what was searched + null results
    research_done: bool

    # Response generation
    response_text: Optional[str]

    # Org-member guard (set by context_builder; if True the bot stays silent)
    org_member_replied: bool

    # Metadata
    processing_start_time: datetime
    error: Optional[str]


def create_initial_state(event: Dict[str, Any]) -> ConversationState:
    """Create initial conversation state from a Slack event dict."""
    message_event = event.get("event", {})

    return ConversationState(
        event=event,
        channel_id=message_event.get("channel", ""),
        user_id=message_event.get("user", ""),
        user_query=message_event.get("text", ""),
        thread_ts=message_event.get("thread_ts"),
        message_ts=message_event.get("ts", ""),

        thread_context=[],
        thread_summary=None,

        is_relevant=True,
        is_actionable=True,
        is_harmful=False,
        question_type=None,
        block_reason=None,
        is_conceptual=False,

        thinking_log=[],
        search_history=[],
        research_files=[],
        research_summary=None,
        research_done=False,

        response_text=None,

        org_member_replied=False,

        processing_start_time=datetime.now(),
        error=None,
    )
