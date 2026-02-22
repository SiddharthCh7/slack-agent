"""
Deep Reasoner Node — iterative reasoning with explicit ANSWER/CLARIFY/RETRIEVE_MORE decisions.

Redesign vs original:
  - Outputs a structured decision (ANSWER | CLARIFY | RETRIEVE_MORE) each iteration
  - If RETRIEVE_MORE → sets new_search_queries for the next doc_retriever pass
  - If CLARIFY → sets clarification_questions (passed to clarification_asker)
  - If ANSWER → sets response_text draft (passed to solution_provider for formatting)
  - Reasoning trace is stored (logged, not shown to user)
  - Thread-aware: uses prior bot Q&A in thread before deciding to clarify again
  - Alex persona: thinks as a senior OLake support engineer
"""

from __future__ import annotations
import asyncio
import json
import re
from typing import Dict, Any, List

from agent.state import ConversationState, ReasoningIteration
from agent.llm import get_chat_completion
from agent.logger import get_logger
from agent.config import Config, OLAKE_CONTEXT


_PARSE_RE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

THREAD_CONTEXT_LIMIT = 15
MAX_ITERATIONS = 3


def _parse_json(text: str | None) -> dict:
    """Parse LLM JSON with progressive fallbacks for truncated responses."""
    if not text:
        raise ValueError("LLM returned empty response")
    text = _PARSE_RE_FENCE.sub("", text.strip())

    # 1. Happy path
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Truncation repair: the most common failure is the JSON getting cut mid-string.
    #    Try closing unclosed braces/brackets/quotes.
    repaired = text
    if not repaired.endswith("}"):
        # Count open quotes to decide if we're inside a string
        open_strings = repaired.count('"') % 2
        if open_strings:
            repaired += '"'       # close the open string
        repaired += '}'           # close the object
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # 3. Regex extraction as last resort — pull individual fields
    result: dict = {}
    for field, pattern in [
        ("decision",   r'"decision"\s*:\s*"(ANSWER|CLARIFY|RETRIEVE_MORE)"'),
        ("confidence", r'"confidence"\s*:\s*([0-9.]+)'),
    ]:
        m = re.search(pattern, text)
        if m:
            val = m.group(1)
            result[field] = float(val) if field == "confidence" else val

    if "decision" in result:
        result.setdefault("confidence", 0.4)
        result.setdefault("reasoning_trace", "[truncated by token limit]")
        return result

    raise ValueError(f"Cannot parse LLM JSON even after repair: {text[:200]!r}")


_SYSTEM_PROMPT = f"""You are Alex, a senior support engineer at OLake/Datazip.

About OLake:
{OLAKE_CONTEXT.strip()}

Your job: given a user's message, retrieved documentation, and thread context,
decide the best next action and produce a structured JSON output.

DECISION OPTIONS:
  "ANSWER"         — you have enough context to give a complete, accurate answer
  "CLARIFY"        — you need specific information from the user to proceed
  "RETRIEVE_MORE"  — you know which additional docs to look for; retrieve before answering

RULES:
  1. Prefer ANSWER over CLARIFY whenever possible. A partial answer with a follow-up note
     is better than making the user wait for information you might not need.
  2. Only choose CLARIFY if missing user-specific info (version, config, error log) that
     is genuinely required and cannot be inferred from the docs.
  3. Only choose RETRIEVE_MORE if you can name specific topics/sections not yet retrieved.
     Do NOT use it to delay answering.
  4. If the thread already contains bot questions + user answers, use those answers.
     Do NOT ask the same question twice.
  5. Max 2 clarification questions. Make them specific, not compound.
  6. Confidence: 0.0–1.0 reflecting how complete your answer is with current context.

OUTPUT FORMAT (always valid JSON, no markdown fences):
{{
  "decision": "ANSWER" | "CLARIFY" | "RETRIEVE_MORE",
  "confidence": 0.0–1.0,
  "reasoning_trace": "Your step-by-step thinking (private, not shown to user)",
  "proposed_answer": "Draft answer in human-professional tone (only when decision=ANSWER)",
  "clarification_questions": ["Q1?", "Q2?"],  // only when decision=CLARIFY, max 2
  "new_search_queries": ["query1", "query2"],  // only when decision=RETRIEVE_MORE, max 4
  "identified_gaps": ["What was missing / what you still need"]
}}"""


def _build_docs_block(docs) -> str:
    if not docs:
        return "No documentation retrieved yet."
    blocks = []
    for i, doc in enumerate(docs[:6], 1):
        title = doc.title if hasattr(doc, "title") else doc.get("title", "")
        content = doc.content if hasattr(doc, "content") else doc.get("content", "")
        url = doc.url if hasattr(doc, "url") else doc.get("url", "")
        score = doc.relevance_score if hasattr(doc, "relevance_score") else doc.get("score", 0)
        blocks.append(
            f"[Doc {i}] {title} (score={score:.2f}, url={url})\n{content[:600]}"
        )
    return "\n\n---\n\n".join(blocks)


def _build_thread_block(thread_context: List[Dict]) -> str:
    if not thread_context:
        return ""
    lines = []
    for msg in thread_context[-THREAD_CONTEXT_LIMIT:]:
        role = "Bot" if msg.get("is_bot") else "User"
        lines.append(f"{role}: {msg.get('text', '')[:300]}")
    return "\n".join(lines)


async def deep_reasoner(state: ConversationState) -> Dict[str, Any]:
    logger = get_logger()
    user_id    = state["user_id"]
    channel_id = state["channel_id"]

    message_text   = state["message_text"]
    problem_summary = state.get("problem_summary") or message_text
    sub_questions  = state.get("sub_questions", [])
    retrieved_docs = state.get("retrieved_docs", [])
    thread_context = state.get("thread_context", [])
    retrieval_iter = state.get("retrieval_iterations", 0)
    max_ret_iter   = state.get("max_retrieval_iterations", 3)
    prev_iterations = state.get("reasoning_iterations", [])
    current_iter   = state.get("current_iteration", 0)

    docs_block   = _build_docs_block(retrieved_docs)
    thread_block = _build_thread_block(thread_context)

    # Build previous reasoning summary if we've looped
    prev_trace = ""
    if prev_iterations:
        last = prev_iterations[-1]
        prev_trace = f"\nPrevious reasoning summary: {last.thought_process[:300]}"

    user_prompt = f"""USER MESSAGE: "{message_text}"
PROBLEM SUMMARY: {problem_summary}

SUB-QUESTIONS TO RESOLVE:
{chr(10).join(f"  - {q}" for q in sub_questions) if sub_questions else "  (none — address message directly)"}

RETRIEVED DOCUMENTATION:
{docs_block}

THREAD HISTORY (most recent last):
{thread_block if thread_block else "(no prior thread)"}

RETRIEVAL ITERATIONS USED: {retrieval_iter}/{max_ret_iter}
{prev_trace}

Analyse. Decide. Output JSON only."""

    try:
        response = await get_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            # max_tokens=3000,   # generous — reasoning_trace can be long
        )
        result = _parse_json(response)

        decision   = result.get("decision", "ANSWER").upper()
        confidence = float(result.get("confidence", 0.5))
        reasoning  = result.get("reasoning_trace", "")
        gaps       = result.get("identified_gaps", [])

        # Clamp decision if retrieval cap reached
        if decision == "RETRIEVE_MORE" and retrieval_iter >= max_ret_iter:
            decision = "CLARIFY" if float(confidence) < 0.5 else "ANSWER"

        # Record iteration
        iteration_record = ReasoningIteration(
            iteration=current_iter + 1,
            thought_process=reasoning,
            confidence=confidence,
            decision=decision,
            needs_more_docs=(decision == "RETRIEVE_MORE"),
            needs_clarification=(decision == "CLARIFY"),
            identified_gaps=gaps,
            new_search_queries=result.get("new_search_queries", []),
        )
        state["reasoning_iterations"] = list(prev_iterations) + [iteration_record]
        state["current_iteration"]    = current_iter + 1
        state["final_confidence"]     = confidence
        state["reasoning_trace"]      = reasoning
        state["reasoner_decision"]    = decision

        if decision == "ANSWER":
            state["solution_found"]       = True
            state["needs_clarification"]  = False
            state["response_text"]        = result.get("proposed_answer", "")

        elif decision == "CLARIFY":
            state["needs_clarification"]   = True
            state["solution_found"]        = False
            raw_qs = result.get("clarification_questions", [])
            state["clarification_questions"] = raw_qs[:2]  # enforce max 2

        elif decision == "RETRIEVE_MORE":
            state["needs_clarification"]  = False
            state["solution_found"]       = False
            new_qs = result.get("new_search_queries", [])
            # Deduplicate against retrieval_history
            history = state.get("retrieval_history", [])
            fresh = [q for q in new_qs if q not in history]
            state["new_search_queries"] = fresh[:4]

        logger.logger.info(
            f"[DeepReasoner] decision={decision} confidence={confidence:.2f} "
            f"iteration={current_iter+1}"
        )

    except Exception as e:
        logger.log_error(
            error_type="DeepReasoningError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id,
        )
        state["reasoner_decision"]    = "ANSWER"
        state["solution_found"]       = False
        state["needs_clarification"]  = False
        state["final_confidence"]     = 0.0
        state["response_text"]        = None

    return state


def deep_reasoner_sync(state: ConversationState) -> ConversationState:
    """Synchronous wrapper for LangGraph."""
    import asyncio
    import gc
    
    # Create a new event loop explicitly to avoid "Event loop is closed" errors
    # from background tasks (e.g., httpx/Qdrant async cleanup)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(deep_reasoner(state))
    finally:
        # Ensure all pending async cleanup happens before closing the loop
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
        asyncio.set_event_loop(None)
        gc.collect()  # Clean up any remaining references
    return result
