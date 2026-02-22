"""
Shared utilities for robust document ingestion.

Features:
  - Memory-efficient batch processing
  - Checkpoint-based crash recovery
  - Progress tracking with ETA
  - Retry logic with exponential backoff
  - Comprehensive logging
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from config import Config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Checkpoint management for crash recovery
# ---------------------------------------------------------------------------

@dataclass
class Checkpoint:
    """Tracks ingestion progress for crash recovery."""
    collection: str
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    last_chunk_id: str = ""
    last_updated: str = ""
    errors: List[str] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    status: str = "pending"  # pending, running, completed, failed

    def to_dict(self) -> dict:
        return {
            "collection": self.collection,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "failed_items": self.failed_items,
            "last_chunk_id": self.last_chunk_id,
            "last_updated": self.last_updated,
            "errors": self.errors[-10:],  # Keep last 10 errors
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        return cls(
            collection=data.get("collection", ""),
            total_items=data.get("total_items", 0),
            processed_items=data.get("processed_items", 0),
            failed_items=data.get("failed_items", 0),
            last_chunk_id=data.get("last_chunk_id", ""),
            last_updated=data.get("last_updated", ""),
            errors=data.get("errors", []),
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            status=data.get("status", "pending"),
        )


class CheckpointManager:
    """Manages checkpoint files for crash recovery."""

    def __init__(self, checkpoint_dir: str = "./.ingest_checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _checkpoint_path(self, collection: str) -> Path:
        """Get checkpoint file path for a collection."""
        safe_name = collection.replace("/", "_").replace("\\", "_")
        return self.checkpoint_dir / f"{safe_name}.json"

    def load(self, collection: str) -> Optional[Checkpoint]:
        """Load checkpoint for a collection."""
        path = self._checkpoint_path(collection)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Checkpoint.from_dict(data)
        except Exception as e:
            log.warning(f"Failed to load checkpoint for {collection}: {e}")
            return None

    def save(self, checkpoint: Checkpoint) -> None:
        """Save checkpoint for a collection."""
        checkpoint.last_updated = datetime.now(timezone.utc).isoformat()
        path = self._checkpoint_path(checkpoint.collection)
        path.write_text(json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8")

    def delete(self, collection: str) -> None:
        """Delete checkpoint after successful completion."""
        path = self._checkpoint_path(collection)
        if path.exists():
            path.unlink()

    def cleanup_old(self, max_age_hours: int = 24) -> None:
        """Remove checkpoints older than max_age_hours."""
        now = datetime.now(timezone.utc)
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                last_updated = data.get("last_updated", "")
                if last_updated:
                    # Handle both timezone-aware and naive datetime strings
                    last_time = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    age = now - last_time
                    if age > timedelta(hours=max_age_hours):
                        path.unlink()
                        log.info(f"Cleaned up old checkpoint: {path.name}")
            except Exception as e:
                log.warning(f"Failed to cleanup checkpoint {path.name}: {e}")


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

@dataclass
class ProgressTracker:
    """Tracks and reports ingestion progress."""
    total: int
    processed: int = 0
    failed: int = 0
    start_time: float = field(default_factory=time.time)
    last_report: float = field(default_factory=time.time)
    batch_size: int = 64

    def update(self, count: int = 1, failed: bool = False) -> None:
        """Update progress counters."""
        if failed:
            self.failed += count
        else:
            self.processed += count

    def eta(self) -> Optional[str]:
        """Estimate time remaining."""
        if self.processed == 0:
            return None
        elapsed = time.time() - self.start_time
        rate = self.processed / elapsed
        remaining = self.total - self.processed - self.failed
        if rate > 0 and remaining > 0:
            eta_seconds = remaining / rate
            return str(timedelta(seconds=int(eta_seconds)))
        return None

    def progress_percent(self) -> float:
        """Return progress as percentage."""
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100

    def should_report(self, interval_seconds: float = 10.0) -> bool:
        """Check if it's time to report progress."""
        now = time.time()
        if now - self.last_report >= interval_seconds:
            self.last_report = now
            return True
        return False

    def report(self, prefix: str = "") -> str:
        """Generate progress report string."""
        pct = self.progress_percent()
        eta_str = self.eta()
        elapsed = str(timedelta(seconds=int(time.time() - self.start_time)))
        rate = self.processed / (time.time() - self.start_time) if self.processed > 0 else 0

        report = (
            f"{prefix}Progress: {self.processed}/{self.total} ({pct:.1f}%) | "
            f"Elapsed: {elapsed} | "
            f"Rate: {rate:.1f} items/s"
        )
        if eta_str:
            report += f" | ETA: {eta_str}"
        if self.failed > 0:
            report += f" | Failed: {self.failed}"
        return report


# ---------------------------------------------------------------------------
# Batch processing with memory efficiency
# ---------------------------------------------------------------------------

def batch_generator(
    items: List[Any],
    batch_size: int = 64,
    max_batches_before_gc: int = 100,
) -> Generator[List[Any], None, None]:
    """
    Generate batches from a list with optional GC hints.

    Yields batches of size batch_size. After max_batches_before_gc batches,
    yields None to signal a good time for garbage collection.
    """
    batch = []
    batch_count = 0

    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
            batch_count += 1
            if batch_count >= max_batches_before_gc:
                batch_count = 0
                yield []  # Signal for GC

    if batch:
        yield batch


# ---------------------------------------------------------------------------
# Retry logic with exponential backoff
# ---------------------------------------------------------------------------

def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    exceptions: Tuple = (Exception,),
) -> Any:
    """
    Execute a function with exponential backoff retry logic.

    Args:
        func: Function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        exceptions: Tuple of exception types to catch

    Returns:
        Result of func if successful

    Raises:
        Last exception if all retries fail
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt == max_retries:
                break

            delay = min(base_delay * (exponential_base ** attempt), max_delay)
            # Add jitter (±10%)
            jitter = delay * 0.1 * (0.5 - os.urandom(1)[0] / 255)
            delay_with_jitter = delay + jitter

            log.warning(
                f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                f"Retrying in {delay_with_jitter:.1f}s..."
            )
            time.sleep(delay_with_jitter)

    raise last_exception


# ---------------------------------------------------------------------------
# Memory monitoring
# ---------------------------------------------------------------------------

def get_memory_usage_mb() -> float:
    """Get current memory usage in MB."""
    try:
        import resource
        # Returns memory usage in KB on Linux/macOS
        usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On macOS, ru_maxrss is in bytes; on Linux, it's in KB
        if sys.platform == "darwin":
            return usage_kb / (1024 * 1024)
        else:
            return usage_kb / 1024
    except Exception:
        return 0.0


def check_memory_threshold(threshold_mb: float = 1024.0) -> bool:
    """
    Check if memory usage exceeds threshold.

    Returns True if memory usage is above threshold.
    """
    usage = get_memory_usage_mb()
    if usage > threshold_mb:
        log.warning(f"Memory usage high: {usage:.1f} MB (threshold: {threshold_mb:.1f} MB)")
        return True
    return False


# ---------------------------------------------------------------------------
# Chunk ID validation
# ---------------------------------------------------------------------------

def validate_chunk_id(chunk_id: str) -> bool:
    """Validate that a chunk_id is a valid hex string."""
    if not chunk_id or not isinstance(chunk_id, str):
        return False
    try:
        int(chunk_id, 16)
        return len(chunk_id) >= 8  # At least 8 hex chars
    except ValueError:
        return False


def generate_chunk_id(text: str, metadata: dict) -> str:
    """Generate a deterministic chunk ID from text and metadata."""
    content = f"{text}|{json.dumps(metadata, sort_keys=True)}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def setup_ingestion_logging(
    log_file: Optional[str] = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """
    Configure logging for ingestion scripts.

    Args:
        log_file: Optional path to log file
        level: Logging level

    Returns:
        Configured logger
    """
    logger = logging.getLogger("ingest")
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(console_formatter)
        logger.addHandler(file_handler)

    return logger


def log_error_details(error: Exception, context: dict = None) -> None:
    """Log detailed error information."""
    log.error(f"Error: {error}")
    log.error(f"Type: {type(error).__name__}")
    log.error(f"Traceback:\n{traceback.format_exc()}")
    if context:
        log.error(f"Context: {json.dumps(context, indent=2)}")


# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------

def validate_chunk_data(chunk: Any) -> Tuple[bool, List[str]]:
    """
    Validate a chunk before ingestion.

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors = []

    # Check required fields
    if not hasattr(chunk, 'text') or not chunk.text:
        errors.append("Missing or empty 'text' field")

    if not hasattr(chunk, 'chunk_id') or not chunk.chunk_id:
        errors.append("Missing or empty 'chunk_id' field")

    if not hasattr(chunk, 'chunk_type') or not chunk.chunk_type:
        errors.append("Missing or empty 'chunk_type' field")

    # Validate text length
    if hasattr(chunk, 'text') and chunk.text:
        if len(chunk.text) > 100000:  # 100KB limit
            errors.append(f"Text too long: {len(chunk.text)} chars")

    # Validate chunk_id format
    if hasattr(chunk, 'chunk_id') and chunk.chunk_id:
        if not validate_chunk_id(chunk.chunk_id):
            errors.append(f"Invalid chunk_id format: {chunk.chunk_id}")

    return (len(errors) == 0, errors)


def validate_embedding(vector: List[float], expected_dim: int) -> Tuple[bool, str]:
    """
    Validate an embedding vector.

    Returns:
        Tuple of (is_valid, error message)
    """
    if not vector:
        return (False, "Empty vector")

    if len(vector) != expected_dim:
        return (False, f"Dimension mismatch: expected {expected_dim}, got {len(vector)}")

    # Check for NaN or Inf
    import math
    for i, val in enumerate(vector):
        if math.isnan(val) or math.isinf(val):
            return (False, f"Invalid value at index {i}: {val}")

    return (True, "")
