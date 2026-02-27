"""
Logging and error handling utilities for the code documentation system.

Provides:
- Structured logging with rotation
- Custom exception classes
- Retry decorators with exponential backoff
- Performance timing context managers
- Pretty console output with colors
"""

from __future__ import annotations

import functools
import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from loguru import logger


# =============================================================================
# Logging Setup
# =============================================================================

# Custom format for pretty console output
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>{module}</magenta>:<cyan>{function}</cyan> | "
    "<level>{message}</level>"
)

# Detailed format for file logs
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} | "
    "{message}"
)

# Simple format for verbose mode
VERBOSE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)


def setup_logging(
    level: str = "INFO",
    log_file: str = "./logs/codeparse.log",
    max_size_mb: int = 50,
    backup_count: int = 5,
    log_format: Optional[str] = None,
    verbose: bool = False,
) -> None:
    """
    Configure logging for the code documentation system.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to log file.
        max_size_mb: Maximum log file size before rotation.
        backup_count: Number of backup log files to keep.
        log_format: Custom log format string.
        verbose: If True, use simplified verbose format.
    """
    # Remove default handler
    logger.remove()

    # Choose format
    if log_format is None:
        log_format = VERBOSE_FORMAT if verbose else CONSOLE_FORMAT

    # Console handler with color
    logger.add(
        sys.stderr,
        format=log_format,
        level=level,
        colorize=True,
    )

    # File handler with rotation
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_path),
        format=FILE_FORMAT,
        level="DEBUG",  # Always log everything to file
        rotation=f"{max_size_mb} MB",
        retention=backup_count,
        compression="zip",
        enqueue=True,  # Thread-safe
    )

    logger.info(f"Logging configured: level={level}, file={log_file}")


def setup_detailed_logging(
    level: str = "DEBUG",
    log_file: str = "./logs/codeparse.log",
    show_module: bool = True,
    show_colors: bool = True,
) -> None:
    """
    Configure detailed logging with module names and enhanced formatting.

    Args:
        level: Logging level.
        log_file: Path to log file.
        show_module: If True, show module:function in logs.
        show_colors: If True, enable colored output.
    """
    logger.remove()

    # Console format
    if show_module:
        console_fmt = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<blue>{module}</blue>:<cyan>{function}</cyan> | "
            "<level>{message}</level>"
        )
    else:
        console_fmt = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        )

    logger.add(
        sys.stderr,
        format=console_fmt,
        level=level,
        colorize=show_colors,
    )

    # File handler
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_path),
        format=FILE_FORMAT,
        level="DEBUG",
        rotation="50 MB",
        retention=5,
        compression="zip",
        enqueue=True,
    )

    logger.info("Detailed logging initialized")


# =============================================================================
# Custom Exceptions
# =============================================================================

class CodeParseError(Exception):
    """Base exception for code parsing errors."""
    pass


class GitHubAPIError(CodeParseError):
    """Error interacting with GitHub API."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class ParseError(CodeParseError):
    """Error parsing code with tree-sitter."""
    def __init__(self, message: str, file_path: Optional[str] = None):
        super().__init__(message)
        self.file_path = file_path


class QdrantError(CodeParseError):
    """Error interacting with Qdrant."""
    def __init__(self, message: str, operation: Optional[str] = None):
        super().__init__(message)
        self.operation = operation


class CacheError(CodeParseError):
    """Error with SQLite cache operations."""
    pass


class EmbeddingError(CodeParseError):
    """Error generating embeddings."""
    pass


class SyncError(CodeParseError):
    """Error during sync operation."""
    def __init__(self, message: str, codebase: Optional[str] = None):
        super().__init__(message)
        self.codebase = codebase


class ConfigError(CodeParseError):
    """Error with configuration."""
    pass


# =============================================================================
# Retry Decorator
# =============================================================================

T = TypeVar('T')


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential: bool = True,
    exceptions: tuple = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for retrying failed operations with exponential backoff.
    
    Args:
        max_attempts: Maximum number of retry attempts.
        base_delay: Initial delay between retries (seconds).
        max_delay: Maximum delay between retries (seconds).
        exponential: If True, use exponential backoff; otherwise, constant delay.
        exceptions: Tuple of exception types to catch and retry.
    
    Returns:
        Decorated function.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_attempts - 1:
                        # Last attempt, re-raise
                        raise
                    
                    # Calculate delay
                    if exponential:
                        import random
                        delay = base_delay * (2 ** attempt)
                        delay = delay * (0.5 + random.random())  # Add jitter
                        delay = min(delay, max_delay)
                    else:
                        delay = base_delay
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.2f}s"
                    )
                    time.sleep(delay)
            
            # Should not reach here, but just in case
            raise last_exception
        
        return wrapper
    return decorator


# =============================================================================
# Performance Timing
# =============================================================================

@contextmanager
def timed_operation(operation_name: str, log_level: str = "info"):
    """
    Context manager for timing operations.
    
    Args:
        operation_name: Name of the operation for logging.
        log_level: Log level for the timing message.
    
    Yields:
        None
    
    Example:
        with timed_operation("Processing file"):
            process_file(path)
    """
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start_time
        
        log_func = getattr(logger, log_level)
        log_func(f"{operation_name} completed in {elapsed:.3f}s")


class Timer:
    """Simple timer for measuring elapsed time."""
    
    def __init__(self, name: str = "Timer"):
        self.name = name
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.elapsed: float = 0.0
    
    def start(self) -> "Timer":
        """Start the timer."""
        self.start_time = time.perf_counter()
        self.end_time = None
        self.elapsed = 0.0
        return self
    
    def stop(self) -> float:
        """Stop the timer and return elapsed time."""
        if self.start_time is None:
            raise RuntimeError("Timer not started")
        
        self.end_time = time.perf_counter()
        self.elapsed = self.end_time - self.start_time
        return self.elapsed
    
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        if self.end_time:
            return self.elapsed * 1000
        elif self.start_time:
            return (time.perf_counter() - self.start_time) * 1000
        return 0.0
    
    def __enter__(self) -> "Timer":
        return self.start()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


# =============================================================================
# Batch Processing Utilities
# =============================================================================

@dataclass
class BatchStats:
    """Statistics for batch processing."""
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    batches_completed: int = 0
    total_duration: float = 0.0
    
    @property
    def success_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100
    
    @property
    def avg_items_per_second(self) -> float:
        if self.total_duration == 0:
            return 0.0
        return self.processed_items / self.total_duration


def process_in_batches(
    items: list[Any],
    batch_size: int,
    process_fn: Callable[[list[Any]], Any],
    on_error: Optional[Callable[[Exception, Any], None]] = None,
) -> BatchStats:
    """
    Process items in batches with error handling and statistics.
    
    Args:
        items: List of items to process.
        batch_size: Number of items per batch.
        process_fn: Function to process each batch.
        on_error: Optional callback for handling individual item errors.
    
    Returns:
        BatchStats with processing statistics.
    """
    stats = BatchStats(total_items=len(items))
    start_time = time.perf_counter()
    
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        batch_start = time.perf_counter()
        
        try:
            process_fn(batch)
            stats.processed_items += len(batch)
            stats.batches_completed += 1
            
        except Exception as e:
            logger.error(f"Batch {stats.batches_completed + 1} failed: {e}")
            stats.failed_items += len(batch)
            
            if on_error:
                for item in batch:
                    try:
                        on_error(e, item)
                    except Exception:
                        pass
        
        batch_duration = time.perf_counter() - batch_start
        logger.debug(
            f"Batch {stats.batches_completed}: {len(batch)} items in {batch_duration:.3f}s"
        )
    
    stats.total_duration = time.perf_counter() - start_time
    
    logger.info(
        f"Batch processing complete: "
        f"{stats.processed_items}/{stats.total_items} items, "
        f"{stats.success_rate:.1f}% success rate, "
        f"{stats.avg_items_per_second:.1f} items/sec"
    )
    
    return stats


# =============================================================================
# Health Check Utilities
# =============================================================================

@dataclass
class HealthStatus:
    """Health check status."""
    healthy: bool
    component: str
    message: str = ""
    details: dict[str, Any] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


def check_qdrant_health(host: str, port: int) -> HealthStatus:
    """Check Qdrant health."""
    try:
        import httpx
        response = httpx.get(f"http://{host}:{port}/readyz", timeout=5.0)
        response.raise_for_status()
        return HealthStatus(
            healthy=True,
            component="qdrant",
            message="Qdrant is ready",
        )
    except Exception as e:
        return HealthStatus(
            healthy=False,
            component="qdrant",
            message=str(e),
        )


def check_github_connectivity() -> HealthStatus:
    """Check GitHub API connectivity."""
    try:
        import httpx
        response = httpx.get("https://api.github.com", timeout=5.0)
        response.raise_for_status()
        return HealthStatus(
            healthy=True,
            component="github",
            message="GitHub API is reachable",
        )
    except Exception as e:
        return HealthStatus(
            healthy=False,
            component="github",
            message=str(e),
        )


def check_cache_health(cache_path: str) -> HealthStatus:
    """Check SQLite cache health."""
    try:
        import sqlite3
        conn = sqlite3.connect(cache_path)
        conn.execute("SELECT 1")
        conn.close()
        return HealthStatus(
            healthy=True,
            component="cache",
            message="Cache database is accessible",
        )
    except Exception as e:
        return HealthStatus(
            healthy=False,
            component="cache",
            message=str(e),
        )
