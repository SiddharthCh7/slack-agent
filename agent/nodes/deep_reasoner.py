"""
Deep Reasoner Node - Multi-iteration reasoning to analyze the problem deeply.
"""

from typing import Dict, Any
import json

from agent.state import ConversationState, ReasoningIteration
from agent.llm import get_chat_completion
from agent.logger import get_logger
from agent.config import Config, OLAKE_CONTEXT


async def deep_reasoner(state: ConversationState) -> Dict[str, Any]:
    """
    Perform deep, multi-iteration reasoning to determine the best response.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with reasoning results
    """
    logger = get_logger()
    
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    message_text = state["message_text"]
    intent_type = state.get("intent_type")
    retrieved_docs = state.get("retrieved_docs", [])
    user_profile = state.get("user_profile")
    thread_context = state.get("thread_context", [])
    previous_messages = state.get("previous_messages", [])
    
    max_iterations = Config.MAX_REASONING_ITERATIONS if Config.ENABLE_DEEP_REASONING else 1
    
    # Build context for reasoning
    context_str = f"""
## User Message
{message_text}

## Intent
Type: {intent_type.value if intent_type else 'unknown'}

## User Profile
- Knowledge Level: {user_profile.knowledge_level if user_profile else 'unknown'}
- Total Messages: {user_profile.total_messages if user_profile else 0}
- Previous Issues Resolved: {user_profile.resolved_issues if user_profile else 0}

## Thread Context
{_format_thread_context(thread_context)}

## Retrieved Documentation
{_format_docs(retrieved_docs)}

## Previous User Interactions
{_format_previous_messages(previous_messages[:3])}  # Last 3 interactions
"""
    
    reasoning_iterations = []
    current_iteration = 0
    final_confidence = 0.0
    solution_found = False
    needs_clarification = False
    should_escalate = False
    
    try:
        for i in range(max_iterations):
            current_iteration = i + 1
            
            # Build prompt for this iteration
            previous_thoughts = "\n".join([
                f"Iteration {r.iteration}: {r.thought_process} (confidence: {r.confidence:.2f})"
                for r in reasoning_iterations
            ])
            
            iteration_prompt = f"""You are an expert support agent for OLake. Analyze this user's message deeply.

## OLake Context
{OLAKE_CONTEXT}

{context_str}

## Previous Reasoning (if any)
{previous_thoughts if previous_thoughts else "None - this is the first iteration"}

## Your Task
This is iteration {current_iteration} of {max_iterations}.

Analyze the situation and provide:
1. **Thought Process**: Your detailed reasoning about the user's issue
2. **Confidence**: How confident are you in answering this (0.0 to 1.0)
3. **Needs More Docs**: Do you need more documentation to answer? (true/false)
4. **Needs Clarification**: Do you need more info from the user? (true/false)
5. **Identified Gaps**: What information is missing?
6. **Proposed Answer**: If confident enough, provide the answer

Return JSON:
{{
    "thought_process": "...",
    "confidence": 0.0-1.0,
    "needs_more_docs": true/false,
    "needs_clarification": true/false,
    "identified_gaps": ["gap1", "gap2"],
    "proposed_answer": "..." or null
}}

Focus on:
- Is the answer in the documentation?
- Is this a common issue or edge case?
- Does the user's knowledge level affect the explanation?
- Can we solve this or does it need human escalation?
"""
            
            response = await get_chat_completion(
                messages=[{"role": "user", "content": iteration_prompt}],
                temperature=0.4
            )
            
            analysis = json.loads(response)
            
            # Create reasoning iteration record
            iteration_record = ReasoningIteration(
                iteration=current_iteration,
                thought_process=analysis["thought_process"],
                confidence=analysis["confidence"],
                needs_more_docs=analysis["needs_more_docs"],
                needs_clarification=analysis["needs_clarification"],
                identified_gaps=analysis["identified_gaps"]
            )
            
            reasoning_iterations.append(iteration_record)
            
            # Log this iteration
            logger.log_reasoning_iteration(
                iteration=current_iteration,
                thought_process=analysis["thought_process"],
                confidence=analysis["confidence"],
                user_id=user_id,
                channel_id=channel_id
            )
            
            # Check if we can stop reasoning
            if analysis["confidence"] >= Config.CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY:
                final_confidence = analysis["confidence"]
                solution_found = True
                state["response_text"] = analysis.get("proposed_answer")
                break
            
            if analysis["needs_clarification"]:
                needs_clarification = True
                final_confidence = analysis["confidence"]
                break
            
            # If max iterations reached and still low confidence, escalate
            if current_iteration == max_iterations:
                final_confidence = analysis["confidence"]
                if final_confidence < Config.CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY:
                    should_escalate = True
        
        # Update state
        state["reasoning_iterations"] = reasoning_iterations
        state["current_iteration"] = current_iteration
        state["final_confidence"] = final_confidence
        state["solution_found"] = solution_found
        state["needs_clarification"] = needs_clarification
        state["should_escalate"] = should_escalate
        
    except Exception as e:
        logger.log_error(
            error_type="DeepReasoningError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        
        # Fallback: escalate on error
        state["should_escalate"] = True
        state["escalation_reason"] = f"Error during reasoning: {str(e)}"
    
    return state


def deep_reasoner_sync(state: ConversationState) -> ConversationState:
    """Synchronous wrapper for LangGraph compatibility."""
    import asyncio
    return asyncio.run(deep_reasoner(state))


def _format_thread_context(thread_context: list) -> str:
    """Format thread context for prompt."""
    if not thread_context:
        return "No thread context (new message)"
    
    formatted = []
    for msg in thread_context[-5:]:  # Last 5 messages
        formatted.append(f"- {msg.get('user_id', 'unknown')}: {msg.get('message_text', '')[:100]}")
    
    return "\n".join(formatted)


def _format_docs(docs: list) -> str:
    """Format retrieved docs for prompt."""
    if not docs:
        return "No relevant documentation found"
    
    formatted = []
    for i, doc in enumerate(docs[:3], 1):  # Top 3
        formatted.append(f"""
### Doc {i}: {doc.title} (relevance: {doc.relevance_score:.2f})
{doc.content[:500]}...
""")
    
    return "\n".join(formatted)


def _format_previous_messages(messages: list) -> str:
    """Format previous user messages for context."""
    if not messages:
        return "No previous interactions"
    
    formatted = []
    for msg in messages:
        formatted.append(
            f"- {msg.get('message_text', '')[:100]} "
            f"(resolved: {msg.get('resolved', False)})"
        )
    
    return "\n".join(formatted)
