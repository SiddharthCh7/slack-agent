"""
Configuration management for the code documentation system.

Loads and validates settings from sync_config.yaml with environment variable overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class CodebaseConfig:
    """Configuration for a single codebase to monitor."""
    name: str
    repo_url: str
    branch: str = "main"
    poll_interval: int = 300  # seconds
    collection_name: str = ""
    enabled: bool = True

    def __post_init__(self):
        if not self.collection_name:
            self.collection_name = f"codebase_{self.name}"


@dataclass
class ProcessingConfig:
    """Code parsing and chunking settings."""
    chunk_strategies: list[str] = field(default_factory=lambda: [
        "function_level", "class_level", "module_level"
    ])
    max_chunk_size: int = 1000
    overlap_tokens: int = 50
    supported_languages: list[str] = field(default_factory=lambda: [
        "python", "javascript", "typescript", "go", "rust", "java", "ruby"
    ])
    exclude_patterns: list[str] = field(default_factory=list)
    max_file_size_kb: int = 500  # Skip files larger than this (prevent memory issues)
    embedding_batch_size: int = 50  # Batch size for embedding generation


@dataclass
class CacheConfig:
    """SQLite cache settings."""
    type: str = "sqlite"
    path: str = "./cache/codeparse.db"
    vacuum_on_startup: bool = False
    max_cache_age_days: int = 30


@dataclass
class QdrantConfig:
    """Qdrant vector database settings."""
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    vector_size: int = 768
    distance: str = "COSINE"
    create_payload_indexes: bool = True
    indexed_fields: list[str] = field(default_factory=lambda: [
        "file_path", "commit_hash", "language", "chunk_type", "repo_url"
    ])

    @property
    def rest_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def grpc_url(self) -> str:
        return f"{self.host}:{self.grpc_port}"


@dataclass
class SchedulerConfig:
    """Background scheduler settings."""
    enabled: bool = True
    max_workers: int = 4
    reload_config_on_change: bool = True
    config_check_interval: int = 60


@dataclass
class SyncConfig:
    """Sync retry and resumable settings."""
    max_retries: int = 3
    retry_wait_seconds: int = 60
    rate_limit_wait_seconds: int = 60
    max_workers: int = 4
    pause_on_rate_limit: bool = True


@dataclass
class LoggingConfig:
    """Logging settings."""
    level: str = "INFO"
    file: str = "./logs/codeparse.log"
    max_size_mb: int = 50
    backup_count: int = 5
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class Config:
    """
    Main configuration container.

    Loads from sync_config.yaml with optional environment variable overrides.
    """
    codebases: list[CodebaseConfig] = field(default_factory=list)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Config":
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to sync_config.yaml. If None, uses default locations.
        
        Returns:
            Config instance with loaded settings.
        """
        if config_path is None:
            # Try default locations
            candidates = [
                Path("sync_config.yaml"),
                Path(__file__).parent.parent.parent / "sync_config.yaml",
                Path("/etc/codeparse/sync_config.yaml"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    config_path = candidate
                    break
            else:
                raise FileNotFoundError(
                    "Config file not found. Tried: " + ", ".join(str(c) for c in candidates)
                )
        
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        logger.info(f"Loading config from {config_path}")
        
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary."""
        config = cls()

        # Parse codebases
        if "codebases" in data:
            config.codebases = [
                CodebaseConfig(**cb) for cb in data["codebases"]
            ]

        # Parse processing settings
        if "processing" in data:
            proc = data["processing"]
            config.processing = ProcessingConfig(
                chunk_strategies=proc.get("chunk_strategies", config.processing.chunk_strategies),
                max_chunk_size=proc.get("max_chunk_size", config.processing.max_chunk_size),
                overlap_tokens=proc.get("overlap_tokens", config.processing.overlap_tokens),
                supported_languages=proc.get("supported_languages", config.processing.supported_languages),
                exclude_patterns=proc.get("exclude_patterns", config.processing.exclude_patterns),
                max_file_size_kb=proc.get("max_file_size_kb", config.processing.max_file_size_kb),
                embedding_batch_size=proc.get("embedding_batch_size", config.processing.embedding_batch_size),
            )

        # Parse cache settings
        if "cache" in data:
            cache = data["cache"]
            config.cache = CacheConfig(
                type=cache.get("type", config.cache.type),
                path=cache.get("path", config.cache.path),
                vacuum_on_startup=cache.get("vacuum_on_startup", config.cache.vacuum_on_startup),
                max_cache_age_days=cache.get("max_cache_age_days", config.cache.max_cache_age_days),
            )

        # Parse Qdrant settings
        if "qdrant" in data:
            qd = data["qdrant"]
            config.qdrant = QdrantConfig(
                host=qd.get("host", config.qdrant.host),
                port=qd.get("port", config.qdrant.port),
                grpc_port=qd.get("grpc_port", config.qdrant.grpc_port),
                vector_size=qd.get("vector_size", config.qdrant.vector_size),
                distance=qd.get("distance", config.qdrant.distance),
                create_payload_indexes=qd.get("create_payload_indexes", config.qdrant.create_payload_indexes),
                indexed_fields=qd.get("indexed_fields", config.qdrant.indexed_fields),
            )

        # Parse scheduler settings
        if "scheduler" in data:
            sched = data["scheduler"]
            config.scheduler = SchedulerConfig(
                enabled=sched.get("enabled", config.scheduler.enabled),
                max_workers=sched.get("max_workers", config.scheduler.max_workers),
                reload_config_on_change=sched.get("reload_config_on_change", config.scheduler.reload_config_on_change),
                config_check_interval=sched.get("config_check_interval", config.scheduler.config_check_interval),
            )

        # Parse sync retry settings
        if "sync" in data:
            sync_cfg = data["sync"]
            config.sync = SyncConfig(
                max_retries=sync_cfg.get("max_retries", config.sync.max_retries),
                retry_wait_seconds=sync_cfg.get("retry_wait_seconds", config.sync.retry_wait_seconds),
                rate_limit_wait_seconds=sync_cfg.get("rate_limit_wait_seconds", config.sync.rate_limit_wait_seconds),
                max_workers=sync_cfg.get("max_workers", config.sync.max_workers),
                pause_on_rate_limit=sync_cfg.get("pause_on_rate_limit", config.sync.pause_on_rate_limit),
            )

        # Parse logging settings
        if "logging" in data:
            log_cfg = data["logging"]
            config.logging = LoggingConfig(
                level=log_cfg.get("level", config.logging.level),
                file=log_cfg.get("file", config.logging.file),
                max_size_mb=log_cfg.get("max_size_mb", config.logging.max_size_mb),
                backup_count=log_cfg.get("backup_count", config.logging.backup_count),
                format=log_cfg.get("format", config.logging.format),
            )

        # Apply environment variable overrides
        config._apply_env_overrides()

        return config

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        # Qdrant overrides
        if os.getenv("QDRANT_HOST"):
            self.qdrant.host = os.getenv("QDRANT_HOST")
        if os.getenv("QDRANT_PORT"):
            self.qdrant.port = int(os.getenv("QDRANT_PORT"))
        
        # Cache path override
        if os.getenv("CODEPARSE_CACHE_PATH"):
            self.cache.path = os.getenv("CODEPARSE_CACHE_PATH")

    def get_enabled_codebases(self) -> list[CodebaseConfig]:
        """Return only enabled codebases."""
        return [cb for cb in self.codebases if cb.enabled]

    def get_codebase_by_name(self, name: str) -> CodebaseConfig | None:
        """Get a specific codebase configuration by name."""
        for cb in self.codebases:
            if cb.name == name:
                return cb
        return None

    def validate(self) -> list[str]:
        """
        Validate configuration and return list of errors.
        Empty list means configuration is valid.
        """
        errors = []

        # Validate codebases
        if not self.codebases:
            errors.append("No codebases configured")
        
        seen_names = set()
        for cb in self.codebases:
            if cb.name in seen_names:
                errors.append(f"Duplicate codebase name: {cb.name}")
            seen_names.add(cb.name)
            
            if not cb.repo_url:
                errors.append(f"Codebase '{cb.name}' missing repo_url")
            if not cb.collection_name:
                errors.append(f"Codebase '{cb.name}' missing collection_name")

        # Validate processing settings
        if self.processing.max_chunk_size < 100:
            errors.append("max_chunk_size must be at least 100")
        if self.processing.overlap_tokens < 0:
            errors.append("overlap_tokens cannot be negative")

        # Validate Qdrant settings
        if self.qdrant.vector_size < 1:
            errors.append("qdrant.vector_size must be positive")

        return errors
