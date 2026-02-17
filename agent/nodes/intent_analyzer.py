"""
Intent Analyzer Node - Classifies user message intent and urgency.
"""

from typing import Dict, Any
import json

from agent.state import ConversationState, IntentType, UrgencyLevel
from agent.llm import get_chat_completion
from agent.logger import get_logger, EventType
from agent.config import Config


async def analyze_intent(state: ConversationState) -> Dict[str, Any]:
    """
    Analyze the intent and urgency of the user's message.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with intent classification
    """
    logger = get_logger()
    
    message_text = state["message_text"]
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    
    # Create intent analysis prompt
    prompt = f"""Analyze this Slack message from a user in the OLake community channel.

Message: "{message_text}"

Classify the message:
1. **Intent Type**: question, issue, discussion, feedback, or unknown
2. **Urgency Level**: low, medium, high, or critical
3. **Key Topics**: List of main topics mentioned (e.g., ["CDC", "PostgreSQL", "installation"])
4. **Technical Terms**: List of technical terms used

Return your analysis in JSON format:
{{
    "intent_type": "...",
    "urgency": "...",
    "key_topics": [...],
    "technical_terms": [...],
    "reasoning": "Brief explanation of your classification"
}}

Guidelines:
- "question": User is asking how to do something
- "issue": User is reporting a problem or error
- "discussion": User wants to discuss a topic or provide feedback
- "feedback": User is sharing their experience or suggesting improvements

- "critical": Production system down, data loss, security issue
- "high": Blocking issue preventing work
- "medium": Important but not blocking
- "low": General questions, discussions
"""
    
    try:
        response = await get_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        
        # Parse response
        analysis = json.loads(response)
        
        # Update state
        state["intent_type"] = IntentType(analysis["intent_type"])
        state["urgency"] = UrgencyLevel(analysis["urgency"])
        state["key_topics"] = analysis["key_topics"]
        state["technical_terms"] = analysis["technical_terms"]
        
        # Log the classification
        logger.log_event(
            event_type=EventType.INTENT_CLASSIFIED,
            message=f"Intent: {analysis['intent_type']}, Urgency: {analysis['urgency']}",
            user_id=user_id,
            channel_id=channel_id,
            metadata={
                "intent_type": analysis["intent_type"],
                "urgency": analysis["urgency"],
                "key_topics": analysis["key_topics"],
                "reasoning": analysis["reasoning"]
            }
        )
        
    except Exception as e:
        logger.log_error(
            error_type="IntentAnalysisError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        
        # Fallback to defaults
        state["intent_type"] = IntentType.UNKNOWN
        state["urgency"] = UrgencyLevel.MEDIUM
        state["key_topics"] = []
        state["technical_terms"] = []
    
    return state


def analyze_intent_sync(state: ConversationState) -> ConversationState:
    """Synchronous wrapper for LangGraph compatibility."""
    import asyncio
    return asyncio.run(analyze_intent(state))
