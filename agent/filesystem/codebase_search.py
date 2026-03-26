"""
Minimal codebase search utilities for the deep researcher.

Design:
- Search with ripgrep JSON output
- Return lightweight structured hits
- Read bounded file ranges safely for context
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPOS_ROOT = Path.cwd() / ".github_repos"
_DEFAULT_TIMEOUT_SECONDS = 45


class RgSearchError(Exception):
    """Raised when ripgrep exits with an error (exit code 2)."""


@dataclass
class SearchHit:
    """A single ripgrep match with surrounding context."""

    path: str
    line: int
    text: str
    context: str


def _resolve_repo_path(path: str) -> Path:
    """
    Resolve path under .github_repos and prevent directory traversal.
    Accepts values like: 'olake', 'olake/pkg/waljs', 'olake-ui/src'.
    Use the reserved alias 'all' to search across every cloned repo at once.
    """
    raw = (path or "").strip().lstrip("/")
    if not raw:
        raise ValueError("path cannot be empty")

    # Reserved alias: search the entire repos root (all cloned repos at once).
    if raw == "all":
        return _REPOS_ROOT.resolve()

    candidate = (_REPOS_ROOT / raw).resolve()
    root = _REPOS_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError(f"path escapes repos root: {path}")
    return candidate


def _run_rg_json(args: list[str], cwd: Path) -> list[dict]:
    """
    Run rg and parse --json lines.
    rg exit codes:
      0 = matches found
      1 = no matches
      2 = error

    On exit code 2, returns a single sentinel event {"type": "rg_error", "data": {"text": stderr}}
    so callers can surface the error in search history rather than silently returning 0 results.
    """
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_DEFAULT_TIMEOUT_SECONDS,
    )

    if result.returncode == 1:
        return []
    if result.returncode == 2:
        stderr = (result.stderr or "").strip()
        log.warning("[codebase_search] rg error: %s", stderr[:300])
        return [{"type": "rg_error", "data": {"text": stderr[:300]}}]

    events: list[dict] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _check_rg_error(events: list[dict]) -> None:
    """Raise RgSearchError if events contain a sentinel rg error event."""
    for ev in events:
        if ev.get("type") == "rg_error":
            msg = ev.get("data", {}).get("text", "rg error (no details)")
            raise RgSearchError(msg)


def _extract_matches(events: list[dict]) -> list[tuple[str, int, str]]:
    """Extract (path, line_number, matched_line_text) from rg JSON events."""
    out: list[tuple[str, int, str]] = []
    for ev in events:
        if ev.get("type") != "match":
            continue
        data = ev.get("data", {})
        file_path = data.get("path", {}).get("text", "")
        line_number = int(data.get("line_number", 0) or 0)
        line_text = (data.get("lines", {}).get("text", "") or "").rstrip("\n")
        if file_path and line_number > 0:
            out.append((file_path, line_number, line_text))
    return out


def _build_context(path: str, line: int, context_lines: int) -> str:
    """Read file and return +/- context_lines around a specific match line."""
    full_path = _resolve_repo_path(path)
    try:
        lines = full_path.read_text(errors="replace").splitlines()
    except Exception:
        return ""

    start = max(1, line - context_lines)
    end = min(len(lines), line + context_lines)
    return "\n".join(f"{i}|{lines[i - 1]}" for i in range(start, end + 1))


def search_code(
    pattern: str,
    path: str,
    file_type: Optional[str] = None,
    context_lines: int = 15,
) -> list[SearchHit]:
    """
    Search code with ripgrep.

    Equivalent shape:
      rg {pattern} {path} -n -C {context_lines} [-t {file_type}] --json
    """
    target = _resolve_repo_path(path)
    args = ["rg", pattern, str(target), "-n", "-C", str(context_lines), "--json"]
    if file_type:
        args.extend(["-t", file_type])

    events = _run_rg_json(args=args, cwd=_REPOS_ROOT)
    _check_rg_error(events)
    matches = _extract_matches(events)

    hits: list[SearchHit] = []
    for file_path, line, text in matches:
        rel = str(Path(file_path))
        # rg may emit absolute or relative paths depending on invocation details
        if Path(rel).is_absolute():
            try:
                rel = str(Path(rel).resolve().relative_to(_REPOS_ROOT.resolve()))
            except Exception:
                pass
        hits.append(
            SearchHit(
                path=rel,
                line=line,
                text=text,
                context=_build_context(rel, line, context_lines),
            )
        )
    return hits


def find_files_with_symbol(symbol: str, path: str) -> list[str]:
    """
    Find file paths containing an exact symbol.

    Equivalent shape:
      rg \\b{symbol}\\b {path} -l --json
    """
    target = _resolve_repo_path(path)
    pattern = rf"\b{re.escape(symbol)}\b"
    args = ["rg", pattern, str(target), "-l", "--json"]
    events = _run_rg_json(args=args, cwd=_REPOS_ROOT)
    _check_rg_error(events)

    files: list[str] = []
    for ev in events:
        if ev.get("type") != "begin":
            continue
        file_path = ev.get("data", {}).get("path", {}).get("text", "")
        if not file_path:
            continue
        rel = str(Path(file_path))
        if Path(rel).is_absolute():
            try:
                rel = str(Path(rel).resolve().relative_to(_REPOS_ROOT.resolve()))
            except Exception:
                pass
        files.append(rel)
    # keep stable order + dedupe
    return list(dict.fromkeys(files))


def find_definitions(symbol: str, path: str, lang: str) -> list[SearchHit]:
    """
    Find likely definitions for a symbol using a declaration-style regex.

    Equivalent shape:
      rg "^(func|type|class|def|export (function|class|const)) .*{symbol}" \
         {path} -t {lang} -n -C 3 --json
    """
    target = _resolve_repo_path(path)
    decl_pattern = (
        r"^(func|type|class|def|export (function|class|const)) .*"
        + re.escape(symbol)
    )
    args = [
        "rg",
        decl_pattern,
        str(target),
        "-t",
        lang,
        "-n",
        "-C",
        "3",
        "--json",
    ]
    events = _run_rg_json(args=args, cwd=_REPOS_ROOT)
    _check_rg_error(events)
    matches = _extract_matches(events)
    hits: list[SearchHit] = []
    for file_path, line, text in matches:
        rel = str(Path(file_path))
        if Path(rel).is_absolute():
            try:
                rel = str(Path(rel).resolve().relative_to(_REPOS_ROOT.resolve()))
            except Exception:
                pass
        hits.append(
            SearchHit(
                path=rel,
                line=line,
                text=text,
                context=_build_context(rel, line, 3),
            )
        )
    return hits


def read_file(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_lines: int = 300,
) -> str:
    """
    Read file lines safely with a hard line cap.

    - Default when range is omitted: read lines 1..max_lines
    - Hard cap always enforced to protect token budget
    - Returns line-numbered content like: "42|the line text"
    """
    if max_lines <= 0:
        raise ValueError("max_lines must be > 0")

    full_path = _resolve_repo_path(path)
    lines = full_path.read_text(errors="replace").splitlines()
    total = len(lines)

    start = 1 if start_line is None else max(1, int(start_line))
    if end_line is None:
        end = start + max_lines - 1
    else:
        end = int(end_line)

    if end < start:
        raise ValueError("end_line must be >= start_line")

    actual_end = min(total, end, start + max_lines - 1)
    truncated = actual_end < min(total, end)
    # also truncated if no end_line and file longer than default window
    if end_line is None and total > actual_end:
        truncated = True

    snippet = "\n".join(
        f"{i}|{lines[i - 1]}" for i in range(start, actual_end + 1)
    )
    if truncated:
        snippet += (
            f"\n[Truncated: showing lines {start}-{actual_end} of {total}. "
            "Use read_file with a narrower range to see more.]"
        )
    return snippet
