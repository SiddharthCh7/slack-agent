#!/usr/bin/env python3
"""
OLake Documentation Ingestion Script.

Robust, memory-efficient ingestion for OLake documentation into Qdrant.

Features:
  - Memory-efficient batch processing with GC hints
  - Checkpoint-based crash recovery (resume from last successful batch)
  - Progress tracking with ETA
  - Retry logic with exponential backoff for Qdrant operations
  - Comprehensive logging to file and console
  - Data validation before ingestion
  - Dense embeddings with Qdrant full-text index (no sparse vectors)

Usage:
  # Full ingestion with reset
  python ingest_docs.py --reset

  # Resume from checkpoint
  python ingest_docs.py

  # Ingest only docs collection
  python ingest_docs.py --collection docs

  # Ingest only code collection
  python ingest_docs.py --collection code

  # Dry run (validate only)
  python ingest_docs.py --dry-run
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Disable PyTorch parallelism to prevent crashes on macOS
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from config import Config
from chunker import parse_file, Chunk
from embedder import embed_documents, vector_size
from indexer import ensure_collection, upsert_chunks, _client
from ingest_utils import (
    Checkpoint,
    CheckpointManager,
    ProgressTracker,
    batch_generator,
    retry_with_backoff,
    get_memory_usage_mb,
    check_memory_threshold,
    validate_chunk_data,
    validate_embedding,
    setup_ingestion_logging,
    log_error_details,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Ingestion settings
BATCH_SIZE = int(os.getenv("INGEST_BATCH_SIZE", "32"))
MAX_RETRIES = int(os.getenv("INGEST_MAX_RETRIES", "3"))
MEMORY_THRESHOLD_MB = float(os.getenv("INGEST_MEMORY_THRESHOLD_MB", "2048"))
CHECKPOINT_INTERVAL = int(os.getenv("INGEST_CHECKPOINT_INTERVAL", "10"))  # Save every N batches
LOG_FILE = os.getenv("INGEST_LOG_FILE", "./ingest.log")
CHECKPOINT_DIR = os.getenv("CHECKPOINT_DIR", "./.ingest_checkpoints")

# Collection names
DOCS_COLLECTION = Config.DOCS_COLLECTION
CODE_COLLECTION = Config.CODE_COLLECTION

# ---------------------------------------------------------------------------
# Ingestion class
# ---------------------------------------------------------------------------


class DocIngester:
    """Handles document ingestion with crash recovery and progress tracking."""

    def __init__(
        self,
        docs_path: Path,
        collection: str = "both",
        reset: bool = False,
        dry_run: bool = False,
    ):
        self.docs_path = docs_path
        self.target_collection = collection  # "docs", "code", or "both"
        self.reset = reset
        self.dry_run = dry_run

        self.checkpoint_manager = CheckpointManager(CHECKPOINT_DIR)
        self.expected_vector_dim = vector_size()

        # Set up logging
        self.logger = setup_ingestion_logging(
            log_file=LOG_FILE if not dry_run else None,
            level=logging.INFO,
        )

        # Statistics
        self.stats = {
            "total_chunks": 0,
            "docs_chunks": 0,
            "code_chunks": 0,
            "upserted_docs": 0,
            "upserted_code": 0,
            "failed": 0,
            "start_time": "",
            "end_time": "",
            "errors": [],
        }

    def run(self) -> dict:
        """Execute the ingestion pipeline."""
        self.stats["start_time"] = datetime.now(timezone.utc).isoformat()
        self.logger.info(f"Starting ingestion from {self.docs_path}")
        self.logger.info(f"Target: {self.target_collection} collection(s)")
        self.logger.info(f"Reset: {self.reset}, Dry run: {self.dry_run}")
        self.logger.info(f"Batch size: {BATCH_SIZE}, Max retries: {MAX_RETRIES}")

        try:
            # Validate source file
            if not self.docs_path.exists():
                raise FileNotFoundError(f"Source file not found: {self.docs_path}")

            # Initialize collections
            if not self.dry_run:
                self._initialize_collections()

            # Parse chunks
            self.logger.info("Parsing document...")
            all_chunks = parse_file(self.docs_path)
            self.stats["total_chunks"] = len(all_chunks)
            self.logger.info(f"Parsed {len(all_chunks)} total chunks")

            # Separate docs and code chunks
            docs_chunks = [c for c in all_chunks if c.chunk_type != "code"]
            code_chunks = [c for c in all_chunks if c.chunk_type == "code"]
            self.stats["docs_chunks"] = len(docs_chunks)
            self.stats["code_chunks"] = len(code_chunks)
            self.logger.info(f"  Docs chunks: {len(docs_chunks)}")
            self.logger.info(f"  Code chunks: {len(code_chunks)}")

            # Ingest docs collection
            if self.target_collection in ("both", "docs") and docs_chunks:
                self._ingest_collection(
                    collection=DOCS_COLLECTION,
                    chunks=docs_chunks,
                    checkpoint_key="docs",
                )

            # Ingest code collection
            if self.target_collection in ("both", "code") and code_chunks:
                self._ingest_collection(
                    collection=CODE_COLLECTION,
                    chunks=code_chunks,
                    checkpoint_key="code",
                )

            # Success
            self.stats["end_time"] = datetime.now(timezone.utc).isoformat()
            self.logger.info("✓ Ingestion completed successfully")
            self._log_summary()

            return {
                "ok": True,
                "stats": self.stats,
            }

        except Exception as e:
            self.stats["end_time"] = datetime.now(timezone.utc).isoformat()
            self.logger.error(f"Ingestion failed: {e}")
            log_error_details(e)
            self.stats["errors"].append(str(e))

            return {
                "ok": False,
                "error": str(e),
                "stats": self.stats,
            }

    def _initialize_collections(self) -> None:
        """Create or reset Qdrant collections."""
        self.logger.info("Initializing collections...")

        if self.target_collection in ("both", "docs"):
            ensure_collection(DOCS_COLLECTION, drop_first=self.reset)
            if self.reset:
                self.logger.info(f"  Reset collection: {DOCS_COLLECTION}")
            else:
                self.logger.info(f"  Collection ready: {DOCS_COLLECTION}")

        if self.target_collection in ("both", "code"):
            ensure_collection(CODE_COLLECTION, drop_first=self.reset)
            if self.reset:
                self.logger.info(f"  Reset collection: {CODE_COLLECTION}")
            else:
                self.logger.info(f"  Collection ready: {CODE_COLLECTION}")

    def _ingest_collection(
        self,
        collection: str,
        chunks: List[Chunk],
        checkpoint_key: str,
    ) -> None:
        """Ingest chunks into a specific collection."""
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"Ingesting {len(chunks)} chunks into {collection}")
        self.logger.info(f"{'='*60}")

        # Load checkpoint for crash recovery
        checkpoint = self.checkpoint_manager.load(checkpoint_key)
        start_idx = 0

        if checkpoint and not self.reset:
            if checkpoint.status == "completed":
                self.logger.info(f"Checkpoint found - {checkpoint_key} already completed. Skipping.")
                return

            start_idx = checkpoint.processed_items
            self.logger.info(
                f"Resuming from checkpoint: {start_idx}/{len(chunks)} processed"
            )
            if checkpoint.errors:
                self.logger.warning(f"Previous errors: {len(checkpoint.errors)}")
        else:
            checkpoint = Checkpoint(
                collection=collection,
                total_items=len(chunks),
                start_time=datetime.now(timezone.utc).isoformat(),
                status="running",
            )

        # Initialize progress tracker
        progress = ProgressTracker(total=len(chunks), batch_size=BATCH_SIZE)
        progress.processed = start_idx

        # Process in batches
        batch_num = 0
        current_idx = start_idx

        for batch in batch_generator(chunks[start_idx:], batch_size=BATCH_SIZE, max_batches_before_gc=50):
            # GC hint
            if not batch:
                gc.collect()
                if check_memory_threshold(MEMORY_THRESHOLD_MB):
                    self.logger.warning("Memory threshold exceeded, forcing GC")
                    gc.collect()
                continue

            batch_num += 1
            batch_start = current_idx
            batch_end = current_idx + len(batch)

            try:
                # Validate batch
                valid_chunks, invalid_count = self._validate_batch(batch, collection)

                if not valid_chunks:
                    self.logger.warning(f"Batch {batch_num}: All {len(batch)} chunks invalid, skipping")
                    progress.update(len(batch), failed=True)
                    checkpoint.failed_items += invalid_count
                    current_idx = batch_end
                    continue

                if invalid_count > 0:
                    self.logger.warning(f"Batch {batch_num}: {invalid_count} invalid chunks filtered out")

                # Embed batch
                self.logger.debug(f"Batch {batch_num}: Embedding {len(valid_chunks)} chunks...")
                texts = [c.text for c in valid_chunks]

                if self.dry_run:
                    dense_vectors = [[0.0] * self.expected_vector_dim] * len(valid_chunks)
                else:
                    dense_vectors = embed_documents(texts)

                # Validate embeddings
                valid_vectors = []
                valid_chunks_filtered = []
                for chunk, vec in zip(valid_chunks, dense_vectors):
                    vec_valid, vec_err = validate_embedding(vec, self.expected_vector_dim)
                    if vec_valid:
                        valid_vectors.append(vec)
                        valid_chunks_filtered.append(chunk)
                    else:
                        self.logger.warning(f"Invalid embedding for chunk {chunk.chunk_id}: {vec_err}")
                        progress.update(1, failed=True)

                # Upsert to Qdrant
                if valid_vectors and not self.dry_run:
                    self.logger.debug(f"Batch {batch_num}: Upserting to Qdrant...")

                    def upsert_fn():
                        return upsert_chunks(
                            collection=collection,
                            chunks=valid_chunks_filtered,
                            vectors=valid_vectors,
                        )

                    upserted = retry_with_backoff(
                        upsert_fn,
                        max_retries=MAX_RETRIES,
                        exceptions=(Exception,),
                    )
                    self.stats["upserted_docs" if collection == DOCS_COLLECTION else "upserted_code"] += upserted
                    self.logger.debug(f"Batch {batch_num}: Upserted {upserted} chunks")

                # Update progress
                progress.update(len(batch))
                current_idx = batch_end
                checkpoint.processed_items = current_idx
                if valid_chunks_filtered:
                    checkpoint.last_chunk_id = valid_chunks_filtered[-1].chunk_id

                # Save checkpoint periodically
                if batch_num % CHECKPOINT_INTERVAL == 0:
                    self.checkpoint_manager.save(checkpoint)
                    self.logger.debug(f"Checkpoint saved at {current_idx}/{len(chunks)}")

                # Report progress
                if progress.should_report(interval_seconds=15.0):
                    prefix = f"[{collection}] "
                    self.logger.info(progress.report(prefix))

            except Exception as e:
                self.logger.error(f"Batch {batch_num} failed: {e}")
                log_error_details(e, {"batch_start": batch_start, "batch_end": batch_end})
                progress.update(len(batch), failed=True)
                checkpoint.failed_items += len(batch)
                checkpoint.errors.append(f"Batch {batch_num}: {str(e)}")
                current_idx = batch_end
                # Continue with next batch instead of failing entirely
                continue

        # Final checkpoint save and cleanup
        checkpoint.status = "completed"
        checkpoint.end_time = datetime.now(timezone.utc).isoformat()
        self.checkpoint_manager.save(checkpoint)
        self.logger.info(f"✓ {collection} ingestion complete: {progress.processed}/{len(chunks)} chunks")

        # Clean up checkpoint on success
        if progress.failed == 0:
            self.checkpoint_manager.delete(checkpoint_key)
            self.logger.info(f"Cleaned up checkpoint for {checkpoint_key}")

    def _validate_batch(
        self,
        batch: List[Chunk],
        collection: str,
    ) -> Tuple[List[Chunk], int]:
        """
        Validate a batch of chunks.

        Returns:
            Tuple of (valid_chunks, invalid_count)
        """
        valid = []
        invalid_count = 0

        for chunk in batch:
            is_valid, errors = validate_chunk_data(chunk)
            if is_valid:
                valid.append(chunk)
            else:
                invalid_count += 1
                self.logger.warning(f"Invalid chunk {chunk.chunk_id}: {', '.join(errors)}")

        return (valid, invalid_count)

    def _log_summary(self) -> None:
        """Log ingestion summary."""
        self.logger.info("\n" + "="*60)
        self.logger.info("INGESTION SUMMARY")
        self.logger.info("="*60)
        self.logger.info(f"Total chunks parsed:     {self.stats['total_chunks']}")
        self.logger.info(f"  - Docs chunks:         {self.stats['docs_chunks']}")
        self.logger.info(f"  - Code chunks:         {self.stats['code_chunks']}")
        self.logger.info(f"Docs chunks upserted:    {self.stats['upserted_docs']}")
        self.logger.info(f"Code chunks upserted:    {self.stats['upserted_code']}")
        self.logger.info(f"Failed:                  {self.stats['failed']}")
        self.logger.info(f"Start time:              {self.stats['start_time']}")
        self.logger.info(f"End time:                {self.stats['end_time']}")

        if self.stats["errors"]:
            self.logger.warning(f"Errors encountered: {len(self.stats['errors'])}")
            for err in self.stats["errors"][-5:]:
                self.logger.warning(f"  - {err}")

        self.logger.info("="*60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest OLake documentation into Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--path", "-p",
        type=Path,
        default=Config.DOCS_FILE,
        help=f"Path to documentation file (default: {Config.DOCS_FILE})",
    )
    parser.add_argument(
        "--collection", "-c",
        type=str,
        choices=["docs", "code", "both"],
        default="both",
        help="Which collection(s) to ingest (default: both)",
    )
    parser.add_argument(
        "--reset", "-r",
        action="store_true",
        help="Drop and recreate collections before ingesting",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Validate and parse only, don't upsert to Qdrant",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=BATCH_SIZE,
        help=f"Batch size for embedding and upsert (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--log-level", "-l",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Update global settings (must be done before creating DocIngester)
    if args.batch_size != BATCH_SIZE:
        globals()["BATCH_SIZE"] = args.batch_size

    # Run ingestion
    ingester = DocIngester(
        docs_path=args.path,
        collection=args.collection,
        reset=args.reset,
        dry_run=args.dry_run,
    )
    result = ingester.run()

    # Exit code
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
