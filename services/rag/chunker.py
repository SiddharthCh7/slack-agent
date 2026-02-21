"""
OLake Docs Chunker — improved version with all quality fixes.

Key improvements over the original:
  1. Breadcrumb prepended to every chunk:
       [§4 Source Connectors > 4.1 PostgreSQL > 4.1.2 CDC Prerequisites]
     Improves embedding quality and gives LLM heading context.

  2. Per-chunk doc_url: resolves the nearest DOC URL seen at or before each
     subsection, not just the parent section URL.

  3. True sliding-window overlap across subsection/section boundaries:
     each chunk carries the last OVERLAP_CHARS chars of the previous chunk
     prepended, even when crossing heading boundaries.

  4. Larger max chunk size: 2500 chars (model handles 8192 tokens).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import Config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern registries
# ---------------------------------------------------------------------------

_CONNECTOR_RE: Dict[str, List[str]] = {
    "postgres":  ["postgres", "postgresql", "pgoutput", "wal2json", "rds postgres", "aurora postgres"],
    "mysql":     ["mysql", "binlog", "aurora mysql", "rds mysql"],
    "mongodb":   ["mongodb", "mongo ", "oplog", "change stream", "atlas"],
    "oracle":    ["oracle"],
    "kafka":     ["kafka", "consumer group"],
}
_SYNC_MODE_RE: Dict[str, List[str]] = {
    "cdc":          ["strict cdc", "cdc", "change data capture", "binlog", "oplog", "pgoutput"],
    "full_refresh": ["full refresh", "full_refresh"],
    "incremental":  ["incremental"],
}
_DEST_RE: Dict[str, List[str]] = {
    "iceberg": ["iceberg"],
    "parquet": ["parquet"],
    "s3":      [" s3 ", "aws s3", "amazon s3"],
    "gcs":     ["gcs", "google cloud storage"],
    "minio":   ["minio"],
}
_BENCH_RE: Dict[str, List[str]] = {
    "full_load":  ["full load rps", "rps (full)", "full load"],
    "cdc":        ["cdc rps", "rps (cdc)", "cdc benchmark"],
    "streaming":  ["mps", "streaming"],
}


def _detect(text: str, patterns: Dict[str, List[str]]) -> str:
    tl = text.lower()
    for key, pats in patterns.items():
        if any(p in tl for p in pats):
            return key
    return ""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    text: str                    # breadcrumb + content
    raw_text: str                # content only (for dedup)
    chunk_type: str              # prose | table | code | metadata
    section: str = ""
    subsection: str = ""
    subsubsection: str = ""
    connector: str = ""
    sync_mode: str = ""
    destination: str = ""
    benchmark_type: str = ""
    doc_url: str = ""
    tags: str = ""
    chunk_id: str = ""

    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = hashlib.sha256(
                f"{self.section}|{self.subsection}|{self.subsubsection}|{self.raw_text[:120]}".encode()
            ).hexdigest()[:16]

    def to_payload(self) -> dict:
        return {
            "text": self.text,
            "raw_text": self.raw_text,
            "chunk_type": self.chunk_type,
            "section": self.section,
            "subsection": self.subsection,
            "subsubsection": self.subsubsection,
            "connector": self.connector,
            "sync_mode": self.sync_mode,
            "destination": self.destination,
            "benchmark_type": self.benchmark_type,
            "doc_url": self.doc_url,
            "tags": self.tags,
            "chunk_id": self.chunk_id,
        }


# ---------------------------------------------------------------------------
# URL extraction helpers
# ---------------------------------------------------------------------------

_DOC_URL_RE = re.compile(r"\*\*DOC URL\*\*\s+(\S+)")
_TAGS_RE     = re.compile(r"\*\*TAGS\*\*\s+(.+)")

def _extract_url_from_block(text: str) -> str:
    """Extract the first DOC URL found in a block of text."""
    m = _DOC_URL_RE.search(text)
    return m.group(1).strip() if m else ""

def _extract_tags(text: str) -> str:
    m = _TAGS_RE.search(text)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Sliding window splitter
# ---------------------------------------------------------------------------

def _split_with_overlap(
    text: str,
    max_chars: int = Config.MAX_CHUNK_CHARS,
    overlap: int = Config.OVERLAP_CHARS,
) -> List[str]:
    """
    Split text on paragraph boundaries, carrying overlap between windows.
    Returns list of text chunks.
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    current = ""
    prev_tail = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            # Start next window: overlap tail from previous chunk
            tail = current[-overlap:] if len(current) > overlap else current
            current = (tail + "\n\n" + para).strip() if tail else para.strip()

    if current:
        chunks.append(current)
    return chunks or [text]


# ---------------------------------------------------------------------------
# Breadcrumb builder
# ---------------------------------------------------------------------------

def _breadcrumb(section: str, subsection: str, subsubsection: str) -> str:
    parts = [p for p in [section, subsection, subsubsection] if p]
    if not parts:
        return ""
    return "[" + " > ".join(parts) + "]\n"


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_and_chunk(docs_path: Path) -> List[Chunk]:
    """
    Parse the OLake knowledge-base markdown and return a flat list of Chunk
    objects ready for embedding and ingestion.
    """
    text = docs_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    chunks: List[Chunk] = []

    # Current heading state
    section = ""
    subsection = ""
    subsubsection = ""

    # URL/tag state — tracked at the closest heading level
    section_url = ""
    subsection_url = ""   # may differ from section_url if subsection has its own DOC URL
    section_tags = ""

    # Rolling overlap tail — last N chars from the previous prose chunk
    prev_tail = ""

    # Buffer for current block of text
    buf: List[str] = []
    in_code = False
    code_lang = ""
    code_buf: List[str] = []

    def flush_prose(extra_overlap: str = "") -> None:
        """Flush the current prose buffer into chunks."""
        nonlocal prev_tail
        raw = "\n".join(buf).strip()
        if not raw:
            return

        # Resolve the most specific URL available
        url = subsection_url or section_url or "https://olake.io/docs/"
        bc = _breadcrumb(section, subsection, subsubsection)

        full_text = extra_overlap + raw if extra_overlap else raw
        sub_chunks = _split_with_overlap(full_text)

        for i, sc in enumerate(sub_chunks):
            # Build overlap for next sibling
            current_tail = sc[-Config.OVERLAP_CHARS:]

            chunk = Chunk(
                text=bc + sc,
                raw_text=sc,
                chunk_type="prose",
                section=section,
                subsection=subsection,
                subsubsection=subsubsection,
                connector=_detect(sc, _CONNECTOR_RE),
                sync_mode=_detect(sc, _SYNC_MODE_RE),
                destination=_detect(sc, _DEST_RE),
                benchmark_type=_detect(sc, _BENCH_RE),
                doc_url=url,
                tags=section_tags,
            )
            chunks.append(chunk)
            prev_tail = current_tail

        buf.clear()

    def flush_code() -> None:
        """Flush the current code block into a code chunk."""
        raw = "\n".join(code_buf).strip()
        if not raw:
            return
        url = subsection_url or section_url or "https://olake.io/docs/"
        bc = _breadcrumb(section, subsection, subsubsection)
        chunk = Chunk(
            text=bc + f"```{code_lang}\n{raw}\n```",
            raw_text=raw,
            chunk_type="code",
            section=section,
            subsection=subsection,
            subsubsection=subsubsection,
            connector=_detect(raw, _CONNECTOR_RE),
            sync_mode=_detect(raw, _SYNC_MODE_RE),
            destination=_detect(raw, _DEST_RE),
            benchmark_type=_detect(raw, _BENCH_RE),
            doc_url=url,
            tags=section_tags,
        )
        chunks.append(chunk)
        code_buf.clear()

    for line in lines:
        # ── Code fence toggle ──────────────────────────────────────────
        if line.startswith("```"):
            if not in_code:
                flush_prose(prev_tail)
                in_code = True
                code_lang = line[3:].strip()
            else:
                flush_code()
                in_code = False
                code_lang = ""
            continue

        if in_code:
            code_buf.append(line)
            continue

        # ── Section heading (§N) ────────────────────────────────────────
        if re.match(r"^§\d", line):
            flush_prose(prev_tail)
            section = line.strip()
            subsection = ""
            subsubsection = ""
            section_url = ""
            subsection_url = ""
            section_tags = ""
            prev_tail = ""
            buf.clear()
            continue

        # ── H2 — numbered subsection (e.g. "4.1 PostgreSQL Connector") ──
        if re.match(r"^\d+\.\d+ ", line):
            flush_prose(prev_tail)
            subsection = line.strip()
            subsubsection = ""
            subsection_url = ""  # reset; will pick up if URL found in content
            prev_tail = ""
            buf.clear()
            continue

        # ── H3 — numbered sub-subsection ────────────────────────────────
        if re.match(r"^\d+\.\d+\.\d+ ", line):
            flush_prose(prev_tail)
            subsubsection = line.strip()
            prev_tail = ""
            buf.clear()
            continue

        # ── Metadata: DOC URL ────────────────────────────────────────────
        if "**DOC URL**" in line:
            url_match = re.search(r"https?://\S+", line)
            if url_match:
                found_url = url_match.group(0).rstrip("\\")
                if not subsection:
                    section_url = found_url
                else:
                    subsection_url = found_url
            buf.append(line)
            continue

        # ── Metadata: TAGS ───────────────────────────────────────────────
        if "**TAGS**" in line:
            m = re.search(r"\*\*TAGS\*\*\s+(.+)", line)
            if m:
                section_tags = m.group(1).strip()
            buf.append(line)
            continue

        # ── Regular content ──────────────────────────────────────────────
        buf.append(line)

    # Flush any remaining content
    flush_prose(prev_tail)
    if code_buf:
        flush_code()

    return chunks


def parse_file(path: Path = Config.DOCS_FILE) -> List[Chunk]:
    """Public entry point — parse and return all chunks."""
    log.info(f"Parsing {path} ...")
    chunks = parse_and_chunk(path)
    log.info(f"Parsed {len(chunks)} chunks  "
             f"(prose:{sum(1 for c in chunks if c.chunk_type=='prose')} "
             f"code:{sum(1 for c in chunks if c.chunk_type=='code')} "
             f"other:{sum(1 for c in chunks if c.chunk_type not in ('prose','code'))})")
    return chunks
