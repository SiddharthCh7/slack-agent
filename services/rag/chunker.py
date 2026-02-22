"""
OLake Docs Chunker — H2-based hierarchical chunking strategy.

Chunking Strategy:
  - Primary unit: H2 boundaries (e.g., "4.1 PostgreSQL Connector")
  - Each chunk includes: H2 header, all H3 subsections, tables, code blocks
  - Metadata inheritance: H1 metadata fields stored as chunk metadata
  - Section path prepended to chunk text for hierarchical context

Special Handling:
  - §4.1.3 Variant-Specific Setup → split into 4 sub-chunks (RDS/Aurora/Azure/Self-hosted)
  - §3.2.5–3.2.7 Schema Evolution → split into 3 sub-chunks (column/table/type changes)
  - §1.4 Glossary → one chunk + glossary_terms metadata array
  - §12 Quick Reference → one chunk per table, tagged chunk_type="summary"

Overlap: ~400 chars (~100 tokens) between H3 sub-chunks within split H2s.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from config import Config

# ---------------------------------------------------------------------------
# Link extraction patterns
# ---------------------------------------------------------------------------

# Markdown link patterns
LINK_PATTERNS = {
    # Standard markdown: [text](url) or [text](url "title")
    "markdown": re.compile(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)'),
    # Reference-style link definition: [ref]: url
    "reference": re.compile(r'^\[([^\]]+)\]:\s*(\S+)', re.MULTILINE),
    # Bare URLs (not in markdown syntax)
    "bare_url": re.compile(r'(?<!\()(https?://[^\s\)]+)(?![^<]*>|[^<]*\))'),
    # Docusaurus site links: {/docs/...} or @site/docs/...
    "docusaurus": re.compile(r'(?:\{/?docs/|@site/docs/)([^}\s]+)'),
    # Image links: ![alt](url)
    "image": re.compile(r'!\[([^\]]*)\]\(([^)\s]+)\)'),
}

log = logging.getLogger(__name__)


def resolve_link(base_path: str, link: str) -> str:
    """
    Resolve relative link to absolute doc path.
    
    Examples:
      base_path = "connectors/postgres/setup/rds.mdx"
      link = "./config.mdx"           → "connectors/postgres/config.mdx"
      link = "../troubleshooting.mdx"  → "connectors/postgres/troubleshooting.mdx"
      link = "/docs/core/architecture" → "core/architecture.mdx"
      link = "#prerequisites"          → "connectors/postgres/setup/rds.mdx#prerequisites"
    """
    if not link:
        return ""
    
    # Anchor link (same document)
    if link.startswith("#"):
        return f"{base_path}{link}"
    
    # Absolute docs path
    if link.startswith("/docs/"):
        return link.replace("/docs/", "") + ".mdx"
    
    # External link
    if link.startswith(("http://", "https://")):
        return link
    
    # Relative path resolution
    base_dir = Path(base_path).parent
    resolved = (base_dir / link).as_posix()
    return resolved


def extract_links(content: str, base_path: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Extract all links from markdown content.
    
    Returns:
        Tuple of (internal_links, external_links, anchor_links, image_links)
        - internal_links: List of absolute doc paths (e.g., "connectors/postgres/config.mdx")
        - external_links: List of http(s) URLs
        - anchor_links: List of anchor IDs (e.g., "#prerequisites")
        - image_links: List of image paths
    """
    internal = set()
    external = set()
    anchors = set()
    images = set()
    
    # Extract standard markdown links
    for match in LINK_PATTERNS["markdown"].finditer(content):
        url = match.group(2)
        _categorize_link(url, base_path, internal, external, anchors, images)
    
    # Extract reference-style links
    for match in LINK_PATTERNS["reference"].finditer(content):
        url = match.group(2)
        _categorize_link(url, base_path, internal, external, anchors, images)
    
    # Extract bare URLs
    for match in LINK_PATTERNS["bare_url"].finditer(content):
        url = match.group(1)
        if url.startswith(("http://", "https://")):
            external.add(url)
    
    # Extract Docusaurus-specific links
    for match in LINK_PATTERNS["docusaurus"].finditer(content):
        path = match.group(1)
        resolved = resolve_link(base_path, f"/docs/{path}")
        if resolved.endswith(".mdx"):
            internal.add(resolved)
    
    # Extract image links
    for match in LINK_PATTERNS["image"].finditer(content):
        img_url = match.group(2)
        if img_url.startswith(("http://", "https://")):
            external.add(img_url)
        else:
            images.add(resolve_link(base_path, img_url))
    
    return (
        sorted(internal),
        sorted(external),
        sorted(anchors),
        sorted(images)
    )


def _categorize_link(url: str, base_path: str, internal: set, external: set, anchors: set, images: set):
    """Categorize a single link and add to appropriate set."""
    # Clean URL (remove trailing slashes, fragments for resolution)
    url_clean = url.rstrip("/")
    fragment = ""
    
    # Extract fragment/anchor
    if "#" in url_clean:
        url_clean, fragment = url_clean.split("#", 1)
        if fragment:
            anchors.add(f"#{fragment}")
    
    # Skip empty URLs
    if not url_clean:
        return
    
    # External link
    if url_clean.startswith(("http://", "https://")):
        external.add(url)
        return
    
    # Anchor-only link
    if url_clean.startswith("#"):
        anchors.add(url_clean)
        return
    
    # Resolve and categorize
    resolved = resolve_link(base_path, url_clean)
    
    if resolved.endswith(".mdx"):
        internal.add(resolved)
    elif resolved.startswith("http"):
        external.add(resolved)


# ---------------------------------------------------------------------------
# Pattern registries for metadata detection
# ---------------------------------------------------------------------------

_CONNECTOR_RE: Dict[str, List[str]] = {
    "postgres":  ["postgres", "postgresql", "pgoutput", "wal2json", "rds postgres", "aurora postgres"],
    "mysql":     ["mysql", "binlog", "aurora mysql", "rds mysql"],
    "mongodb":   ["mongodb", "mongo ", "oplog", "change stream", "atlas"],
    "oracle":    ["oracle"],
    "kafka":     ["kafka", "consumer group"],
}
_SYNC_MODE_RE: Dict[str, List[str]] = {
    "cdc":          ["strict cdc", "cdc", "change data capture", "binlog", "oplog", "pgoutput", "wal"],
    "full_refresh": ["full refresh", "full_refresh", "full load"],
    "incremental":  ["incremental", "cursor-based", "cursor based"],
}
_DEST_RE: Dict[str, List[str]] = {
    "iceberg": ["iceberg"],
    "parquet": ["parquet"],
    "s3":      [" s3 ", "aws s3", "amazon s3", "s3a://"],
    "gcs":     ["gcs", "google cloud storage", "gs://"],
    "minio":   ["minio"],
    "adls":    ["adls", "azure data lake", "abfs://"],
}
_BENCH_RE: Dict[str, List[str]] = {
    "full_load":  ["full load rps", "rps (full)", "full load", "full refresh rps"],
    "cdc":        ["cdc rps", "rps (cdc)", "cdc benchmark", "cdc rps"],
    "streaming":  ["mps", "streaming", "records/sec"],
}

# Variant markers for §4.1.3 split
_VARIANT_MARKERS = [
    "**RDS PostgreSQL:**",
    "**Aurora PostgreSQL:**",
    "**Azure PostgreSQL Flexible Server:**",
    "**Self-Hosted / Generic:**"
]

# Schema evolution section markers for §3.2.5-3.2.7 split
_SCHEMA_EVOLUTION_H3 = ["3.2.5 Schema Evolution", "3.2.6 Schema Evolution", "3.2.7 Data Type Changes"]


def _detect(text: str, patterns: Dict[str, List[str]]) -> str:
    tl = text.lower()
    for key, pats in patterns.items():
        if any(p in tl for p in pats):
            return key
    return ""


def _infer_connector_from_section(subsection: str, section: str) -> str:
    full = f"{section} {subsection}".lower()
    if "postgres" in full or "postgresql" in full:
        return "postgres"
    if "mysql" in full:
        return "mysql"
    if "mongodb" in full or "mongo" in full:
        return "mongodb"
    if "oracle" in full:
        return "oracle"
    if "kafka" in full:
        return "kafka"
    return ""


def _infer_destination_from_section(subsection: str, section: str) -> str:
    full = f"{section} {subsection}".lower()
    if "iceberg" in full:
        return "iceberg"
    if "parquet" in full:
        return "parquet"
    if "glue" in full:
        return "iceberg"
    if "hive" in full:
        return "iceberg"
    if "jdbc" in full:
        return "iceberg"
    if "rest" in full and "catalog" in full:
        return "iceberg"
    if "gcs" in full or "google cloud" in full:
        return "gcs"
    if "minio" in full:
        return "minio"
    if "s3" in full:
        return "s3"
    if "adls" in full or "azure" in full:
        return "adls"
    return ""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """Represents a single chunk of documentation."""
    text: str                    # section_path + content (for embedding)
    raw_text: str                # content only (for display/dedup)
    chunk_type: str              # "prose" | "table" | "code" | "metadata" | "summary"
    section: str = ""            # H1: §N Title
    subsection: str = ""         # H2: N.N Title
    subsubsection: str = ""      # H3: N.N.N Title
    variant: str = ""            # For split sub-chunks (e.g., "RDS", "Aurora")
    connector: str = ""
    sync_mode: str = ""
    destination: str = ""
    benchmark_type: str = ""
    doc_url: str = ""
    tags: str = ""
    key_entities: str = ""
    last_updated: str = ""
    sample_questions: str = ""
    section_path: str = ""       # Hierarchical path: "§4 > §4.1 PostgreSQL > §4.1.3 > RDS"
    glossary_terms: List[Dict[str, str]] = field(default_factory=list)
    chunk_id: str = ""
    # Link fields
    internal_links: List[str] = field(default_factory=list)   # /docs/... paths
    external_links: List[str] = field(default_factory=list)   # https://...
    anchor_links: List[str] = field(default_factory=list)     # #section-id
    image_links: List[str] = field(default_factory=list)      # /img/... paths
    # Document metadata
    doc_path: str = ""           # Relative path from docs/ (e.g., "connectors/postgres/config.mdx")
    doc_category: str = ""       # "connectors" | "core" | "getting-started" | etc.
    is_redirect: bool = False    # True if this is a redirect page

    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = hashlib.sha256(
                f"{self.section}|{self.subsection}|{self.subsubsection}|{self.variant}|{self.raw_text}".encode()
            ).hexdigest()[:16]

    def to_payload(self) -> dict:
        payload = {
            "text": self.text,
            "raw_text": self.raw_text,
            "chunk_type": self.chunk_type,
            "section": self.section,
            "subsection": self.subsection,
            "subsubsection": self.subsubsection,
            "variant": self.variant,
            "connector": self.connector,
            "sync_mode": self.sync_mode,
            "destination": self.destination,
            "benchmark_type": self.benchmark_type,
            "doc_url": self.doc_url,
            "tags": self.tags,
            "key_entities": self.key_entities,
            "last_updated": self.last_updated,
            "sample_questions": self.sample_questions,
            "section_path": self.section_path,
            "chunk_id": self.chunk_id,
            # Link fields (JSON-encoded for Qdrant)
            "internal_links": json.dumps(self.internal_links) if self.internal_links else "",
            "external_links": json.dumps(self.external_links) if self.external_links else "",
            "anchor_links": json.dumps(self.anchor_links) if self.anchor_links else "",
            "image_links": json.dumps(self.image_links) if self.image_links else "",
            # Document metadata
            "doc_path": self.doc_path,
            "doc_category": self.doc_category,
            "is_redirect": self.is_redirect,
        }
        # Only include glossary_terms if non-empty
        if self.glossary_terms:
            payload["glossary_terms"] = json.dumps(self.glossary_terms)
        return payload


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------

_METADATA_FIELDS = ["DOC URL", "SEE ALSO", "LAST UPDATED", "TAGS", "KEY ENTITIES", "ANSWERS QUESTIONS LIKE", "UPDATE WHEN"]


def _extract_metadata_table(lines: List[str], start_idx: int) -> Tuple[Dict[str, str], int]:
    """
    Extract metadata table starting at start_idx.
    Returns (metadata_dict, end_idx).
    
    Table format:
      ------------- -------------------------
      **DOC URL**   https://...
      **LAST        Feb 2026
      UPDATED**     
      ------------- -------------------------
    """
    metadata = {}
    idx = start_idx
    current_field = None
    current_value = []
    table_started = False
    expecting_continuation = False
    
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            idx += 1
            continue
        
        # Skip table border lines (but not if they contain **)
        if "---" in stripped and "**" not in stripped:
            if table_started:
                break
            else:
                idx += 1
                continue
        
        # Check for field name continuation FIRST
        if expecting_continuation:
            if "UPDATED**" in stripped:
                current_field = "LAST UPDATED"
                expecting_continuation = False
                idx += 1
                continue
            elif "ENTITIES**" in stripped:
                current_field = "KEY ENTITIES"
                expecting_continuation = False
                idx += 1
                continue
            elif "LIKE**" in stripped:
                current_field = "ANSWERS QUESTIONS LIKE"
                expecting_continuation = False
                idx += 1
                continue
            elif "WHEN**" in stripped:
                current_field = "UPDATE WHEN"
                expecting_continuation = False
                idx += 1
                continue
        
        # Check for field header
        if "**DOC URL**" in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "DOC URL"
            current_value = [line.split("**DOC URL**")[-1].strip()]
            table_started = True
            idx += 1
            continue
        
        if "**SEE ALSO**" in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "SEE ALSO"
            current_value = [line.split("**SEE ALSO**")[-1].strip()]
            table_started = True
            idx += 1
            continue
        
        if "**TAGS**" in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "TAGS"
            current_value = [line.split("**TAGS**")[-1].strip()]
            table_started = True
            idx += 1
            continue
        
        # Multi-line field starters
        if "**LAST" in line and "UPDATED" not in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "LAST"
            current_value = [line.split("**LAST")[-1].strip()]
            table_started = True
            expecting_continuation = True
            idx += 1
            continue
        
        if "**KEY" in line and "ENTITIES" not in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "KEY"
            current_value = [line.split("**KEY")[-1].strip()]
            table_started = True
            expecting_continuation = True
            idx += 1
            continue
        
        if "**ANSWERS" in line and "LIKE" not in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "ANSWERS"
            current_value = [line.split("**ANSWERS")[-1].strip()]
            table_started = True
            expecting_continuation = True
            idx += 1
            continue
        
        if "**UPDATE" in line and "WHEN" not in line:
            if current_field:
                metadata[current_field] = " ".join(current_value).strip()
            current_field = "UPDATE"
            current_value = [line.split("**UPDATE")[-1].strip()]
            table_started = True
            expecting_continuation = True
            idx += 1
            continue
        
        # Continuation value
        if current_field:
            current_value.append(stripped)
            idx += 1
            continue
        
        idx += 1

    # Save last field
    if current_field:
        metadata[current_field] = " ".join(current_value).strip()

    return metadata, idx


def _parse_metadata_section(metadata: Dict[str, str]) -> Dict[str, Any]:
    """Parse extracted metadata into structured fields."""
    result = {
        "doc_url": "",
        "tags": "",
        "key_entities": "",
        "last_updated": "",
        "sample_questions": "",
    }

    if "DOC URL" in metadata:
        url_match = re.search(r"https?://\S+", metadata["DOC URL"])
        if url_match:
            result["doc_url"] = url_match.group(0).rstrip("\\")

    if "TAGS" in metadata:
        result["tags"] = metadata["TAGS"]

    if "KEY ENTITIES" in metadata:
        result["key_entities"] = metadata["KEY ENTITIES"]

    if "LAST UPDATED" in metadata:
        result["last_updated"] = metadata["LAST UPDATED"]

    if "ANSWERS QUESTIONS LIKE" in metadata:
        # Questions are separated by \ or newlines
        questions = metadata["ANSWERS QUESTIONS LIKE"].replace("\\", "\n").split("\n")
        result["sample_questions"] = "\n".join(q.strip() for q in questions if q.strip())

    return result


# ---------------------------------------------------------------------------
# Section path builder
# ---------------------------------------------------------------------------

def _build_section_path(section: str, subsection: str, subsubsection: str, variant: str = "") -> str:
    """Build hierarchical section path string."""
    parts = [p for p in [section, subsection, subsubsection, variant] if p]
    return " > ".join(parts)


# ---------------------------------------------------------------------------
# Special section handlers
# ---------------------------------------------------------------------------

def _split_variant_section(content: str, h3_title: str) -> List[Tuple[str, str]]:
    """
    Split variant-specific content (e.g., §4.1.3) into sub-chunks.
    Returns list of (variant_name, variant_content) tuples.
    """
    lines = content.split("\n")
    variants = []
    current_variant = None
    current_content = []
    shared_intro = []

    for line in lines:
        # Check for variant marker
        variant_found = None
        for marker in _VARIANT_MARKERS:
            if marker in line:
                variant_found = marker.strip("*:")
                break

        if variant_found:
            # Save previous variant
            if current_variant:
                variants.append((current_variant, "\n".join(current_content)))
            elif shared_intro:
                # Save shared intro for first variant
                pass  # Will be prepended to each variant

            current_variant = variant_found
            current_content = []
        else:
            if current_variant is None:
                shared_intro.append(line)
            else:
                current_content.append(line)

    # Save last variant
    if current_variant:
        variants.append((current_variant, "\n".join(current_content)))

    # Prepend shared intro to each variant
    shared_intro_text = "\n".join(shared_intro).strip()
    result = []
    for variant_name, variant_content in variants:
        full_content = f"{h3_title}\n{shared_intro_text}\n{variant_content}".strip()
        result.append((variant_name, full_content))

    return result


def _parse_glossary_table(content: str) -> List[Dict[str, str]]:
    """
    Parse glossary table into list of {term, definition} dicts.
    Table format uses fixed-width columns (no | separators):
      Term              Definition text...
    """
    terms = []
    lines = content.split("\n")
    
    # Find table start (line with **Term** and **Definition**)
    table_start = -1
    for i, line in enumerate(lines):
        if "**Term**" in line and "**Definition**" in line:
            table_start = i + 1
            break
    
    if table_start < 0:
        return terms
    
    current_term = None
    current_def_lines = []
    term_continuation = False
    
    for line in lines[table_start:]:
        stripped = line.strip()
        
        # Skip empty lines and table borders
        if not stripped or stripped.startswith("---"):
            if current_term and current_def_lines:
                terms.append({
                    "term": current_term,
                    "definition": " ".join(current_def_lines).strip()
                })
                current_term = None
                current_def_lines = []
                term_continuation = False
            continue
        
        # Check if this is a new term line (starts with minimal indentation)
        # Term lines have content starting at column ~2, definition continues at column ~20+
        indent = len(line) - len(line.lstrip())
        is_new_term = indent < 4 and not term_continuation
        
        if is_new_term:
            # Save previous term
            if current_term and current_def_lines:
                terms.append({
                    "term": current_term,
                    "definition": " ".join(current_def_lines).strip()
                })
            
            # Parse new term line - look for double-space gap between term and definition
            line_stripped = line.strip()
            parts = line_stripped.split("  ", 1)
            if len(parts) == 2 and parts[0].strip() and not parts[0].strip().endswith(')'):
                # Likely a complete term
                current_term = parts[0].strip()
                current_def_lines = [parts[1].strip()] if parts[1].strip() else []
                term_continuation = False
            elif line_stripped.endswith('(') or line_stripped.endswith(')'):
                # Term continues on next line (e.g., "CDC (Change Data")
                if current_term:
                    current_term = current_term + " " + line_stripped.rstrip('()')
                else:
                    current_term = line_stripped.strip('()')
                current_def_lines = []
                term_continuation = True
            else:
                # Fallback: first word is term
                parts = line_stripped.split(" ", 1)
                current_term = parts[0].strip() if parts else ""
                current_def_lines = [parts[1].strip()] if len(parts) > 1 else []
                term_continuation = False
        else:
            # Continuation of definition (or term if in continuation mode)
            if current_term:
                if term_continuation and not any(c.isalpha() for c in stripped[:1]) or stripped.startswith(')'):
                    # This is still part of the term
                    current_term = current_term + " " + stripped.strip('() ')
                else:
                    # This is definition content
                    current_def_lines.append(stripped)
                    term_continuation = False
    
    # Save last term
    if current_term and current_def_lines:
        terms.append({
            "term": current_term,
            "definition": " ".join(current_def_lines).strip()
        })
    
    return terms


def _is_schema_evolution_section(subsection: str) -> bool:
    """Check if subsection is one of the schema evolution sections."""
    for marker in _SCHEMA_EVOLUTION_H3:
        if marker in subsection:
            return True
    return False


def _split_schema_evolution(content: str, h3_title: str) -> List[Tuple[str, str]]:
    """
    Split schema evolution content into sub-chunks.
    Returns list of (sub_chunk_name, sub_chunk_content) tuples.
    """
    # Schema evolution sections are already split as H3s (3.2.5, 3.2.6, 3.2.7)
    # This function handles any further splitting within each
    return [("content", content)]


def _is_quick_reference_section(section: str) -> bool:
    """Check if section is §12 Quick Reference."""
    return "§12" in section


def _split_quick_reference_tables(content: str) -> List[Tuple[str, str, str]]:
    """
    Split quick reference section into per-table chunks.
    Tables are separated by H2 headings (e.g., "12.1 Source Connector Summary").
    Returns list of (table_title, table_content, table_type) tuples.
    """
    lines = content.split("\n")
    tables = []
    current_title = ""
    current_table_lines = []
    
    for line in lines:
        # Check for H2 heading (table title) - pattern: "N.N Title"
        if re.match(r"^\d+\.\d+\s", line.strip()):
            # Save previous table
            if current_title and current_table_lines:
                tables.append((current_title, "\n".join(current_table_lines), "summary"))
            current_title = line.strip()
            current_table_lines = []
        elif current_title:
            # Accumulate table content (skip empty lines at start)
            if current_table_lines or line.strip():
                current_table_lines.append(line)
    
    # Save last table
    if current_title and current_table_lines:
        tables.append((current_title, "\n".join(current_table_lines), "summary"))
    
    return tables


# ---------------------------------------------------------------------------
# Sliding window splitter (for large H2 content)
# ---------------------------------------------------------------------------

def _split_with_overlap(
    text: str,
    max_chars: int = Config.MAX_CHUNK_CHARS,
    overlap: int = Config.OVERLAP_CHARS,
) -> List[str]:
    """
    Split text on semantic boundaries (paragraphs, table rows, sentences),
    carrying overlap between windows.
    Returns list of text chunks.
    """
    if len(text) <= max_chars:
        return [text]

    # First split on paragraph boundaries
    paragraphs = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            sub_chunks = _split_large_paragraph(para, max_chars, overlap)
            chunks.extend(sub_chunks[:-1])
            current = sub_chunks[-1] if sub_chunks else ""
        elif len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if len(current) > overlap else current
            current = (tail + "\n\n" + para).strip() if tail else para.strip()

    if current:
        chunks.append(current)
    return chunks or [text]


def _split_large_paragraph(para: str, max_chars: int, overlap: int) -> List[str]:
    """Split a single large paragraph on semantic boundaries."""
    if len(para) <= max_chars:
        return [para]

    lines = para.split('\n')

    # Detect if this is a table
    table_lines = []
    non_table_lines = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^[\+\-]+\s*[\+\-]*$', stripped) or '|' in stripped:
            table_lines.append(line)
        else:
            non_table_lines.append(line)

    # If mostly table content, split on table row boundaries
    if len(table_lines) > len(non_table_lines) and len(table_lines) > 3:
        result = []
        current = ""
        for line in table_lines:
            if len(current) + len(line) + 1 <= max_chars:
                current = (current + "\n" + line).strip()
            else:
                if current:
                    result.append(current)
                tail = current[-overlap:] if len(current) > overlap else current
                current = (tail + "\n" + line).strip() if tail else line.strip()
        if current:
            result.append(current)
        if len(result) > 1:
            return result

    # Try splitting on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', para)
    if len(sentences) > 1:
        result = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) + 1 <= max_chars:
                current = (current + " " + sent).strip()
            else:
                if current:
                    result.append(current)
                tail = current[-overlap:] if len(current) > overlap else current
                current = (tail + " " + sent).strip() if tail else sent.strip()
        if current:
            result.append(current)
        if len(result) > 1:
            return result

    # Fallback: hard split at max_chars
    result = []
    pos = 0
    while pos < len(para):
        end = min(pos + max_chars, len(para))
        if end < len(para):
            space_pos = para.rfind(' ', pos, end)
            if space_pos > pos:
                end = space_pos
        chunk = para[pos:end].strip()
        if chunk:
            result.append(chunk)
        pos = end
    return result if result else [para]


# ---------------------------------------------------------------------------
# Frontmatter parsing (Docusaurus YAML frontmatter)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """
    Parse Docusaurus YAML frontmatter from markdown content.
    
    Example frontmatter:
      ---
      title: "QuickStart"
      description: "Get started with OLake"
      sidebar_label: QuickStart
      sidebar_position: 1
      ---
    
    Returns dict with parsed fields.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}
    
    frontmatter_text = match.group(1)
    result = {}
    
    # Simple YAML-like parsing (handle common cases)
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower().replace("-", "_")
            value = value.strip().strip('"').strip("'")
            result[key] = value
    
    return result


def detect_redirect(content: str) -> Optional[str]:
    """
    Detect if this is a redirect page.
    
    Returns the redirect URL if found, None otherwise.
    
    Redirect patterns:
      - Docusaurus: <meta httpEquiv="refresh" content="0; url=/docs/..." />
      - Markdown: Redirecting to [text](url)...
    """
    # Docusaurus meta redirect
    meta_match = re.search(r'<meta\s+httpEquiv="refresh"\s+content="0;\s*url=([^"]+)"', content)
    if meta_match:
        return meta_match.group(1)
    
    # Markdown redirect text
    redirect_match = re.search(r'Redirecting to \[([^\]]+)\]\(([^)]+)\)', content)
    if redirect_match:
        return redirect_match.group(2)
    
    return None


def get_doc_category(file_path: Path) -> str:
    """
    Infer document category from file path.
    
    Examples:
      connectors/postgres/config.mdx → "connectors"
      core/architecture.mdx → "core"
      getting-started/quickstart.mdx → "getting-started"
    """
    parts = file_path.parts
    if len(parts) >= 2:
        # Get the first directory under docs/
        return parts[-2] if len(parts) >= 2 else ""
    return ""


def infer_connector_from_path(file_path: Path) -> str:
    """
    Infer connector type from file path.
    
    Examples:
      connectors/postgres/... → "postgres"
      connectors/mysql/setup/rds.mdx → "mysql"
    """
    path_str = str(file_path).lower()
    if "/postgres/" in path_str or "postgres" in path_str:
        return "postgres"
    if "/mysql/" in path_str or "mysql" in path_str:
        return "mysql"
    if "/mongodb/" in path_str or "mongodb" in path_str:
        return "mongodb"
    if "/oracle/" in path_str or "oracle" in path_str:
        return "oracle"
    if "/kafka/" in path_str or "kafka" in path_str:
        return "kafka"
    if "/s3/" in path_str or "s3" in path_str:
        return "s3"
    if "/db2/" in path_str:
        return "db2"
    if "/mssql/" in path_str:
        return "mssql"
    return ""


def infer_setup_variant_from_path(file_path: Path) -> str:
    """
    Infer setup variant from file path.
    
    Examples:
      setup/rds.mdx → "rds"
      setup/aurora.mdx → "aurora"
      setup/azure.mdx → "azure"
    """
    path_str = str(file_path).lower()
    if "/rds." in path_str:
        return "rds"
    if "/aurora." in path_str:
        return "aurora"
    if "/azure." in path_str:
        return "azure"
    if "/gcp." in path_str:
        return "gcp"
    if "/local." in path_str:
        return "local"
    if "/generic." in path_str:
        return "generic"
    return ""


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_and_chunk(docs_path: Path) -> List[Chunk]:
    """
    Parse the OLake knowledge-base markdown and return a flat list of Chunk objects.

    Strategy:
    1. Parse H1 sections (# or §N) as document boundaries
    2. Parse H2 subsections (## or N.N) as primary chunk units
    3. Parse H3 sub-subsections (### or N.N.N) as chunk subdivisions
    4. Apply special handling for:
       - §4.1.3: Split into variant sub-chunks
       - §3.2.5-3.2.7: Keep as separate H3 chunks
       - §1.4: Extract glossary terms as metadata
       - §12: Split into per-table summary chunks
    5. Store H1 metadata as chunk metadata fields
    6. Prepend section_path to chunk text for embedding
    
    Supports both:
      - Legacy format: §N, N.N, N.N.N headers
      - Standard markdown: #, ##, ### headers
    """
    text = docs_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    chunks: List[Chunk] = []

    # Document-level state
    current_section = ""  # H1: §N Title or # Title
    section_metadata: Dict[str, str] = {}  # Parsed H1 metadata

    # H2-level state
    current_h2 = ""
    h2_content_lines: List[str] = []
    h2_metadata: Dict[str, str] = {}  # H2-specific metadata (overrides H1)

    # H3-level state
    current_h3 = ""
    h3_content_lines: List[str] = []

    # Code block state
    in_code = False
    code_lang = ""
    code_buf: List[str] = []

    # Track if we're in a metadata table
    in_metadata_table = False
    metadata_table_start = -1

    def flush_h3_chunk(h3: str, h3_content: str, h3_metadata: Dict[str, str], is_special: bool = False) -> None:
        """Create chunk(s) from H3 content."""
        nonlocal current_section, current_h2

        if not h3_content.strip():
            return

        # Merge H1 and H2 metadata, then H3-specific overrides
        merged_meta = {**section_metadata, **h2_metadata, **h3_metadata}

        # Build section path
        section_path = _build_section_path(current_section, current_h2, h3)

        # Detect metadata from content
        connector = _detect(h3_content, _CONNECTOR_RE) or _infer_connector_from_section(current_h2, current_section)
        sync_mode = _detect(h3_content, _SYNC_MODE_RE)
        destination = _detect(h3_content, _DEST_RE) or _infer_destination_from_section(current_h2, current_section)
        benchmark_type = _detect(h3_content, _BENCH_RE)

        # Check for special handling
        # §4.1.3 Variant-Specific Setup → split into variant sub-chunks
        if "4.1.3" in h3 and "Variant" in h3:
            # Split into variant sub-chunks
            variants = _split_variant_section(h3_content, h3)
            prev_tail = ""
            for variant_name, variant_content in variants:
                variant_path = _build_section_path(current_section, current_h2, h3, variant_name)
                full_text = variant_content
                if prev_tail and Config.OVERLAP_CHARS > 0:
                    full_text = prev_tail + "\n\n" + variant_content

                chunk = Chunk(
                    text=variant_path + "\n" + full_text,
                    raw_text=full_text,
                    chunk_type="prose",
                    section=current_section,
                    subsection=current_h2,
                    subsubsection=h3,
                    variant=variant_name,
                    connector=connector,
                    sync_mode=sync_mode,
                    destination=destination,
                    benchmark_type=benchmark_type,
                    doc_url=merged_meta.get("doc_url", ""),
                    tags=merged_meta.get("tags", ""),
                    key_entities=merged_meta.get("key_entities", ""),
                    last_updated=merged_meta.get("last_updated", ""),
                    sample_questions=merged_meta.get("sample_questions", ""),
                    section_path=variant_path,
                )
                chunks.append(chunk)
                prev_tail = full_text[-Config.OVERLAP_CHARS:] if len(full_text) > Config.OVERLAP_CHARS else ""
            return

        # Check for schema evolution sections
        if _is_schema_evolution_section(h3):
            sub_chunks = _split_schema_evolution(h3_content, h3)
            prev_tail = ""
            for sub_name, sub_content in sub_chunks:
                sub_path = _build_section_path(current_section, current_h2, h3, sub_name if sub_name != "content" else "")
                full_text = sub_content
                if prev_tail and Config.OVERLAP_CHARS > 0:
                    full_text = prev_tail + "\n\n" + sub_content

                chunk = Chunk(
                    text=sub_path + "\n" + full_text,
                    raw_text=full_text,
                    chunk_type="prose",
                    section=current_section,
                    subsection=current_h2,
                    subsubsection=h3,
                    variant=sub_name if sub_name != "content" else "",
                    connector=connector,
                    sync_mode=sync_mode,
                    destination=destination,
                    benchmark_type=benchmark_type,
                    doc_url=merged_meta.get("doc_url", ""),
                    tags=merged_meta.get("tags", ""),
                    key_entities=merged_meta.get("key_entities", ""),
                    last_updated=merged_meta.get("last_updated", ""),
                    sample_questions=merged_meta.get("sample_questions", ""),
                    section_path=sub_path,
                )
                chunks.append(chunk)
                prev_tail = full_text[-Config.OVERLAP_CHARS:] if len(full_text) > Config.OVERLAP_CHARS else ""
            return

        # Check for quick reference tables (§12)
        if _is_quick_reference_section(current_section):
            tables = _split_quick_reference_tables(h3_content)
            for table_title, table_content, table_type in tables:
                table_path = _build_section_path(current_section, current_h2, h3, table_title)
                chunk = Chunk(
                    text=table_path + "\n" + table_content,
                    raw_text=table_content,
                    chunk_type=table_type,  # "summary"
                    section=current_section,
                    subsection=current_h2,
                    subsubsection=h3,
                    variant=table_title,
                    connector=connector,
                    sync_mode=sync_mode,
                    destination=destination,
                    benchmark_type=benchmark_type,
                    doc_url=merged_meta.get("doc_url", ""),
                    tags=merged_meta.get("tags", ""),
                    key_entities=merged_meta.get("key_entities", ""),
                    last_updated=merged_meta.get("last_updated", ""),
                    sample_questions=merged_meta.get("sample_questions", ""),
                    section_path=table_path,
                )
                chunks.append(chunk)
            return

        # Check for glossary (§1.4)
        if "1.4" in current_h2 or "Key Terminology" in h3 or "Key Terminology" in current_h2:
            glossary_terms = _parse_glossary_table(h3_content)
            chunk = Chunk(
                text=section_path + "\n" + h3_content,
                raw_text=h3_content,
                chunk_type="metadata",
                section=current_section,
                subsection=current_h2,
                subsubsection=h3,
                connector=connector,
                sync_mode=sync_mode,
                destination=destination,
                benchmark_type=benchmark_type,
                doc_url=merged_meta.get("doc_url", ""),
                tags=merged_meta.get("tags", ""),
                key_entities=merged_meta.get("key_entities", ""),
                last_updated=merged_meta.get("last_updated", ""),
                sample_questions=merged_meta.get("sample_questions", ""),
                section_path=section_path,
                glossary_terms=glossary_terms,
            )
            chunks.append(chunk)
            return

        # Standard H3 chunk
        chunk = Chunk(
            text=section_path + "\n" + h3_content,
            raw_text=h3_content,
            chunk_type="prose",
            section=current_section,
            subsection=current_h2,
            subsubsection=h3,
            connector=connector,
            sync_mode=sync_mode,
            destination=destination,
            benchmark_type=benchmark_type,
            doc_url=merged_meta.get("doc_url", ""),
            tags=merged_meta.get("tags", ""),
            key_entities=merged_meta.get("key_entities", ""),
            last_updated=merged_meta.get("last_updated", ""),
            sample_questions=merged_meta.get("sample_questions", ""),
            section_path=section_path,
        )
        chunks.append(chunk)

    def flush_h2_content() -> None:
        """Process accumulated H2 content and create chunks."""
        nonlocal current_h3, h3_content_lines

        h3_content = "\n".join(h3_content_lines).strip()
        
        # Skip empty content
        if not h3_content:
            current_h3 = ""
            h3_content_lines = []
            return
        
        # Special handling for H2-level content without H3 children
        
        # Check for glossary (§1.4 Key Terminology)
        if "1.4" in current_h2 and "Key Terminology" in current_h2:
            h2_path = _build_section_path(current_section, current_h2, "")
            merged_meta = {**section_metadata, **h2_metadata}
            glossary_terms = _parse_glossary_table(h3_content)
            
            connector = _detect(h3_content, _CONNECTOR_RE)
            sync_mode = _detect(h3_content, _SYNC_MODE_RE)
            destination = _detect(h3_content, _DEST_RE)
            benchmark_type = _detect(h3_content, _BENCH_RE)
            
            chunk = Chunk(
                text=h2_path + "\n" + h3_content,
                raw_text=h3_content,
                chunk_type="metadata",
                section=current_section,
                subsection=current_h2,
                subsubsection="",
                connector=connector,
                sync_mode=sync_mode,
                destination=destination,
                benchmark_type=benchmark_type,
                doc_url=merged_meta.get("doc_url", ""),
                tags=merged_meta.get("tags", ""),
                key_entities=merged_meta.get("key_entities", ""),
                last_updated=merged_meta.get("last_updated", ""),
                sample_questions=merged_meta.get("sample_questions", ""),
                section_path=h2_path,
                glossary_terms=glossary_terms,
            )
            chunks.append(chunk)
            current_h3 = ""
            h3_content_lines = []
            return
        
        # Check for quick reference tables (§12) - each H2 becomes a summary chunk
        if _is_quick_reference_section(current_section):
            h2_path = _build_section_path(current_section, current_h2, "")
            merged_meta = {**section_metadata, **h2_metadata}
            
            connector = _detect(h3_content, _CONNECTOR_RE)
            sync_mode = _detect(h3_content, _SYNC_MODE_RE)
            destination = _detect(h3_content, _DEST_RE)
            benchmark_type = _detect(h3_content, _BENCH_RE)
            
            chunk = Chunk(
                text=h2_path + "\n" + h3_content,
                raw_text=h3_content,
                chunk_type="summary",  # Mark as summary for routing
                section=current_section,
                subsection=current_h2,
                subsubsection="",
                variant=current_h2,  # Use H2 title as variant
                connector=connector,
                sync_mode=sync_mode,
                destination=destination,
                benchmark_type=benchmark_type,
                doc_url=merged_meta.get("doc_url", ""),
                tags=merged_meta.get("tags", ""),
                key_entities=merged_meta.get("key_entities", ""),
                last_updated=merged_meta.get("last_updated", ""),
                sample_questions=merged_meta.get("sample_questions", ""),
                section_path=h2_path,
            )
            chunks.append(chunk)
            current_h3 = ""
            h3_content_lines = []
            return
        
        # Standard H2 content handling
        if current_h3 and h3_content:
            flush_h3_chunk(current_h3, h3_content, {})
        elif current_h2:
            # No H3s found, create single chunk for entire H2
            h2_path = _build_section_path(current_section, current_h2, "")
            merged_meta = {**section_metadata, **h2_metadata}

            connector = _detect(h3_content, _CONNECTOR_RE) or _infer_connector_from_section(current_h2, current_section)
            sync_mode = _detect(h3_content, _SYNC_MODE_RE)
            destination = _detect(h3_content, _DEST_RE) or _infer_destination_from_section(current_h2, current_section)
            benchmark_type = _detect(h3_content, _BENCH_RE)

            chunk = Chunk(
                text=h2_path + "\n" + h3_content,
                raw_text=h3_content,
                chunk_type="prose",
                section=current_section,
                subsection=current_h2,
                subsubsection="",
                connector=connector,
                sync_mode=sync_mode,
                destination=destination,
                benchmark_type=benchmark_type,
                doc_url=merged_meta.get("doc_url", ""),
                tags=merged_meta.get("tags", ""),
                key_entities=merged_meta.get("key_entities", ""),
                last_updated=merged_meta.get("last_updated", ""),
                sample_questions=merged_meta.get("sample_questions", ""),
                section_path=h2_path,
            )
            chunks.append(chunk)

        current_h3 = ""
        h3_content_lines = []

    def flush_code() -> None:
        """Flush accumulated code block as a chunk."""
        nonlocal current_h3, h3_content_lines

        raw = "\n".join(code_buf).strip()
        if not raw:
            return

        # Detect language
        detected_lang = code_lang
        if not detected_lang:
            if raw.startswith("docker ") or "docker run" in raw or "docker compose" in raw:
                detected_lang = "bash"
            elif raw.startswith("curl ") or raw.startswith("wget "):
                detected_lang = "bash"
            elif ": " in raw and ("\"" in raw or "&" in raw):
                detected_lang = "yaml"
            elif raw.startswith("{") or raw.startswith("["):
                detected_lang = "json"
            elif "SELECT " in raw.upper() or "FROM " in raw.upper():
                detected_lang = "sql"

        # Create code chunk
        code_path = _build_section_path(current_section, current_h2, current_h3)
        merged_meta = {**section_metadata, **h2_metadata}

        connector = _detect(raw, _CONNECTOR_RE) or _infer_connector_from_section(current_h2, current_section)
        sync_mode = _detect(raw, _SYNC_MODE_RE)
        destination = _detect(raw, _DEST_RE) or _infer_destination_from_section(current_h2, current_section)
        benchmark_type = _detect(raw, _BENCH_RE)

        chunk = Chunk(
            text=code_path + "\n```" + detected_lang + "\n" + raw + "\n```",
            raw_text=raw,
            chunk_type="code",
            section=current_section,
            subsection=current_h2,
            subsubsection=current_h3,
            connector=connector,
            sync_mode=sync_mode,
            destination=destination,
            benchmark_type=benchmark_type,
            doc_url=merged_meta.get("doc_url", ""),
            tags=merged_meta.get("tags", ""),
            key_entities=merged_meta.get("key_entities", ""),
            last_updated=merged_meta.get("last_updated", ""),
            sample_questions=merged_meta.get("sample_questions", ""),
            section_path=code_path,
        )
        chunks.append(chunk)
        code_buf.clear()

    # Parse line by line
    i = 0
    while i < len(lines):
        line = lines[i]

        # ── Code fence toggle ─────────────────────────────────────────────
        if line.startswith("```"):
            if not in_code:
                flush_h2_content()  # Flush any pending H3 content
                in_code = True
                code_lang = line[3:].strip()
            else:
                flush_code()
                in_code = False
                code_lang = ""
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # ── H1 Section (§N or #) ──────────────────────────────────────────────
        # Support both legacy (§N) and standard markdown (#) H1 headers
        is_h1_legacy = re.match(r"^§\d+\s", line)
        is_h1_md = re.match(r"^#\s+", line) and not in_code
        
        if is_h1_legacy or is_h1_md:
            flush_h2_content()  # Flush previous H2
            current_section = line.strip()
            current_h2 = ""
            h2_metadata = {}
            section_metadata = {}

            # Look for metadata table following H1
            j = i + 1
            metadata_lines = []
            while j < len(lines) and j < i + 50:
                l = lines[j]
                ls = l.strip()
                # Skip empty lines at start
                if not metadata_lines and not ls:
                    j += 1
                    continue
                # Table border
                if "---" in ls and "**" not in ls:
                    if metadata_lines:
                        break  # End of table
                    j += 1
                    continue
                # Metadata field lines
                if "**DOC URL**" in l or "**SEE ALSO**" in l or "**TAGS**" in l or \
                   "**LAST" in l or "**KEY" in l or "**ANSWERS" in l or "**UPDATE" in l or \
                   "UPDATED**" in l or "ENTITIES**" in l or "LIKE**" in l or "WHEN**" in l:
                    metadata_lines.append(l)
                elif metadata_lines and ls:
                    # Continuation line
                    metadata_lines.append(l)
                elif metadata_lines and not ls:
                    # Empty line after metadata - might be end
                    j += 1
                    break
                j += 1

            if metadata_lines:
                meta_dict, _ = _extract_metadata_table(metadata_lines, 0)
                section_metadata = _parse_metadata_section(meta_dict)

            i += 1
            continue

        # ── H2 Subsection (N.N Title or ## Title) ────────────────────────────────────
        # Support both legacy (N.N) and standard markdown (##) H2 headers
        is_h2_legacy = re.match(r"^\d+\.\d+\s", line) and not re.match(r"^\d+\.\d+\.\d+\s", line)
        is_h2_md = re.match(r"^##\s+", line) and not in_code
        
        if is_h2_legacy or is_h2_md:
            flush_h2_content()  # Flush previous H2
            current_h2 = line.strip()
            h2_metadata = {}

            # Look for H2-specific metadata table
            j = i + 1
            metadata_lines = []
            while j < len(lines) and j < i + 30:
                l = lines[j]
                ls = l.strip()
                # Skip empty lines at start
                if not metadata_lines and not ls:
                    j += 1
                    continue
                # Table border
                if "---" in ls and "**" not in ls:
                    if metadata_lines:
                        break
                    j += 1
                    continue
                # Metadata field lines
                if "**DOC URL**" in l or "**SEE ALSO**" in l or "**TAGS**" in l or \
                   "**LAST" in l or "**KEY" in l or "**ANSWERS" in l or "**UPDATE" in l or \
                   "UPDATED**" in l or "ENTITIES**" in l or "LIKE**" in l or "WHEN**" in l:
                    metadata_lines.append(l)
                elif metadata_lines and ls:
                    metadata_lines.append(l)
                elif metadata_lines and not ls:
                    j += 1
                    break
                j += 1

            if metadata_lines:
                meta_dict, _ = _extract_metadata_table(metadata_lines, 0)
                h2_metadata = _parse_metadata_section(meta_dict)

            i += 1
            continue

        # ── H3 Sub-subsection (N.N.N Title or ### Title) ──────────────────────────────
        is_h3_legacy = re.match(r"^\d+\.\d+\.\d+\s", line)
        is_h3_md = re.match(r"^###\s+", line) and not in_code
        
        if is_h3_legacy or is_h3_md:
            flush_h2_content()  # Flush previous H3
            current_h3 = line.strip()
            i += 1
            continue

        # ── Regular content line ─────────────────────────────────────────
        if current_h2:
            h3_content_lines.append(line)

        i += 1

    # Flush remaining content
    flush_h2_content()
    if code_buf:
        flush_code()

    return chunks


def parse_file(path: Path = Config.DOCS_FILE) -> List[Chunk]:
    """
    Public entry point — parse and return all chunks.
    
    Supports:
      - Single file: path points to a .md/.mdx file
      - Directory: path points to a directory, recursively parse all .md/.mdx files
    """
    if path.is_file():
        return _parse_single_file(path)
    elif path.is_dir():
        return _parse_directory(path)
    else:
        log.error(f"Path not found: {path}")
        return []


def _parse_single_file(path: Path) -> List[Chunk]:
    """Parse a single markdown file."""
    log.info(f"Parsing {path} ...")
    
    # Read content for link extraction
    content = path.read_text(encoding="utf-8")
    rel_path = _get_relative_doc_path(path)
    category = get_doc_category(path)
    connector = infer_connector_from_path(path)
    setup_variant = infer_setup_variant_from_path(path)
    
    # Extract links from entire file
    internal_links, external_links, anchor_links, image_links = extract_links(content, rel_path)
    
    # Parse the file content
    chunks = parse_and_chunk(path)
    
    # Add file-level metadata to all chunks
    for chunk in chunks:
        if not chunk.doc_path:
            chunk.doc_path = rel_path
        if not chunk.doc_category:
            chunk.doc_category = category
        if not chunk.connector and connector:
            chunk.connector = connector
        if not chunk.variant and setup_variant:
            chunk.variant = setup_variant
        # Add links
        if not chunk.internal_links:
            chunk.internal_links = internal_links
        if not chunk.external_links:
            chunk.external_links = external_links
        if not chunk.anchor_links:
            chunk.anchor_links = anchor_links
        if not chunk.image_links:
            chunk.image_links = image_links

    log.info(f"Parsed {len(chunks)} chunks from {path.name}")
    return chunks


def _parse_directory(docs_root: Path) -> List[Chunk]:
    """
    Parse all markdown files in a directory tree.
    
    Each file becomes a logical "document" with its own chunks.
    Links are resolved relative to each file's location.
    """
    all_chunks: List[Chunk] = []
    md_files = list(docs_root.rglob("*.md")) + list(docs_root.rglob("*.mdx"))
    
    log.info(f"Found {len(md_files)} markdown files in {docs_root}")
    
    for file_path in sorted(md_files):
        # Skip archive/drafts directories
        if "/archive/" in str(file_path) or "/drafts/" in str(file_path):
            log.debug(f"Skipping archive/draft: {file_path}")
            continue
        
        chunks = _parse_file_with_metadata(file_path, docs_root)
        all_chunks.extend(chunks)
    
    log.info(f"Total: {len(all_chunks)} chunks from {len(md_files)} files")
    return all_chunks


def _get_relative_doc_path(file_path: Path, docs_root: Optional[Path] = None) -> str:
    """Get the relative path from docs root to the file."""
    if docs_root:
        try:
            return str(file_path.relative_to(docs_root))
        except ValueError:
            pass
    
    # Fallback: try to find "docs" in the path
    parts = file_path.parts
    for i, part in enumerate(parts):
        if part == "docs":
            return "/".join(parts[i+1:])
    
    return file_path.name


def _parse_file_with_metadata(file_path: Path, docs_root: Path) -> List[Chunk]:
    """
    Parse a single file with full metadata extraction.
    
    - Extract frontmatter
    - Detect redirects
    - Extract links
    - Add document-level metadata
    """
    content = file_path.read_text(encoding="utf-8")
    rel_path = _get_relative_doc_path(file_path, docs_root)
    category = get_doc_category(file_path)
    connector = infer_connector_from_path(file_path)
    setup_variant = infer_setup_variant_from_path(file_path)
    
    # Check for redirect page
    redirect_url = detect_redirect(content)
    is_redirect = redirect_url is not None
    
    if is_redirect:
        # Create a minimal chunk for redirect pages
        frontmatter = parse_frontmatter(content)
        chunk = Chunk(
            text=f"Redirect to {redirect_url}",
            raw_text=f"Redirect to {redirect_url}",
            chunk_type="prose",
            doc_url=redirect_url,
            doc_path=rel_path,
            doc_category=category,
            is_redirect=True,
            section=frontmatter.get("title", ""),
        )
        log.debug(f"Redirect page: {rel_path} → {redirect_url}")
        return [chunk]
    
    # Parse frontmatter
    frontmatter = parse_frontmatter(content)
    
    # Extract links from entire file
    internal_links, external_links, anchor_links, image_links = extract_links(content, rel_path)
    
    # Parse the file content
    chunks = parse_and_chunk(file_path)
    
    # Enrich chunks with file-level metadata
    for chunk in chunks:
        if not chunk.doc_path:
            chunk.doc_path = rel_path
        if not chunk.doc_category:
            chunk.doc_category = category
        if not chunk.connector and connector:
            chunk.connector = connector
        if not chunk.variant and setup_variant:
            chunk.variant = setup_variant
        
        # Add links to each chunk (copy from file-level extraction)
        # Optionally, could extract links per-chunk for more precision
        if not chunk.internal_links:
            chunk.internal_links = internal_links
        if not chunk.external_links:
            chunk.external_links = external_links
        if not chunk.anchor_links:
            chunk.anchor_links = anchor_links
        if not chunk.image_links:
            chunk.image_links = image_links
        
        # Add frontmatter-derived doc_url if not already set
        if not chunk.doc_url and frontmatter.get("title"):
            # Construct doc_url from path
            url_path = rel_path.replace(".mdx", "").replace(".md", "")
            chunk.doc_url = f"/docs/{url_path}"

    log.debug(f"Parsed {len(chunks)} chunks from {rel_path}")
    return chunks
