"""
Clarification Asker Node - Asks user for more information.
"""

from typing import Dict, Any
import json
from datetime import datetime

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger, EventType
from agent.llm import get_chat_completion


async def clarification_asker(state: ConversationState) -> Dict[str, Any]:
    """
    Ask user for clarification when more information is needed.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with clarification sent
    """
    logger = get_logger()
    slack_client = create_slack_client()
    db = get_database()
    
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts") or state["message_ts"]
    message_text = state["message_text"]
    reasoning_iterations = state.get("reasoning_iterations", [])
    
    try:
        # Add thinking emoji
        slack_client.add_reaction(
            channel=channel_id,
            timestamp=state["message_ts"],
            emoji="thinking_face"
        )
        
        # Generate clarification questions
        identified_gaps = []
        for iteration in reasoning_iterations:
            identified_gaps.extend(iteration.identified_gaps)
        
        prompt = f"""Based on this user's question and the identified gaps, generate 2-3 clarifying questions.

User Question: "{message_text}"

Identified Gaps:
{json.dumps(identified_gaps, indent=2)}

Generate questions that will help you provide a better answer. Be specific and concise.

Return JSON:
{{
    "clarification_message": "A friendly message explaining why you need more info",
    "questions": ["question 1?", "question 2?", "question 3?"]
}}
"""
        
        response = await get_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        
        clarification = json.loads(response)
        
        # Format clarification message
        questions_text = "\n".join([
            f"{i+1}. {q}"
            for i, q in enumerate(clarification["questions"])
        ])
        
        full_message = f"""{clarification["clarification_message"]}

{questions_text}

_Just reply in this thread with the answers!_"""
        
        # Format with Block Kit
        response_blocks = slack_client.format_response_blocks(
            response_text=full_message,
            confidence=0.0,
            docs_cited=None,
            is_clarification=True,
            is_escalation=False
        )
        
        # Send clarification request
        slack_client.send_message(
            channel=channel_id,
            text=full_message,
            thread_ts=thread_ts,
            blocks=response_blocks
        )
        
        state["response_text"] = full_message
        state["response_blocks"] = response_blocks
        state["clarification_questions"] = clarification["questions"]
        
        # Log clarification
        logger.log_event(
            event_type=EventType.CLARIFICATION_NEEDED,
            message=f"Asked {len(clarification['questions'])} clarification questions",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            metadata={
                "questions": clarification["questions"],
                "identified_gaps": identified_gaps
            }
        )
        
        # Save to database
        processing_time = (
            (datetime.now() - state["processing_start_time"]).total_seconds()
        )
        
        conversation_record = ConversationRecord(
            id=None,
            message_ts=state["message_ts"],
            thread_ts=thread_ts,
            channel_id=channel_id,
            user_id=user_id,
            message_text=state["message_text"],
            intent_type=state["intent_type"].value if state.get("intent_type") else "unknown",
            urgency=state["urgency"].value if state.get("urgency") else "medium",
            response_text=full_message,
            confidence=state.get("final_confidence", 0.0),
            needs_clarification=True,
            escalated=False,
            escalation_reason=None,
            docs_cited=None,
            reasoning_summary=json.dumps(identified_gaps),
            processing_time=processing_time,
            created_at=state["processing_start_time"],
            resolved=False,
            resolved_at=None
        )
        
        db.save_conversation(conversation_record)
        
    except Exception as e:
        logger.log_error(
            error_type="ClarificationAskerError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        state["error"] = str(e)
    
    return state


def clarification_asker_sync(state: ConversationState) -> ConversationState:
    """Synchronous wrapper for LangGraph compatibility."""
    import asyncio
    return asyncio.run(clarification_asker(state))
