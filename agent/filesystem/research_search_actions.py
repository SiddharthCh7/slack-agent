"""
Execution of planner search actions (search_code, find_definitions, find_files_with_symbol).

Used by the deep researcher; search actions run in a thread pool in parallel.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.filesystem.codebase_search import SearchHit, find_definitions, find_files_with_symbol, search_code
from agent.state import ResearchFile


def action_to_label(action: Dict[str, Any]) -> str:
    tool = action.get("tool", "")
    if tool == "search_code":
        return (
            f'search_code("{action.get("pattern", "")}", "{action.get("path", "")}", '
            f'file_type="{action.get("file_type")}", context_lines={action.get("context_lines", 15)})'
        )
    if tool == "find_files_with_symbol":
        return f'find_files_with_symbol("{action.get("symbol", "")}", "{action.get("path", "")}")'
    if tool == "find_definitions":
        return f'find_definitions("{action.get("symbol", "")}", "{action.get("path", "")}", "{action.get("lang", "")}")'
    if tool == "read_file":
        return (
            f'read_file("{action.get("path", "")}", {action.get("start_line")}, '
            f'{action.get("end_line")})'
        )
    return f"unknown_tool({tool})"


def group_hits_to_research_files(
    hits: List[SearchHit],
    tool_label: str,
    search_pattern: str,
) -> List[ResearchFile]:
    grouped: Dict[str, List[SearchHit]] = {}
    for h in hits:
        grouped.setdefault(h.path, []).append(h)

    files: List[ResearchFile] = []
    for path, file_hits in grouped.items():
        file_hits = sorted(file_hits, key=lambda x: x.line)
        content_chunks = [h.context for h in file_hits[:8] if h.context]
        content = "\n\n".join(content_chunks)
        matches = [f"{h.line}|{h.text}" for h in file_hits[:15]]
        files.append(
            ResearchFile(
                path=path,
                content=content,
                matches=matches,
                retrieval_reason=f"Found via {tool_label}",
                search_pattern=search_pattern,
            )
        )
    return files


def execute_search_action(
    action: Dict[str, Any],
    iteration: int,
) -> tuple[Dict[str, Any], List[ResearchFile], str]:
    tool = action.get("tool")
    label = action_to_label(action)
    if tool == "search_code":
        hits = search_code(
            pattern=action.get("pattern", ""),
            path=action.get("path", "all"),
            file_type=action.get("file_type"),
            context_lines=int(action.get("context_lines", 15)),
        )
        files = group_hits_to_research_files(
            hits=hits,
            tool_label=label,
            search_pattern=str(action.get("pattern", "")),
        )
        if not hits:
            block = f"Iteration {iteration} — {label}\n  → 0 results"
        else:
            preview = "\n".join(
                f"  {h.path}:{h.line}  → {h.text[:250]}"
                for h in hits[:8]
            )
            block = f"Iteration {iteration} — {label}\n{preview}"
        return action, files, block

    if tool == "find_definitions":
        hits = find_definitions(
            symbol=action.get("symbol", ""),
            path=action.get("path", "all"),
            lang=action.get("lang", "go"),
        )
        files = group_hits_to_research_files(
            hits=hits,
            tool_label=label,
            search_pattern=str(action.get("symbol", "")),
        )
        if not hits:
            block = f"Iteration {iteration} — {label}\n  → 0 results"
        else:
            preview = "\n".join(
                f"  {h.path}:{h.line}  → {h.text[:250]}"
                for h in hits[:8]
            )
            block = f"Iteration {iteration} — {label}\n{preview}"
        return action, files, block

    if tool == "find_files_with_symbol":
        files_found = find_files_with_symbol(
            symbol=action.get("symbol", ""),
            path=action.get("path", "all"),
        )
        files: List[ResearchFile] = []
        for p in files_found[:20]:
            files.append(
                ResearchFile(
                    path=p,
                    content="",
                    matches=[f"symbol: {action.get('symbol', '')}"],
                    retrieval_reason=f"Found via {label}",
                    search_pattern=str(action.get("symbol", "")),
                )
            )
        if not files_found:
            block = f"Iteration {iteration} — {label}\n  → 0 results"
        else:
            preview = "\n".join(f"  {p}" for p in files_found[:5])
            block = f"Iteration {iteration} — {label}\n{preview}"
        return action, files, block

    return action, [], f"Iteration {iteration} — {label}\n  → unsupported tool"
