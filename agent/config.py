"""
Enhanced configuration for OLake Slack Community Agent.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Path to team definition file (relative to project root)
TEAM_FILE_PATH = Path(__file__).parent.parent / "olake-team.json"


class Config:
    """Configuration for Slack Community Agent."""
    
    # LLM Provider
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-4.6-sonnet")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    
    # Slack
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_APP_ID: str = os.getenv("SLACK_APP_ID", "")
    SLACK_CLIENT_ID: str = os.getenv("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET: str = os.getenv("SLACK_CLIENT_SECRET", "")
    
    # Agent Behavior
    MAX_REASONING_ITERATIONS: int = int(os.getenv("MAX_REASONING_ITERATIONS", "5"))
    _THRESHOLD_FOR_AUTO_REPLY: float = float(
        os.getenv("_THRESHOLD_FOR_AUTO_REPLY", "0.75")
    )
    ENABLE_DEEP_REASONING: bool = os.getenv("ENABLE_DEEP_REASONING", "true").lower() == "true"
    ENABLE_USER_LEARNING: bool = os.getenv("ENABLE_USER_LEARNING", "true").lower() == "true"
    MAX_CONTEXT_MESSAGES: int = int(os.getenv("MAX_CONTEXT_MESSAGES", "10"))

    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/slack_agent.db")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # Server
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "3000"))
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/slack/events")
    
    # Channel Configuration (Optional)
    IGNORED_CHANNELS: list = [
        c.strip() for c in os.getenv("IGNORED_CHANNELS", "").split(",") if c.strip()
    ]
    HIGH_PRIORITY_CHANNELS: list = [
        c.strip() for c in os.getenv("HIGH_PRIORITY_CHANNELS", "").split(",") if c.strip()
    ]

    # Team — olake-team.json for org-member detection and escalation prompt
    TEAM_FILE: Path = Path(__file__).parent.parent / "olake-team.json"

    # Terminal Tool
    TERMINAL_TOOL_ENABLED: bool = os.getenv("TERMINAL_TOOL_ENABLED", "false").lower() == "true"
    TERMINAL_TOOL_CONFIG: Path = Path(__file__).parent.parent / "terminal_allowed_commands.yaml"

    # LLM request timeout (prevents hanging when API is slow or unresponsive)
    LLM_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "90"))

    # Deep Research Agent
    MAX_RESEARCH_ITERATIONS: int = int(os.getenv("MAX_RESEARCH_ITERATIONS", "5"))
    MAX_CONTEXT_FILES: int = int(os.getenv("MAX_CONTEXT_FILES", "15"))
    MIN__TO_STOP: float = float(os.getenv("MIN__TO_STOP", "0.7"))
    RESEARCH_TIMEOUT_SECONDS: int = int(os.getenv("RESEARCH_TIMEOUT_SECONDS", "120"))

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration."""
        errors = []
        
        if not cls.SLACK_BOT_TOKEN:
            errors.append("SLACK_BOT_TOKEN is required")
        
        if not cls.SLACK_SIGNING_SECRET:
            errors.append("SLACK_SIGNING_SECRET is required")
        
        if cls.LLM_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required when using OpenAI")
        
        if cls.LLM_PROVIDER == "gemini" and not cls.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY is required when using Gemini")

        if cls.LLM_PROVIDER == "openrouter" and not cls.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY is required when using OpenRouter")

        if cls.LLM_PROVIDER == "ollama":
            # No API key required; ensure base URL is set (default: http://localhost:11434/v1)
            pass
        
        if errors:
            for error in errors:
                print(f"❌ Configuration Error: {error}")
            return False
        
        return True
    
    @classmethod
    def print_config(cls) -> None:
        """Print current configuration (sanitized)."""
        def mask_secret(value: str) -> str:
            if not value or len(value) < 8:
                return "***"
            return f"{value[:4]}...{value[-4:]}"
        
        print("\n📋 OLake Slack Agent Configuration")
        print("=" * 50)
        print(f"LLM Provider: {cls.LLM_PROVIDER}")
        print(f"Slack Bot Token: {mask_secret(cls.SLACK_BOT_TOKEN)}")
        print(f"Max Reasoning Iterations: {cls.MAX_REASONING_ITERATIONS}")
        print(f" Threshold: {cls._THRESHOLD_FOR_AUTO_REPLY}")
        print(f"Deep Reasoning Enabled: {cls.ENABLE_DEEP_REASONING}")
        print(f"User Learning Enabled: {cls.ENABLE_USER_LEARNING}")
        print(f"Database Path: {cls.DATABASE_PATH}")
        print(f"Webhook Port: {cls.WEBHOOK_PORT}")
        print(f"Log Level: {cls.LOG_LEVEL}")
        print(f"Max Context Files: {cls.MAX_CONTEXT_FILES}")
        print(f"Min  to Stop: {cls.MIN__TO_STOP}")
        print("=" * 50 + "\n")


# OLake Context (for LLM)
ABOUT_OLAKE = """
OLake: Comprehensive Technical Research Report
Open-Source Database Replication to Apache Iceberg
March 2026 | Based on olake.io & github.com/datazip-inc/olake

================================================================================
1. INTRODUCTION & OVERVIEW
================================================================================

OLake is an open-source, high-performance ELT (Extract, Load, Transform) engine built by Datazip, focused exclusively on one mission: replicating data from operational databases into open lakehouse table formats — primarily Apache Iceberg and plain Parquet — as fast and reliably as possible. The project is written entirely in Go (with a specialized Java component for Iceberg I/O), and is available at github.com/datazip-inc/olake.

Unlike generic ETL platforms such as Airbyte or Fivetran that attempt to cover hundreds of sources and destinations, OLake is deliberately narrow in scope. It does not try to be a universal connector hub. Instead, it is hyper-optimised for the specific, increasingly common use case of database-to-lakehouse replication — moving OLTP data into a queryable, engine-agnostic lakehouse so that analytics, ML, and BI workloads can run without touching production systems.

The tool was born from our experience building Datazip, a broader data analytics platform, where we kept hitting the same wall: existing ingestion solutions were too slow, too complex, or too expensive for the Iceberg-native path. OLake is our answer to that problem, now shared with the open-source community.

Key Claim: OLake delivers up to 7x faster bulk-load performance than Fivetran for PostgreSQL-to-Iceberg replication, and outpaces open-source alternatives like Airbyte and Debezium by 21x to over 600x in benchmark tests (NYC Taxi dataset, 4 billion rows, Azure infrastructure).

How OLake connects to sources: OLake connects directly to the upstream database (or log source). It reads the source's change stream (PostgreSQL WAL, MySQL binlog, MongoDB oplog, etc.) as a consumer or client. OLake does not sit behind middleware or act as a replica, primary, or broker in the source's topology; it is always a direct client to the database it is reading from. Source-side settings that apply to the database's own replication (e.g. replica commit order) apply to that component, not to OLake's connection.

================================================================================
2. SUPPORTED SOURCES & DESTINATIONS
================================================================================

2.1 Source Connectors

OLake currently supports the following source databases and streaming systems, each with distinct sync modes tailored to the engine's native change-capture mechanism.

PostgreSQL supports Full Refresh, Incremental, and CDC via pgoutput (WAL logical replication). It works with standard community Postgres, AWS RDS, Aurora, and Supabase. MySQL supports Full Refresh, Incremental, and CDC via Binlog (go-mysql library), including MySQL RDS and Aurora. MongoDB supports Full Refresh, Incremental, and CDC via the Oplog / Change Streams API, including sharded and replica-set clusters. Oracle supports Full Refresh and Incremental Sync via DBMS Parallel Execute, but CDC is not yet available. Apache Kafka supports consumer group-based streaming in append-only mode. MSSQL, DB2, and S3 are planned and currently in development.

2.2 Destination Connectors

On the destination side, OLake writes to two primary formats. Apache Iceberg is supported via multiple catalog integrations: AWS Glue, REST catalogs (Nessie, Polaris, Unity Catalog, Lakekeeper, S3 Tables), Hive Metastore, and JDBC Catalog. Plain Parquet is written directly to S3, GCS, MinIO, or local filesystem, which is useful for lightweight analytics without the Iceberg metadata layer.

OLake's Iceberg output is immediately queryable by any Iceberg v2-compatible engine, including AWS Athena, Trino, Spark, Flink, Presto, Hive, Snowflake, DuckDB, and Dremio. The use of open table formats eliminates vendor lock-in entirely.

================================================================================
3. ARCHITECTURE: A DEEP TECHNICAL DIVE
================================================================================

OLake follows a modular, plugin-based architecture with a clean separation of concerns across five primary layers: the Core Framework, the Protocol Layer, Drivers (Sources), Writers (Destinations), and the Type System. Understanding these layers is key to understanding why OLake can achieve its performance characteristics.

At a high level, every piece of data flowing through OLake passes through four stages: a Driver reads from the source database, the Core Framework orchestrates concurrency and state, a Writer pushes to the destination, and the Protocol Layer enforces the interfaces that keep all of this composable.

3.1 The Core Framework

The core framework is built with Cobra for CLI command management and exposes four primary commands: spec (returns a JSON Schema for a connector's config), check (validates a connection), discover (introspects the source schema), and sync (runs the actual data pipeline).

State Management tracks sync progress in a state.json file, enabling resumable snapshots and CDC cursor tracking. If a sync job crashes mid-flight, it can restart from exactly where it left off.

Configuration Management handles source credentials, destination configs, concurrency settings, and stream selections via JSON files (source.json, destination.json, streams.json).

Monitoring is provided by an embedded HTTP server that exposes live stats — concurrent process count, estimated finish time, live record counts, and throughput — which are also persisted to stats.json.

Concurrency Orchestration uses a context-based concurrency group (GlobalCxGroup) that controls the total number of concurrent database connections to prevent overwhelming the source.

3.2 The Protocol Layer

The Protocol Layer defines three critical Go interfaces that every source and destination must implement. These contracts are what make OLake's plugin architecture work.

The Connector interface is the base, requiring methods to return a config reference, a JSON spec, a connection check, and a type identifier. The Driver interface extends Connector with Setup, Discover, Read, and ChangeStreamSupported methods. The Writer interface extends Connector with Setup, Write, Normalization, EvolveSchema, and Close methods.

This strict interface contract means that adding a new database source or a new destination format requires no changes to the core — developers simply implement the appropriate interface and the rest of the system works automatically.

The full interfaces in Go are as follows:

  type Connector interface {
      GetConfigRef() Config
      Spec() any
      Check() error
      Type() string
  }

  type Driver interface {
      Connector
      Setup() error
      Discover(discoverSchema bool) ([]*types.Stream, error)
      Read(pool *WriterPool, stream Stream) error
      ChangeStreamSupported() bool
      SetupState(state *types.State)
  }

  type Writer interface {
      Connector
      Setup(stream Stream, opts *Options) error
      Write(ctx context.Context, record types.RawRecord) error
      Normalization() bool
      Flattener() FlattenFunction
      EvolveSchema(bool, bool, map[string]*types.Property, types.Record) error
      Close() error
  }

3.3 Drivers (Source Connectors)

PostgreSQL Driver

The PostgreSQL driver connects to the WAL (Write-Ahead Log) using the pglogrepl library and the native pgoutput protocol. A PostgreSQL publication defines which tables to watch. For CDC, the driver creates a logical replication slot and streams WAL messages, decoding each entry into an OLake RawRecord with an operation type (c = create/insert, u = update, d = delete) and a Unix millisecond timestamp.

For full refresh, PostgreSQL uses one of three chunking strategies depending on the table's structure. CTID-based chunking is used for tables without primary keys, leveraging PostgreSQL's physical row identifier. Primary key chunking is used for tables with integer PKs, creating evenly distributed key ranges. User-defined column chunking is used for tables with indexed non-standard columns.

MySQL Driver

MySQL CDC is handled via the go-mysql library, which reads binary log (binlog) events. The driver uses a single-reader, multi-writer architecture: one thread reads the binlog sequentially and routes change events to appropriate per-stream writer threads. MySQL's binlog includes full row images (INSERT, UPDATE, DELETE), and OLake maps these directly to Iceberg operations. For full refresh, MySQL uses auto-increment PK chunking, indexed column chunking, or partition-aware chunking that aligns with MySQL's native table partitions.

MongoDB Driver

MongoDB is a schema-less document store, which introduces unique challenges. For CDC, OLake uses MongoDB's Change Streams API (built on the oplog) with an aggregation pipeline filter for insert, update, and delete operations. The driver uses SetFullDocument(options.UpdateLookup) so that update events contain the complete document post-update, not just the diff.

For full refresh chunking, MongoDB uses three strategies. ObjectID-based chunking is used for collections with the default _id field, leveraging the timestamp embedded in ObjectIDs. The SplitVector strategy is used for sharded collections, invoking MongoDB's own splitVector command to find optimal chunk boundaries aligned with existing shard boundaries. Adaptive sampling is used for collections without obvious split keys, statistically sampling the collection to understand data distribution and create balanced chunks.

3.4 Writers (Destination Connectors)

The Go + Java Split Architecture

One of OLake's most architecturally interesting decisions is its hybrid Go/Java writer for Iceberg. Go is the language of the entire data plane — it is fast, has lightweight goroutines for concurrency, and a low memory footprint. However, Apache Iceberg's most mature, feature-complete implementation is the Java Iceberg library, with new features arriving in Java first. OLake solves this tension by using each language where it excels.

The Go side handles data ingestion from sources, concurrency management, schema detection, batching (10,000 records per batch), and serialization to Arrow/Parquet format. The Java side runs as a gRPC server and handles Iceberg table creation and schema registration, committing Parquet files to the Iceberg table format, and catalog interactions (Glue, REST, Hive, JDBC). Go sends compacted, typed payloads over gRPC to the Java server, which then performs the Iceberg-native operations. This architecture eliminated the need to maintain a parallel Iceberg implementation in Go while keeping the hot data path in Go.

Apache Arrow Integration

OLake recently migrated to Apache Arrow as its in-memory data format, achieving roughly 1.75x additional speedup over the previous Parquet-row-by-row approach. Arrow's columnar, in-memory format means data is already shaped the way Parquet expects it, eliminating the expensive row-to-column restructuring step. Arrow exposes raw buffer pointers, so the Parquet writer can read directly from Arrow's memory without allocation or copying. Arrow also processes full RecordBatches in a single call — 10,000 rows in microseconds — and benefits from SIMD operations and cache-locality optimizations.

Each thread gets its own rolling Arrow writer. OLake implements a fan-out strategy: each chunk of source data is distributed across multiple partition keys (derived from configured partition columns), and each partition key gets its own rolling writer. This means writes are always going to the correct partition without requiring a sort step.

Iceberg Delete Files for CDC

For CDC operations (updates and deletes), OLake writes Iceberg Equality Delete Files rather than modifying existing Parquet data files. An Equality Delete File is a special Parquet file that instructs query engines to logically mark rows as deleted by matching one or more column values. In OLake's case, an internal _olake_id field serves as the equality key. This approach is significantly faster than positional deletes (which require knowing the exact file and row position) and avoids the need for background merge jobs. The delete files are bounded at 64 MB each. OLake stores the Iceberg field-id in each Parquet file's metadata so query engines know which schema column is being referenced.

3.5 Parallel Chunking & Concurrency Model

Parallelized chunking is arguably OLake's single biggest performance lever. Rather than reading a table sequentially from row one to row N, OLake divides the table into logical chunks and processes all chunks simultaneously in a thread pool. The thread count is configurable via max_threads and can be set as high as your infrastructure allows.

OLake operates on three levels of concurrency. At the Global Level, the GlobalCxGroup is a context-based concurrency group that caps the total number of concurrent stream operations across all streams, preventing the source database from being overwhelmed. At the Stream Level, within each stream OLake creates a pool of worker threads equal to max_threads. Each thread is assigned one chunk and processes it independently, managed by the utils.Concurrent() utility. At the Writer Pool Level, each writer thread has its own in-memory buffer (channel). The buffer is non-blocking from the producer's perspective, with backpressure applied if the channel fills up. This means reading from the source is never blocked by writing to the destination — both operate as concurrent pipelines.

OLake also implements Adaptive Concurrency Control: a background goroutine monitors CPU, memory, and I/O utilization and dynamically adjusts the concurrency limit up or down based on whether the system is under high or low load.

Hybrid Sync Mode (Full Refresh + CDC)

A subtle but critical feature is OLake's handling of the transition from full refresh to CDC. When a sync starts for the first time, it must do a full snapshot first, then switch to CDC. During the full snapshot, changes are still happening in the source database. OLake handles this by starting CDC before the snapshot completes, buffering CDC events during the snapshot, and then applying them once the snapshot finishes. This guarantees no changes are missed during the transition window. If a new table is added after months of CDC running, OLake will do a fresh snapshot of just that table without interrupting the existing CDC streams for other tables.

3.6 State Management & Resumability

Every sync operation in OLake produces a state.json file that records the current position of each stream. For CDC streams, this is the database log cursor (WAL LSN for Postgres, binlog position for MySQL, resume token for MongoDB). For full refresh operations, the state tracks which chunks have been completed, so a crashed job can skip already-processed chunks and resume from the next pending one. This chunk-level resumability is particularly important for large tables where a full refresh could take hours — a failure at 95% completion does not restart from zero.

3.7 Schema Evolution

OLake automatically detects and adapts to schema changes in the source database. When a new column appears (whether discovered during snapshot or received via CDC), OLake uses a thread-safe schema evolution mechanism to update the destination Iceberg table's schema. The Go side maintains a local copy of the writer schema to avoid unnecessary locks during schema compatibility checks — only when a true schema change is detected does it acquire a lock, refresh the Java Iceberg writer, and proceed. A Dead Letter Queue (DLQ) mechanism ensures that schema changes do not break in-flight pipelines; problematic records are routed to a DLQ for inspection rather than crashing the pipeline.

================================================================================
4. PERFORMANCE BENCHMARKS & COMPARISONS
================================================================================

OLake's benchmarks are conducted on the NYC Taxi dataset (trips and fhv_trips tables), totalling approximately 4 billion rows. The test infrastructure uses an Azure Standard D64ls v5 VM (64 vCPUs, 128 GiB memory) for OLake/Debezium, and managed cloud offerings for Fivetran, Estuary, and Airbyte. The source database is an Azure Standard D32ads_v5 (32 vCores, 128 GiB, 51,200 max IOPS).

4.1 Full Load (Bulk Ingestion) Performance

OLake processed the full 4,008,587,913-row dataset and completed within 24 hours. Fivetran also completed the same dataset but was 7x slower than OLake. Airbyte crashed after 7.5 hours with only a partial load. Estuary completed a much smaller normalized dataset in 24 hours, implying far lower throughput. Debezium was 15.9x slower than OLake on equivalent full-load workloads.

The headline number is 235,000 records per second (RPS) for PostgreSQL full loads, which is what gives OLake its 15.9x advantage over Debezium.

4.2 CDC (Incremental) Performance

For a test set of 50 million PostgreSQL CDC changes, OLake completed the sync in 20.1 minutes — 53% faster than Fivetran and 10x to 70x faster than other open-source CDC tools. For MySQL CDC, OLake is 85.9% faster than Fivetran on equivalent workloads.

4.3 The 7x Iceberg Writer Refactor

OLake's destination pipeline has been significantly refactored from its original implementation. The original writer had multiple serialization/deserialization passes using JSON schemas, small and inconsistent Parquet file sizes from frequent buffer flushes, heavy processing on the Java JVM side for schema discovery and concurrency management, and a partition writer that closed and reopened files whenever a different partition key appeared in a batch.

The refactored writer introduced a single 10,000-record batch buffer per thread (reducing memory footprint and serialization overhead), commits only after finishing a full 4 GB chunk (compressing to approximately 350 MB, resulting in fewer, larger Parquet files ideal for query performance), concurrent partition writers (maintaining multiple active partition writers simultaneously rather than cycling through one at a time), and a Go-side schema cache to avoid unnecessary gRPC calls to the Java server for every schema check. The cumulative result is a 7x improvement in Iceberg write throughput.

================================================================================
5. DEPLOYMENT ARCHITECTURE
================================================================================

5.1 Kubernetes / Helm Deployment

For production workloads, OLake is designed to run on Kubernetes, deployed via a Helm chart. The Helm chart deploys six key services that work in concert.

The OLake UI is a web interface and REST API server for configuring sources, destinations, and jobs, and monitoring sync progress. The OLake Worker is a Kubernetes-native worker that listens for tasks from the orchestrator (Temporal) and dynamically creates Kubernetes pods to execute sync operations, schema discovery, and connection tests. Temporal is an open-source workflow orchestrator that manages the entire pipeline lifecycle — every sync job in OLake is a durable Temporal workflow, so if the job crashes, Temporal remembers exactly where it was and resumes from that point on the next schedule. PostgreSQL (as a Temporal backend) is used by Temporal to persist workflow state. An NFS Server provides a shared volume for passing configuration files between the UI and Worker pods. The Temporal UI provides full execution history visibility — every step, every retry, every decision point in a workflow is visible here.

A key design insight is that when a worker pod needs to execute a data operation, it does not run that operation inside the OLake Worker itself. Instead, it creates a dedicated, ephemeral Kubernetes pod for that specific task. This provides resource isolation (each sync job gets its own pod with its own resource limits), failure isolation (a crashed pod doesn't affect other syncs), and enables routing specific sync types to nodes with the right hardware.

5.2 Docker Compose / Local Quickstart

For development and smaller workloads, OLake provides a single Docker Compose file that launches the entire stack (UI, Worker, Temporal, Postgres, MinIO for local S3) with one command. The UI is accessible at localhost:8000. This is how most users first experience OLake — no Kubernetes cluster required to evaluate the tool.

5.3 Airflow Integration

OLake can also be orchestrated by Apache Airflow for teams already invested in that ecosystem. Airflow DAGs can invoke OLake's CLI commands (sync, discover, etc.) on a schedule. There are documented deployment patterns for both Airflow-on-EC2 and Airflow-on-Kubernetes configurations.

================================================================================
6. KNOWN LIMITATIONS & SCOPE BOUNDARIES
================================================================================

OLake is an ELT tool — it replicates raw data as-is. Transformations such as business logic, aggregations, and joins are expected to happen downstream using the query engine of choice (dbt + Spark/Trino, etc.).

Oracle support currently covers Full Refresh and Incremental Sync but not CDC via LogMiner. Full CDC for Oracle is on the roadmap.

Delta Lake and Apache Hudi are planned destinations but not currently supported — Iceberg is the primary format. The Java gRPC Iceberg writer is currently a single process, which could become a bottleneck at extreme scale, though the 10K-record batching and large-file commit strategy mitigates this significantly.

================================================================================
7. CODEBASE STRUCTURE & ENGINEERING OBSERVATIONS
================================================================================

The OLake codebase at github.com/datazip-inc/olake is organized around a clear directory structure. The drivers/ directory contains one subdirectory per source connector (postgres/, mysql/, mongodb/, oracle/, kafka/), each with a main.go entry point and an internal/ package for the connector logic. The writers/ directory holds destination implementations (iceberg/, parquet/). The protocol/ directory defines the core interfaces (Connector, Driver, Writer, WriterPool, ThreadEvent) and the sync orchestration logic. The types/ directory houses OLake's internal type system, schema representation, RawRecord, Chunk, and State definitions. The utils/ directory holds shared utilities including the concurrent execution primitives (Concurrent, ConcurrentInGroup, CGroupWithLimit). The waljs/ directory contains the PostgreSQL WAL parsing library wrapping pglogrepl.

Each driver is built as a separate binary (driver-postgres, driver-mysql, etc.) rather than a single monolithic binary. This keeps the executable size smaller since each binary only links the dependencies it needs.

The concurrency primitives in utils/ are worth noting. OLake uses Go's native goroutines and channels rather than any external concurrency library. The CGroupWithLimit type is a custom implementation of a bounded concurrency group backed by golang.org/x/sync/errgroup, extended with a semaphore for limiting simultaneous goroutines.

================================================================================
8. COMMUNITY & ECOSYSTEM
================================================================================

OLake is maintained by Datazip and has an active open-source community. The project accepts contributions via GitHub (github.com/datazip-inc/olake), has a Slack community for real-time support, and runs a community contributor program. The project has participated in Google Summer of Code (GSoC). Documentation is maintained separately at github.com/datazip-inc/olake-docs.

The project uses a standard open-source contribution model with issue templates for bug reports and doc errors, PR review guidelines, and a Code of Conduct. A dedicated testing framework is included for writing sync tests and connection checks across different database flavors.

================================================================================
Sources: olake.io/docs | olake.io/blog | github.com/datazip-inc/olake | olake.io/docs/benchmarks
================================================================================
"""

# Repo Info
ABOUT_OLAKE_REPO_INFO = """
Below are the repositories that make up OLake:

=== olake (Core Engine) ===
Language: Go
The central runtime that does all actual data movement. Contains:
- Source connectors/drivers: PostgreSQL (pgoutput CDC), MySQL (binlog CDC), MongoDB (oplog CDC),
  Oracle, MSSQL, DB2, Kafka, S3
- Destination writers: Apache Iceberg (REST/Glue/Hive catalogs), Parquet files
- Core sync logic: full load, incremental, and CDC (change data capture) modes
- Schema discovery, schema evolution handling, type mapping
- CLI entrypoint for running sync jobs (used directly or invoked by olake-ui's BFF)
- Internal libraries/interfaces shared across connectors (state management, record batching,
  checkpointing, parallelism)
- CI/CD pipelines, integration tests, Docker image builds (image consumed by olake-ui and olake-helm)

=== olake-ui (Frontend + BFF) ===
Languages: TypeScript (React frontend), Go (BFF/API backend)
The user-facing control plane for OLake. Contains:
- React frontend: dashboard for managing sources, destinations, jobs, sync runs, logs
- BFF (Backend for Frontend): REST API that stores job/source/destination configurations in
  PostgreSQL, triggers and monitors sync jobs via Temporal workflow engine
- Temporal worker code that invokes olake (core engine) Docker image to actually run syncs
- Docker Compose setup to run the full stack (UI + BFF + Temporal + PostgreSQL)
- Auth layer (user login, session management)
Connection to others: Directly orchestrates olake (core) by spawning its Docker container per
sync job. olake-helm deploys this service to Kubernetes. olake-docs documents how to set it up.

=== olake-docs (Documentation & Website) ===
Language: MDX/JavaScript (Docusaurus)
The public-facing website at olake.io. Contains:
- Full user documentation: quickstart guides, connector-specific setup (Postgres, MySQL, MongoDB,
  Iceberg, S3, etc.), configuration references, CLI flag references
- Architecture explanations, CDC concepts, benchmarks, performance comparisons
- Blog posts and announcements
- Changelog and migration guides
- No runtime code; purely static content
Connection to others: Documents all features of olake (core) and olake-ui. References olake-helm
for Kubernetes deployment instructions.

=== olake-helm (Kubernetes Deployment) ===
Language: YAML (Helm)
Kubernetes deployment manifests for the entire OLake stack. Contains:
- Helm chart(s) for deploying olake-ui (frontend + BFF), Temporal, PostgreSQL, and the sync
  worker infrastructure on a Kubernetes cluster
- values.yaml with configurable resource limits, replica counts, image tags, secrets
- Templates for Deployments, Services, Ingress, ConfigMaps, PersistentVolumeClaims
- Likely references the same Docker images built and published by olake and olake-ui repos
Connection to others: Packages and deploys olake-ui and the olake core worker image; the
Kubernetes-native alternative to the Docker Compose setup in olake-ui.

=== olake-fusion (Lakehouse Management Layer) ===
Language: Java
Base: Fork/customization of Apache Amoro (incubating)
A lakehouse management system built on open table formats (Iceberg, etc.). Contains:
- Table optimization services: compaction, expiry, orphan file cleanup for Iceberg tables
- Catalog management: unified interface over multiple Iceberg catalogs (REST, Hive, Glue, etc.)
- AMS (Amoro Management Service): web UI and API for monitoring and managing lakehouse tables
- Iceberg table health metrics, partitioning strategies, self-optimizing table features
Connection to others: Sits downstream of olake (core) — after olake writes data into Iceberg
tables, olake-fusion manages and optimizes those tables. It is the lakehouse governance/maintenance
layer that complements the ingestion done by the core engine.

=== Inter-repo Relationships Summary ===
olake (core) ← invoked by → olake-ui (BFF orchestrates core's Docker image per sync job)
olake (core) → writes Iceberg tables → olake-fusion (manages/optimizes those tables)
olake + olake-ui → packaged for K8s by → olake-helm
olake + olake-ui + olake-helm → documented in → olake-docs
"""


def load_olake_docs() -> str:
    """Load OLake documentation from files."""
    docs_path = Path(Config.DOCS_PATH)
    
    if not docs_path.exists():
        # Fallback to about_olake.md
        about_path = Path("docs/about_olake.md")
        if about_path.exists():
            return about_path.read_text()
        return ABOUT_OLAKE
    
    # If we have a knowledge base directory, load all markdown files
    all_docs = []
    for md_file in docs_path.rglob("*.md"):
        try:
            all_docs.append(f"\n\n# {md_file.stem}\n{md_file.read_text()}")
        except Exception:
            continue
    
    return "\n".join(all_docs) if all_docs else ABOUT_OLAKE


# Validate on import
if __name__ == "__main__":
    Config.print_config()
    if Config.validate():
        print("✅ Configuration is valid!")
    else:
        print("❌ Configuration has errors!")
