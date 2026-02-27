"""
Background scheduler for code documentation sync.

Uses APScheduler to run periodic sync jobs for each configured codebase.
Supports hot-reload of configuration without restart.

Features:
- Periodic polling of GitHub repositories
- Configurable intervals per codebase
- Hot-reload when sync_config.yaml changes
- Graceful shutdown
- Job status tracking
"""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from .config import Config, CodebaseConfig
from .sync import CodeSyncEngine, SyncResult


@dataclass
class JobStatus:
    """Status of a scheduled sync job."""
    codebase_name: str
    last_run: Optional[datetime] = None
    last_result: Optional[SyncResult] = None
    next_run: Optional[datetime] = None
    error_count: int = 0
    is_running: bool = False


class CodeparseScheduler:
    """
    Background scheduler for code documentation sync.
    
    Manages periodic sync jobs for all configured codebases with
    support for configuration hot-reload.
    """

    def __init__(
        self,
        config: Config,
        embed_fn: Callable,
        config_path: Optional[str | Path] = None,
    ):
        """
        Initialize scheduler.
        
        Args:
            config: Configuration object.
            embed_fn: Embedding function for code chunks.
            config_path: Path to config file for hot-reload monitoring.
        """
        self.config = config
        self.embed_fn = embed_fn
        self.config_path = Path(config_path) if config_path else None
        
        self._scheduler = BackgroundScheduler(
            timezone="UTC",
            job_defaults={
                "max_instances": 1,  # Only one sync per codebase at a time
                "misfire_grace_time": 60,  # Allow 60s grace for missed runs
            },
        )
        
        self._sync_engine: Optional[CodeSyncEngine] = None
        self._job_statuses: dict[str, JobStatus] = {}
        self._config_mtime: Optional[float] = None
        self._config_lock = threading.Lock()
        self._running = False
        self._config_monitor_thread: Optional[threading.Thread] = None
        
        # Initialize job statuses
        for codebase in self.config.get_enabled_codebases():
            self._job_statuses[codebase.name] = JobStatus(codebase_name=codebase.name)
        
        logger.info("CodeparseScheduler initialized")

    def start(self) -> None:
        """Start the scheduler and all sync jobs."""
        if self._running:
            logger.warning("Scheduler already running")
            return
        
        logger.info("Starting scheduler")
        
        # Initialize sync engine
        self._sync_engine = CodeSyncEngine(self.config, self.embed_fn)
        
        # Schedule jobs for all enabled codebases
        for codebase in self.config.get_enabled_codebases():
            self._schedule_codebase(codebase)
        
        # Start scheduler
        self._scheduler.start()
        
        # Start config monitoring if enabled
        if self.config.scheduler.reload_config_on_change and self.config_path:
            self._start_config_monitor()
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        self._running = True
        logger.info(f"Scheduler started with {len(self._job_statuses)} jobs")

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self._running:
            return
        
        logger.info("Stopping scheduler")
        
        self._running = False
        
        # Stop config monitor
        if self._config_monitor_thread:
            self._config_monitor_thread.join(timeout=5)
        
        # Shutdown scheduler
        self._scheduler.shutdown(wait=True)
        
        # Close sync engine
        if self._sync_engine:
            self._sync_engine.close()
        
        logger.info("Scheduler stopped")

    def wait(self) -> None:
        """Block until scheduler is stopped."""
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def get_job_statuses(self) -> dict[str, dict[str, Any]]:
        """
        Get status of all scheduled jobs.
        
        Returns:
            Dict mapping codebase name to status info.
        """
        statuses = {}
        
        for name, status in self._job_statuses.items():
            job = self._scheduler.get_job(name)
            
            statuses[name] = {
                "codebase_name": name,
                "is_scheduled": job is not None,
                "next_run": str(status.next_run) if status.next_run else None,
                "last_run": str(status.last_run) if status.last_run else None,
                "last_success": status.last_result.success if status.last_result else None,
                "error_count": status.error_count,
                "is_running": status.is_running,
            }
        
        return statuses

    def trigger_sync(self, codebase_name: str) -> Optional[SyncResult]:
        """
        Manually trigger sync for a codebase.
        
        Args:
            codebase_name: Name of the codebase to sync.
        
        Returns:
            SyncResult or None if codebase not found.
        """
        codebase = self.config.get_codebase_by_name(codebase_name)
        if not codebase:
            logger.error(f"Codebase not found: {codebase_name}")
            return None
        
        logger.info(f"Manual sync triggered for {codebase_name}")
        return self._run_sync(codebase)

    def trigger_all_syncs(self) -> dict[str, SyncResult]:
        """
        Trigger sync for all enabled codebases.
        
        Returns:
            Dict mapping codebase name to SyncResult.
        """
        results = {}
        
        for codebase in self.config.get_enabled_codebases():
            result = self._run_sync(codebase)
            if result:
                results[codebase.name] = result
        
        return results

    def reload_config(self) -> bool:
        """
        Reload configuration and update scheduled jobs.
        
        Returns:
            True if config was reloaded successfully.
        """
        with self._config_lock:
            try:
                logger.info("Reloading configuration")
                
                new_config = Config.load(self.config_path)
                
                # Stop existing jobs
                for job in self._scheduler.get_jobs():
                    self._scheduler.remove_job(job.id)
                
                # Close old sync engine
                if self._sync_engine:
                    self._sync_engine.close()
                
                # Update config
                self.config = new_config
                self._sync_engine = CodeSyncEngine(self.config, self.embed_fn)
                
                # Reset job statuses
                self._job_statuses = {}
                for codebase in self.config.get_enabled_codebases():
                    self._job_statuses[codebase.name] = JobStatus(codebase_name=codebase.name)
                    self._schedule_codebase(codebase)
                
                logger.info("Configuration reloaded successfully")
                return True
                
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")
                return False

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _schedule_codebase(self, codebase: CodebaseConfig) -> None:
        """Schedule sync job for a codebase."""
        trigger = IntervalTrigger(seconds=codebase.poll_interval)
        
        self._scheduler.add_job(
            self._run_sync,
            trigger=trigger,
            id=codebase.name,
            name=f"Sync {codebase.name}",
            args=[codebase],
            replace_existing=True,
        )
        
        # Update next run time
        job = self._scheduler.get_job(codebase.name)
        if job and codebase.name in self._job_statuses:
            self._job_statuses[codebase.name].next_run = job.next_run_time
        
        logger.info(
            f"Scheduled sync for {codebase.name} "
            f"(interval: {codebase.poll_interval}s)"
        )

    def _run_sync(self, codebase: CodebaseConfig) -> Optional[SyncResult]:
        """
        Run sync for a codebase.
        
        Args:
            codebase: Codebase configuration.
        
        Returns:
            SyncResult or None on error.
        """
        if codebase.name not in self._job_statuses:
            self._job_statuses[codebase.name] = JobStatus(codebase_name=codebase.name)
        
        status = self._job_statuses[codebase.name]
        
        # Check if already running
        if status.is_running:
            logger.warning(f"Sync already running for {codebase.name}")
            return None
        
        status.is_running = True
        
        try:
            logger.info(f"Running sync for {codebase.name}")
            
            if not self._sync_engine:
                self._sync_engine = CodeSyncEngine(self.config, self.embed_fn)
            
            result = self._sync_engine.sync_codebase(codebase)
            
            status.last_run = datetime.now(timezone.utc)
            status.last_result = result
            status.is_running = False
            
            if result.success:
                logger.info(
                    f"Sync completed for {codebase.name}: "
                    f"{result.stats.files_changed} files, "
                    f"{result.stats.vectors_upserted} vectors"
                )
            else:
                status.error_count += 1
                logger.error(f"Sync failed for {codebase.name}: {result.message}")
            
            # Update next run time
            job = self._scheduler.get_job(codebase.name)
            if job:
                status.next_run = job.next_run_time
            
            return result
            
        except Exception as e:
            status.is_running = False
            status.error_count += 1
            logger.error(f"Sync error for {codebase.name}: {e}")
            return None

    def _start_config_monitor(self) -> None:
        """Start configuration file monitoring thread."""
        if not self.config_path or not self.config_path.exists():
            return
        
        self._config_mtime = self.config_path.stat().st_mtime
        
        self._config_monitor_thread = threading.Thread(
            target=self._monitor_config,
            daemon=True,
            name="config-monitor",
        )
        self._config_monitor_thread.start()
        
        logger.info(f"Config monitor started for {self.config_path}")

    def _monitor_config(self) -> None:
        """Monitor config file for changes."""
        while self._running:
            try:
                time.sleep(self.config.scheduler.config_check_interval)
                
                if not self.config_path or not self.config_path.exists():
                    continue
                
                current_mtime = self.config_path.stat().st_mtime
                
                if current_mtime != self._config_mtime:
                    logger.info("Config file changed, triggering reload")
                    self._config_mtime = current_mtime
                    self.reload_config()
                    
            except Exception as e:
                logger.debug(f"Config monitor error: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down")
            self.stop()
        
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)


def create_scheduler(
    config_path: Optional[str | Path] = None,
    embed_fn: Optional[Callable] = None,
) -> CodeparseScheduler:
    """
    Create and configure scheduler.
    
    Args:
        config_path: Path to sync_config.yaml.
        embed_fn: Embedding function (required for sync operations).
    
    Returns:
        Configured CodeparseScheduler instance.
    """
    # Load configuration
    config = Config.load(config_path)
    
    # Validate configuration
    errors = config.validate()
    if errors:
        for error in errors:
            logger.error(f"Config error: {error}")
        raise ValueError(f"Invalid configuration: {errors}")
    
    # Require embed_fn for actual sync operations
    if embed_fn is None:
        logger.warning("No embed_fn provided - scheduler will not be able to sync")
        # Provide a dummy embed function for testing
        embed_fn = lambda texts: [[0.0] * config.qdrant.vector_size for _ in texts]
    
    return CodeparseScheduler(
        config=config,
        embed_fn=embed_fn,
        config_path=config_path,
    )
