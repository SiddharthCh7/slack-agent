"""
OLake Docs Chunker & ChromaDB Indexer
======================================

Parses docs/olake_docs.md hierarchically, produces richly-annotated chunks,
and ingests them into two ChromaDB collections:

  olake_docs  — prose sections, metadata tables, terminology definitions
  olake_code  — code blocks (config examples, SQL, shell commands)

Chunking strategy (no information loss):
  §N              → one "section header" chunk (metadata + intro paragraph)
  §N.A            → one chunk per H2 subsection         (≤ ~1500 chars)
  §N.A.B          → one chunk per H3 subsection         (≤ ~1000 chars)
  Table rows      → combined as a single chunk per table (atomic facts)
  Code blocks     → one chunk per code block (tagged as code)
  Overlap         → each sub-chunk inherits full parent metadata

Rich metadata per chunk:
  section         — e.g. "§4 Source Connectors"
  subsection      — "4.1 PostgreSQL Connector"
  subsubsection   — "4.1.2 CDC Prerequisites"
  connector       — postgres | mysql | mongodb | oracle | kafka | ""
  sync_mode       — full_refresh | incremental | cdc | strict_cdc | all | ""
  destination     — iceberg | parquet | s3 | gcs | minio | ""
  benchmark_type  — full_load | cdc | streaming | ""
  doc_url         — canonical URL extracted from metadata table
  tags            — comma-separated tag string
  chunk_type      — prose | table | code | metadata
  chunk_id        — deterministic ID for deduplication

Usage:
  python -m agent.scripts.index_docs [--reset]

  --reset  Drops and recreates both collections before ingesting.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DOCS_FILE = Path(__file__).parent.parent.parent / "docs" / "olake_docs.md"
COLLECTION_DOCS = "olake_docs"
COLLECTION_CODE = "olake_code"

MAX_CHUNK_CHARS = 1500      # hard limit per prose chunk
OVERLAP_CHARS = 150         # overlap between consecutive sub-chunks of same section

# Connector detection
_CONNECTOR_PATTERNS: Dict[str, List[str]] = {
    "postgres": ["postgres", "postgresql", "pgoutput", "wal", "rds postgres", "aurora postgres"],
    "mysql": ["mysql", "binlog", "aurora mysql", "rds mysql"],
    "mongodb": ["mongodb", "mongo", "oplog", "change stream", "atlas"],
    "oracle": ["oracle"],
    "kafka": ["kafka", "consumer group"],
}

_SYNC_MODE_PATTERNS: Dict[str, List[str]] = {
    "cdc": ["strict cdc", "cdc", "change data capture", "binlog", "oplog", "pgoutput"],
    "full_refresh": ["full refresh"],
    "incremental": ["incremental"],
}

_DESTINATION_PATTERNS: Dict[str, List[str]] = {
    "iceberg": ["iceberg"],
    "parquet": ["parquet"],
    "s3": [" s3 ", "aws s3", "amazon s3"],
    "gcs": ["gcs", "google cloud storage"],
    "minio": ["minio"],
}

_BENCHMARK_PATTERNS: Dict[str, List[str]] = {
    "full_load": ["full load rps", "rps (full)", "full load"],
    "cdc": ["cdc rps", "rps (cdc)", "cdc benchmark"],
    "streaming": ["mps", "streaming"],
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    text: str
    chunk_type: str          # prose | table | code | metadata
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
                f"{self.section}|{self.subsection}|{self.subsubsection}|{self.text[:120]}".encode()
            ).hexdigest()[:16]

    def to_metadata(self) -> Dict:
        return {
            "section": self.section,
            "subsection": self.subsection,
            "subsubsection": self.subsubsection,
            "connector": self.connector,
            "sync_mode": self.sync_mode,
            "destination": self.destination,
            "benchmark_type": self.benchmark_type,
            "doc_url": self.doc_url,
            "tags": self.tags,
            "chunk_type": self.chunk_type,
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _detect_connector(text: str) -> str:
    tl = text.lower()
    for connector, patterns in _CONNECTOR_PATTERNS.items():
        if any(p in tl for p in patterns):
            return connector
    return ""


def _detect_sync_mode(text: str) -> str:
    tl = text.lower()
    # Order matters: strict_cdc first → cdc → ...
    for mode, patterns in _SYNC_MODE_PATTERNS.items():
        if any(p in tl for p in patterns):
            return mode
    return ""


def _detect_destination(text: str) -> str:
    tl = text.lower()
    for dest, patterns in _DESTINATION_PATTERNS.items():
        if any(p in tl for p in patterns):
            return dest
    return ""


def _detect_benchmark(text: str) -> str:
    tl = text.lower()
    for btype, patterns in _BENCHMARK_PATTERNS.items():
        if any(p in tl for p in patterns):
            return btype
    return ""


def _split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> List[str]:
    """Split text on paragraph boundaries when it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n\n+", text)
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            # Start new chunk with overlap from end of previous
            tail = current[-overlap:] if len(current) > overlap else current
            current = (tail + "\n\n" + para).strip()
    if current:
        chunks.append(current)
    return chunks or [text]


def _extract_metadata_table(block: str) -> Dict[str, str]:
    """
    Parse the dashed key-value metadata tables that appear at the top of each §-section.
    Returns dict with keys: doc_url, tags, key_entities, answers_like.
    """
    meta: Dict[str, str] = {}
    # Patterns: **DOC URL**   https://...
    for key_pat, meta_key in [
        (r"\*\*DOC URL\*\*\s+(https?://\S+)", "doc_url"),
        (r"\*\*TAGS\*\*\s+(.+?)(?=\*\*|\Z)", "tags"),
        (r"\*\*KEY\s+ENTITIES?\*\*\s+(.+?)(?=\*\*|\Z)", "key_entities"),
        (r"\*\*ANSWERS\s+QUESTIONS?\s+LIKE\*\*\s+(.+?)(?=\*\*|\Z)", "answers_like"),
    ]:
        m = re.search(key_pat, block, re.DOTALL | re.IGNORECASE)
        if m:
            val = m.group(1).strip().replace("\n", " ")
            val = re.sub(r"\s{2,}", " ", val)
            meta[meta_key] = val
    return meta


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

class OLakeDocParser:
    """
    Hierarchical parser for docs/olake_docs.md.

    Identifies:
      §N sections       (top-level — marked with §N prefix)
      N.A subsections   (e.g. 4.1 PostgreSQL Connector)
      N.A.B sub-subs    (e.g. 4.1.2 CDC Prerequisites)
      Tables            (lines forming dashed-border tables)
      Code blocks       (lines starting with >) 
    """

    def __init__(self, path: Path = DOCS_FILE):
        self.path = path
        self.chunks: List[Chunk] = []

    # ---- helpers ----

    def _make_chunk(
        self,
        text: str,
        chunk_type: str,
        section: str,
        subsection: str,
        subsubsection: str,
        meta: Dict,
        extra_context: str = "",
    ) -> List[Chunk]:
        """Build one or more Chunk objects, splitting if text is too long."""
        full_text = text.strip()
        if not full_text:
            return []

        connector = _detect_connector(section + " " + subsection + " " + subsubsection + " " + full_text)
        sync_mode = _detect_sync_mode(section + " " + full_text)
        destination = _detect_destination(section + " " + full_text)
        benchmark_type = _detect_benchmark(full_text)

        base = dict(
            chunk_type=chunk_type,
            section=section,
            subsection=subsection,
            subsubsection=subsubsection,
            connector=connector,
            sync_mode=sync_mode,
            destination=destination,
            benchmark_type=benchmark_type,
            doc_url=meta.get("doc_url", ""),
            tags=meta.get("tags", ""),
        )

        if chunk_type in ("table", "code") or len(full_text) <= MAX_CHUNK_CHARS:
            return [Chunk(text=full_text, **base)]

        # Split long prose
        result = []
        for part in _split_long_text(full_text):
            result.append(Chunk(text=part, **base))
        return result

    # ---- table detection ----

    @staticmethod
    def _is_table_line(line: str) -> bool:
        stripped = line.strip()
        return bool(
            stripped.startswith("|")
            or re.match(r"^\s*-{3,}", stripped)     # --- dividers
            or re.match(r"^\s*\+[-+]{3,}", stripped)  # +-+-+ dividers
        )

    @staticmethod
    def _is_code_line(line: str) -> bool:
        return line.startswith(">")

    # ---- parse ----

    def parse(self) -> List[Chunk]:
        raw = self.path.read_text(encoding="utf-8")
        lines = raw.splitlines()

        current_section = ""
        current_meta: Dict[str, str] = {}
        current_subsection = ""
        current_subsubsection = ""

        # Buffers
        prose_buf: List[str] = []
        table_buf: List[str] = []
        code_buf: List[str] = []
        meta_buf: List[str] = []

        in_table = False
        in_code = False
        in_meta_block = False  # metadata table at top of each §

        def flush_prose():
            nonlocal prose_buf
            text = "\n".join(prose_buf).strip()
            if text:
                self.chunks.extend(
                    self._make_chunk(text, "prose", current_section,
                                     current_subsection, current_subsubsection, current_meta)
                )
            prose_buf = []

        def flush_table():
            nonlocal table_buf
            text = "\n".join(table_buf).strip()
            if text:
                context = f"[TABLE within {current_subsection or current_section}]\n"
                self.chunks.extend(
                    self._make_chunk(context + text, "table", current_section,
                                     current_subsection, current_subsubsection, current_meta)
                )
            table_buf = []

        def flush_code():
            nonlocal code_buf
            text = "\n".join(code_buf).strip()
            if text:
                context = f"[CODE within {current_subsubsection or current_subsection or current_section}]\n"
                self.chunks.extend(
                    self._make_chunk(context + text, "code", current_section,
                                     current_subsection, current_subsubsection, current_meta)
                )
            code_buf = []

        def flush_meta():
            nonlocal meta_buf, current_meta
            text = "\n".join(meta_buf).strip()
            if text:
                extracted = _extract_metadata_table(text)
                current_meta.update(extracted)
                # Store the raw metadata block as a "metadata" chunk for retrieval
                self.chunks.extend(
                    self._make_chunk(text, "metadata", current_section,
                                     current_subsection, current_subsubsection, current_meta)
                )
            meta_buf = []

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # ----------------------------------------------------------------
            # §N top-level section header
            # ----------------------------------------------------------------
            section_match = re.match(r"^§(\d+)\s+(.+)", stripped)
            if section_match:
                # Flush everything
                flush_prose(); flush_table(); flush_code()
                current_section = stripped
                current_subsection = ""
                current_subsubsection = ""
                current_meta = {}
                # Next lines until the first non-metadata line form the section header chunk
                # Accumulate the dashed metadata table that follows each §
                in_meta_block = True
                meta_buf = [line]
                i += 1
                continue

            # ----------------------------------------------------------------
            # N.A.B sub-subsection (e.g. "4.1.2 CDC Prerequisites")
            # ----------------------------------------------------------------
            subsub_match = re.match(r"^(\d+\.\d+\.\d+)\s+(.+)", stripped)
            if subsub_match and not self._is_table_line(line):
                flush_prose(); flush_table(); flush_code()
                if in_meta_block:
                    flush_meta()
                    in_meta_block = False
                current_subsubsection = stripped
                prose_buf = [stripped]
                i += 1
                continue

            # ----------------------------------------------------------------
            # N.A subsection (e.g. "4.1 PostgreSQL Connector")
            # ----------------------------------------------------------------
            sub_match = re.match(r"^(\d+\.\d+)\s+(.+)", stripped)
            if sub_match and not self._is_table_line(line):
                flush_prose(); flush_table(); flush_code()
                if in_meta_block:
                    flush_meta()
                    in_meta_block = False
                current_subsection = stripped
                current_subsubsection = ""
                prose_buf = [stripped]
                i += 1
                continue

            # ----------------------------------------------------------------
            # Metadata block (dashed tables that immediately follow §N)
            # ----------------------------------------------------------------
            if in_meta_block:
                # Metadata block ends when we see a subsection heading or a non-empty
                # line that doesn't look like a table or key-value metadata line
                looks_like_meta = (
                    self._is_table_line(line)
                    or re.search(r"\*\*(DOC URL|SEE ALSO|TAGS|KEY|ANSWERS|UPDATE|LAST)\*\*", stripped)
                    or stripped == ""
                    or re.match(r"^\s+", line)  # indented continuation
                )
                if looks_like_meta:
                    meta_buf.append(line)
                    i += 1
                    continue
                else:
                    # End of metadata block
                    flush_meta()
                    in_meta_block = False
                    # Fall through to normal processing

            # ----------------------------------------------------------------
            # Code block (lines starting with >)
            # ----------------------------------------------------------------
            if self._is_code_line(line):
                if not in_code:
                    flush_prose(); flush_table()
                    in_code = True
                code_buf.append(line.lstrip("> "))
                i += 1
                continue
            elif in_code:
                # End of code block (blank line or non-code line)
                if stripped == "":
                    code_buf.append("")
                    i += 1
                    continue
                flush_code()
                in_code = False

            # ----------------------------------------------------------------
            # Table detection (dashed borders or | pipes)
            # ----------------------------------------------------------------
            is_tl = self._is_table_line(line)
            if is_tl:
                if not in_table:
                    flush_prose()
                    in_table = True
                table_buf.append(line)
                i += 1
                continue
            elif in_table:
                if stripped == "":
                    # Tables can have blank separator lines inside
                    table_buf.append(line)
                    i += 1
                    continue
                flush_table()
                in_table = False

            # ----------------------------------------------------------------
            # Regular prose line
            # ----------------------------------------------------------------
            prose_buf.append(line)
            i += 1

        # Flush remaining buffers
        flush_prose()
        flush_table()
        flush_code()
        if in_meta_block:
            flush_meta()

        log.info(f"Parsed {len(self.chunks)} chunks from {self.path}")
        return self.chunks


# ---------------------------------------------------------------------------
# Qdrant ingestion
# ---------------------------------------------------------------------------

def get_qdrant_client(vector_db_url: str):
    from qdrant_client import QdrantClient
    if vector_db_url.startswith("http"):
        return QdrantClient(url=vector_db_url)
    else:
        # Local persistent path
        path = vector_db_url.replace("sqlite://", "") if vector_db_url.startswith("sqlite") else vector_db_url
        return QdrantClient(path=path)


def ingest(
    chunks: List[Chunk],
    vector_db_url: str,
    reset: bool = False,
    batch_size: int = 64,
) -> None:
    client = get_qdrant_client(vector_db_url)

    _get_or_create_collection(client, COLLECTION_DOCS, reset)
    _get_or_create_collection(client, COLLECTION_CODE, reset)

    docs_chunks = [c for c in chunks if c.chunk_type != "code"]
    code_chunks = [c for c in chunks if c.chunk_type == "code"]

    log.info(f"Ingesting {len(docs_chunks)} doc chunks → {COLLECTION_DOCS}")
    _batch_upsert(client, COLLECTION_DOCS, docs_chunks, batch_size)

    log.info(f"Ingesting {len(code_chunks)} code chunks → {COLLECTION_CODE}")
    _batch_upsert(client, COLLECTION_CODE, code_chunks, batch_size)

    log.info("✅ Ingestion complete.")
    try:
        docs_count = client.count(COLLECTION_DOCS).count
        code_count = client.count(COLLECTION_CODE).count
        log.info(f"  {COLLECTION_DOCS}: {docs_count} total documents")
        log.info(f"  {COLLECTION_CODE}: {code_count} total documents")
    except Exception as e:
        log.warning(f"Could not fetch final counts: {e}")


def _get_or_create_collection(client, name: str, reset: bool):
    from qdrant_client.models import VectorParams, Distance
    
    if reset:
        try:
            client.delete_collection(name)
            log.info(f"Dropped collection '{name}'")
        except Exception:
            pass

    if not client.collection_exists(name):
        # text-embedding-004 produces 768-dimensional vectors
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
        log.info(f"Created collection '{name}'")


def _batch_upsert(client, collection_name: str, chunks: List[Chunk], batch_size: int) -> None:
    from qdrant_client.models import PointStruct
    from agent.embedding import embed_texts
    import uuid

    if not chunks:
        return

    # Deduplicate by chunk_id
    seen = set()
    deduped = []
    for c in chunks:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            deduped.append(c)

    for start in range(0, len(deduped), batch_size):
        batch = deduped[start: start + batch_size]
        
        # 1. Embed texts using Gemini
        texts = [c.text for c in batch]
        embeddings = embed_texts(texts)
        
        # 2. Prepare Qdrant points
        points = []
        for i, c in enumerate(batch):
            # Qdrant needs UUIDs or integers. We convert the 16-char hex to a UUID.
            # Pad or manipulate the 16-char chunk_id to form a valid UUID.
            # chunk_id is a 16-char hex string (64 bits). UUID is 128 bits.
            # We can zero-pad or duplicate it to make 32 hex chars.
            padded_hex = (c.chunk_id * 2)[:32] 
            point_id = str(uuid.UUID(padded_hex))
            
            payload = c.to_metadata()
            payload["text"] = c.text  # Store the actual text in the payload for retrieval
            
            points.append(PointStruct(
                id=point_id,
                vector=embeddings[i],
                payload=payload
            ))
            
        client.upsert(
            collection_name=collection_name,
            points=points
        )
        log.info(f"  Upserted batch {start // batch_size + 1} ({len(batch)} chunks)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Index OLake docs into Qdrant")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate collections before ingesting")
    parser.add_argument("--vector-db-url", default=None,
                        help="Qdrant URL (default: from Config.VECTOR_DB_URL or ./qdrant_db)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print chunk stats without ingesting")
    args = parser.parse_args()

    # Resolve URL
    vector_db_url = args.vector_db_url
    if not vector_db_url:
        try:
            from agent.config import Config
            vector_db_url = Config.VECTOR_DB_URL
        except Exception:
            vector_db_url = "http://localhost:8000"

    log.info(f"Parsing {DOCS_FILE} ...")
    p = OLakeDocParser()
    chunks = p.parse()

    # Stats
    type_counts = {}
    for c in chunks:
        type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1
    connector_counts = {}
    for c in chunks:
        if c.connector:
            connector_counts[c.connector] = connector_counts.get(c.connector, 0) + 1

    log.info(f"\n=== Chunk Statistics ===")
    log.info(f"Total:       {len(chunks)}")
    for k, v in sorted(type_counts.items()):
        log.info(f"  {k:12s}: {v}")
    log.info(f"By connector: {connector_counts}")

    if args.dry_run:
        log.info("Dry run — not ingesting.")
        # Print sample chunks
        for c in chunks[:5]:
            print(f"\n--- [{c.chunk_type}] {c.section} / {c.subsection} ---")
            print(c.text[:300])
        return

    ingest(chunks, vector_db_url, reset=args.reset)


if __name__ == "__main__":
    main()
