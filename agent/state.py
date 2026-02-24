"""
State management for OLake Slack Community Agent.

Defines state schema for conversation handling with LangGraph.
"""

from typing import TypedDict, List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class IntentType(Enum):
    """Types of user intents."""
    QUESTION = "question"
    ISSUE = "issue"
    DISCUSSION = "discussion"
    FEEDBACK = "feedback"
    UNKNOWN = "unknown"


class UrgencyLevel(Enum):
    """Urgency levels for issues."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class UserProfile:
    """User profile with interaction history."""
    user_id: str
    username: str
    real_name: str
    email: Optional[str]
    total_messages: int
    common_topics: List[str]
    resolved_issues: int
    unresolved_issues: int
    avg_resolution_time: float  # in minutes
    last_interaction: Optional[datetime]
    knowledge_level: str  # "beginner", "intermediate", "advanced"
    

@dataclass
class RetrievedDocument:
    """A retrieved documentation chunk."""
    title: str
    content: str
    url: str
    relevance_score: float
    source_type: str  # "docs", "github", "stackoverflow", etc.


@dataclass
class ReasoningIteration:
    """A single iteration of the reasoning process."""
    iteration: int
    thought_process: str
    confidence: float
    decision: str            # "ANSWER" | "CLARIFY" | "RETRIEVE_MORE"
    needs_more_docs: bool
    needs_clarification: bool
    identified_gaps: List[str]
    new_search_queries: List[str]


class ConversationState(TypedDict):
    """
    State for the Slack community agent conversation graph.
    
    This state is passed between nodes in the LangGraph workflow.
    """
    # Slack event data
    event: Dict[str, Any]  # Raw Slack event
    channel_id: str
    user_id: str
    message_text: str
    thread_ts: Optional[str]  # Thread timestamp for replies
    message_ts: str  # Message timestamp
    
    # User context
    user_profile: Optional[UserProfile]
    previous_messages: List[Dict[str, Any]]  # User's message history
    thread_context: List[Dict[str, Any]]  # Messages in current thread
    
    # Intent analysis
    intent_type: Optional[IntentType]
    urgency: Optional[UrgencyLevel]
    key_topics: List[str]
    technical_terms: List[str]
    
    # Documentation search
    search_queries: List[str]
    retrieved_docs: List[RetrievedDocument]
    docs_relevance_score: float

    # Problem decomposition (from problem_decomposer)
    problem_summary: Optional[str]        # one-sentence restatement of the issue
    sub_questions: List[str]              # decomposed sub-questions
    is_ambiguous: bool                    # True if issue cannot be partially diagnosed

    # Iterative retrieval loop
    retrieval_iterations: int             # how many retrieval rounds have run
    max_retrieval_iterations: int         # cap (default 3)
    new_search_queries: List[str]         # queries from reasoner for next retrieval
    retrieval_history: List[str]          # all queries run so far (dedup across rounds)
    retrieval_summaries: List[Dict[str, Any]]  # summary of what was retrieved each iteration

    # Reasoning process
    reasoning_iterations: List[ReasoningIteration]
    current_iteration: int
    final_confidence: float
    solution_found: bool
    reasoning_trace: Optional[str]        # deep_reasoner chain-of-thought (logged)
    reasoner_decision: Optional[str]      # "ANSWER" | "CLARIFY" | "RETRIEVE_MORE"
    
    # Response generation
    needs_clarification: bool
    clarification_questions: List[str]
    should_escalate: bool
    escalation_reason: Optional[str]
    response_text: Optional[str]
    response_blocks: Optional[List[Dict[str, Any]]]

    # Org-member guard
    org_member_replied: bool  # True when an org team member is in the thread → bot silences
    doc_sufficient: bool       # True when retrieved docs score above DOCS_ANSWER_THRESHOLD
    rag_service_available: Optional[bool]  # None=unknown, True=up, False=using keyword fallback
    # Metadata
    processing_start_time: datetime
    processing_end_time: Optional[datetime]
    total_processing_time: Optional[float]  # in seconds
    error: Optional[str]


@dataclass
class ConversationRecord:
    """Record of a conversation for database storage."""
    id: Optional[int]
    message_ts: str
    thread_ts: Optional[str]
    channel_id: str
    user_id: str
    message_text: str
    intent_type: str
    urgency: str
    response_text: Optional[str]
    confidence: float
    needs_clarification: bool
    escalated: bool
    escalation_reason: Optional[str]
    docs_cited: Optional[str]  # JSON string
    reasoning_summary: Optional[str]
    processing_time: float
    created_at: datetime
    resolved: bool
    resolved_at: Optional[datetime]


@dataclass
class UserInteraction:
    """Record of a user interaction for profiling."""
    id: Optional[int]
    user_id: str
    message_ts: str
    channel_id: str
    topic: str
    resolved: bool
    resolution_time: Optional[float]  # in minutes
    created_at: datetime


def create_initial_state(event: Dict[str, Any]) -> ConversationState:
    """
    Create initial conversation state from Slack event.
    
    Args:
        event: Slack event dict
        
    Returns:
        Initial ConversationState
    """
    message_event = event.get("event", {})
    
    return ConversationState(
        # Event data
        event=event,
        channel_id=message_event.get("channel", ""),
        user_id=message_event.get("user", ""),
        message_text=message_event.get("text", ""),
        thread_ts=message_event.get("thread_ts"),
        message_ts=message_event.get("ts", ""),
        
        # User context
        user_profile=None,
        previous_messages=[],
        thread_context=[],
        
        # Intent analysis
        intent_type=None,
        urgency=None,
        key_topics=[],
        technical_terms=[],
        
        # Documentation search
        search_queries=[],
        retrieved_docs=[],
        docs_relevance_score=0.0,

        # Problem decomposition
        problem_summary=None,
        sub_questions=[],
        is_ambiguous=False,

        # Iterative retrieval
        retrieval_iterations=0,
        max_retrieval_iterations=3,
        new_search_queries=[],
        retrieval_history=[],
        retrieval_summaries=[],

        # Reasoning
        reasoning_iterations=[],
        current_iteration=0,
        final_confidence=0.0,
        solution_found=False,
        reasoning_trace=None,
        reasoner_decision=None,
        
        # Response
        needs_clarification=False,
        clarification_questions=[],
        should_escalate=False,
        escalation_reason=None,
        response_text=None,
        response_blocks=None,

        # Org-member guard
        org_member_replied=False,
        doc_sufficient=False,
        rag_service_available=None,

        # Metadata
        processing_start_time=datetime.now(),
        processing_end_time=None,
        total_processing_time=None,
        error=None
    )
