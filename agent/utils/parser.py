from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


# Shared fence matcher for LLM JSON responses wrapped in ``` or ```json fences.
JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.DOTALL)
FENCED_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    re.DOTALL,
)

# Repair LLM outputs that sometimes include an extra trailing quote after numbers
# in JSON numbers, e.g. `"context_lines": 5"` instead of `"context_lines": 5`.
_NUMERIC_TRAILING_QUOTE_AFTER_VALUE_RE = re.compile(
    r'(:\s*\d+)"(?=\s*[,}\]])',
    re.DOTALL,
)


def strip_json_fences(text: str | None) -> str:
    """Remove leading/trailing ``` or ```json fences and surrounding whitespace."""
    if not text:
        return ""
    return JSON_FENCE_RE.sub("", text.strip()).strip()


def _extract_fenced_json_block(text: str | None) -> str:
    """
    Extract the content inside the first ```json / ``` fenced block.

    This is more resilient than strip_json_fences() when the model emits prose
    before/after the fence, or when the closing fence isn't exactly aligned at
    end-of-string.
    """
    if not text:
        return ""
    m = FENCED_JSON_BLOCK_RE.search(text)
    if not m:
        return ""
    return (m.group(1) or "").strip()


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to pull the first well-formed JSON object out of text that may have
    prose before/after it (e.g. the model wrote a paragraph then the JSON).
    Tries three progressively looser strategies before giving up.
    """
    # Strategy 1: text starts right at the JSON object (happy path via caller)
    start = text.find('{')
    if start == -1:
        return None

    # Strategy 2: parse from first '{' to end of string
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        pass

    # Strategy 3: parse from first '{' to last '}'
    end = text.rfind('}')
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Strategy 4: regex for a top-level JSON object (handles trailing prose)
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def parse_llm_json(text: str | None) -> Dict[str, Any]:
    """
    Parse an LLM response that should be a JSON object.

    Handles:
      - Clean JSON response (happy path)
      - JSON wrapped in ```/```json fences
      - Prose preamble before the JSON object (model "thinks out loud")
    """
    if not text:
        raise ValueError("LLM returned empty response")

    # First try: extract the first fenced JSON block, if present.
    fenced = _extract_fenced_json_block(text)
    if fenced:
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            # Fall through to the normal cleaning/extraction logic.
            pass

    # Strip fences first
    cleaned = strip_json_fences(text)

    # Happy path — response is just JSON
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback — model wrote prose then JSON; extract the object
    extracted = _extract_json_object(cleaned)
    if extracted is not None:
        return extracted

    # Also try on raw text in case fences messed up the extraction
    extracted = _extract_json_object(text)
    if extracted is not None:
        return extracted

    return {"error": f"Cannot parse LLM JSON: {text[:300]!r}"}


def parse_planner_json(text: str | None) -> Dict[str, Any]:
    """
    Parse the deep-researcher planner output into a normalised dict.

    Accepts:
      - Direct shape: {"thinking": ..., "search_params": [...], ...}
      - Wrapped shape: {"result": [{...}, {...}]}  (merges all entries)
    """
    base = parse_llm_json(text)

    if "error" in base:
        return base

    if not isinstance(base, dict):
        return {
            "thinking": "",
            "search_intent": "Searching for relevant code.",
            "search_params": [],
            "is_conceptual": False,
        }

    # Unwrap {"result": [...]} shape by merging all entries
    if "result" in base and isinstance(base["result"], list):
        items: List[Dict[str, Any]] = base["result"]
        return {
            "thinking": "\n".join(str(i.get("thinking", "")) for i in items if i.get("thinking")),
            "search_intent": next((str(i["search_intent"]) for i in items if i.get("search_intent")), ""),
            "search_params": [sp for i in items for sp in (i.get("search_params") or [])],
            "is_conceptual": any(bool(i.get("is_conceptual")) for i in items),
        }

    return base


def parse_json_list(text: str | None) -> List[Any]:
    """Parse an LLM response that should be a JSON array."""
    if not text or not text.strip():
        return []
    cleaned = strip_json_fences(text)
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []
