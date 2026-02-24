"""
Low Confidence Tagger Node — Tags the most suitable team member when agent confidence < 50%.

This node:
  1. Analyzes the user's question carefully
  2. Matches it against team member expertise from olake-team.json
  3. Tags the single most relevant person using Slack mention format (@username)
  4. Does NOT attempt to answer or ask clarifying questions
"""

from typing import Dict, Any
import json
from datetime import datetime

from agent.state import ConversationState, ConversationRecord
from agent.slack_client import create_slack_client
from agent.persistence import get_database
from agent.logger import get_logger
from agent.team_resolver import (
    get_all_members_flat,
    resolve_mention,
    load_team,
)
from agent.llm import get_chat_completion


def _build_system_prompt(team_data: dict) -> str:
    """Build the system prompt with team data injected dynamically."""
    team_data_json = json.dumps(team_data, indent=2)
    
    # Build matching guidelines from team data
    guidelines = []
    for dept, members in team_data.items():
        for name, info in members.items():
            desc = info.get("desc", "")
            role = info.get("role", "")
            if desc:
                # Extract key topics from description
                guidelines.append(f"  - {desc} → {name}")
    
    guidelines_text = "\n".join(guidelines)
    
    return f"""You are an intelligent routing assistant for OLake's Slack support.

Your ONLY job: Analyze a user's question and tag the ONE most suitable team member to handle it.

RULES:
  1. DO NOT answer the question yourself
  2. DO NOT ask clarifying questions
  3. ONLY output the slack_name of the selected team member - nothing else

TEAM DATA:
{team_data_json}

MATCHING GUIDELINES:
{guidelines_text}
  - If unclear, default to Engineering (first available member)

OUTPUT: Return ONLY the slack_name (e.g., "Deepanshu Pal"). No JSON, no explanation."""


_USER_PROMPT_TEMPLATE = """
USER QUESTION: "{message_text}"

Select the ONE most suitable team member to handle this. Return ONLY their slack_name.
"""


def _parse_tagger_response(text: str | None) -> str:
    """Extract the tagged member name from LLM response."""
    if not text:
        raise ValueError("LLM returned empty response")
    
    # Clean up the response - just get the name
    text = text.strip()
    
    # Remove any quotes if present
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    
    return text


def low_confidence_tagger(state: ConversationState) -> ConversationState:
    """
    Tag the most suitable team member when confidence is below 50%.
    
    This node does NOT answer the question or ask clarifying questions.
    It only analyzes the question and tags the relevant person.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with tagging handled
    """
    logger = get_logger()
    slack_client = create_slack_client()
    db = get_database()
    
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    thread_ts = state.get("thread_ts") or state["message_ts"]
    message_text = state["message_text"]
    
    # Load team data
    team_data = load_team()
    all_members = get_all_members_flat()
    member_names = {m["slack_name"] for m in all_members}
    
    try:
        # Build prompt for LLM to select the best team member
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            message_text=message_text,
        )
        
        # Build system prompt with team data injected
        system_prompt = _build_system_prompt(team_data)

        import asyncio
        import gc

        # Run async completion in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                get_chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,  # Low temperature for consistent selection
                )
            )
        finally:
            loop.run_until_complete(asyncio.sleep(0))
            loop.close()
            asyncio.set_event_loop(None)
            gc.collect()
        
        tagged_member = _parse_tagger_response(response)
        
        # Validate the tagged member exists in team data
        if tagged_member not in member_names:
            logger.logger.warning(
                f"Tagged member '{tagged_member}' not found in team data. Falling back to Engineering."
            )
            # Fallback to first Engineering member
            engineering_members = [m for m in all_members if m["dept"] == "Engineering"]
            if engineering_members:
                tagged_member = engineering_members[0]["slack_name"]
            else:
                tagged_member = "shubham"  # Ultimate fallback
        
        # Build the Slack mention
        mention = resolve_mention(tagged_member)
        
        # Build the tagging message - simple and direct
        tagging_message = f"Hey {mention}, please look into this."
        
        response_blocks = slack_client.format_response_blocks(
            response_text=tagging_message,
            confidence=state.get("final_confidence", 0.0),
            docs_cited=None,
            is_clarification=False,
            is_escalation=False,
        )
        
        # Reply in-thread
        slack_client.send_message(
            channel=channel_id,
            text=tagging_message,
            thread_ts=thread_ts,
            blocks=response_blocks,
        )
        
        # Add a flag reaction to indicate this needs attention
        try:
            slack_client.add_reaction(
                channel=channel_id,
                timestamp=state["message_ts"],
                emoji="flag",
            )
        except Exception:
            pass  # Reaction failure is non-critical
        
        state["response_text"] = tagging_message
        state["response_blocks"] = response_blocks
        
        logger.logger.info(
            f"[LowConfidenceTagger] Tagged {tagged_member} — "
            f"confidence={state.get('final_confidence', 0.0):.2f}"
        )
        
        # Log the tagging action
        logger.log_escalation(
            user_id=user_id,
            channel_id=channel_id,
            reason=f"Low confidence ({state.get('final_confidence', 0.0):.2f}) — tagged {tagged_member}",
            original_message=message_text,
            thread_ts=thread_ts,
        )
        
        # Save conversation record
        processing_time = (datetime.now() - state["processing_start_time"]).total_seconds()
        
        db.save_conversation(
            ConversationRecord(
                id=None,
                message_ts=state["message_ts"],
                thread_ts=thread_ts,
                channel_id=channel_id,
                user_id=user_id,
                message_text=message_text,
                intent_type=state["intent_type"].value if state.get("intent_type") else "unknown",
                urgency=state["urgency"].value if state.get("urgency") else "medium",
                response_text=tagging_message,
                confidence=state.get("final_confidence", 0.0),
                needs_clarification=False,
                escalated=True,
                escalation_reason=f"Tagged {tagged_member}",
                docs_cited=None,
                reasoning_summary=f"Tagged {tagged_member}",
                processing_time=processing_time,
                created_at=state["processing_start_time"],
                resolved=False,
                resolved_at=None,
            )
        )
        
    except Exception as e:
        logger.log_error(
            error_type="LowConfidenceTaggerError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        state["error"] = str(e)
        # Fallback: tag CTO as ultimate escalation
        state["response_text"] = f"Flagging this for {resolve_mention('shubham')} to review."
    
    return state
