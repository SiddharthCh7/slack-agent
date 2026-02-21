**OLake**

Comprehensive Knowledge-Base Document

*Optimised for Hierarchical Chunking · Vector DB · RAG Agent Retrieval*

Source: olake.io/docs · GitHub: datazip-inc/olake · Generated: Feb 2026

+-----------------------------------------------------------------------+
| **HOW TO USE & MAINTAIN THIS DOCUMENT**                               |
|                                                                       |
| Each H1 section is a self-contained chunk with a METADATA TABLE at    |
| the top containing canonical URLs, tags, key entities, and sample     |
| questions. Apply hierarchical chunking at H1 → H2 → H3 boundaries.    |
| Store the metadata fields as chunk metadata in your vector DB         |
| alongside the embedding. When documentation changes: (1) locate the   |
| section by its DOC URL, (2) update content, (3) refresh LAST UPDATED. |
| New connector? Add an H2 under the appropriate source/destination H1  |
| following the existing pattern.                                       |
+-----------------------------------------------------------------------+

§1 Introduction to OLake

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/

  **SEE ALSO**  Architecture (blog):
                https://olake.io/blog/olake-architecture/\
                GitHub (core): https://github.com/datazip-inc/olake

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      overview · introduction · what-is-olake · architecture ·
                ELT · open-source

  **KEY         OLake, ELT, Apache Iceberg, Parquet, CDC, Golang, Datazip
  ENTITIES**    

  **ANSWERS     What is OLake?\
  QUESTIONS     What does OLake do?\
  LIKE**        Why should I use OLake instead of Debezium or Airbyte?\
                What language is OLake written in?\
                Is OLake open source?\
                Who makes OLake?

  **UPDATE      Update if core product description, license, or
  WHEN**        maintainer changes.
  ------------- ---------------------------------------------------------

1.1 What Is OLake?

OLake is a blazing-fast, open-source ELT (Extract-Load-Transform)
framework written entirely in Golang for memory efficiency and high
performance. It replicates data from transactional databases and event
streams directly into Apache Iceberg and Parquet --- enabling real-time
lakehouse analytics without ETL scripts or vendor lock-in.

-   GitHub (core engine): https://github.com/datazip-inc/olake

-   GitHub (UI): https://github.com/datazip-inc/olake-ui

-   Documentation: https://olake.io/docs/

-   Community Slack: https://olake.io/slack

-   Company: Datazip, Inc. --- 16192 Coastal Hwy, Lewes, DE 19958, USA

-   Contact: hello@olake.io

1.2 Core Value Proposition

-   Fastest lakehouse path: parallelised chunking, resumable snapshots,
    exactly-once delivery.

-   Efficient CDC: native database logs --- pgoutput (PostgreSQL),
    binlogs (MySQL), oplogs (MongoDB).

-   Schema-aware: auto-detects and handles column/table-level schema
    changes.

-   Open formats: Parquet + Iceberg --- engine-agnostic, no vendor
    lock-in.

-   Infrastructure-light: no Spark, Flink, Kafka, or Debezium required.

-   Self-serve UI: Docker Compose single-command deploy, first sync in
    minutes.

1.3 Architecture Overview

OLake has four main components:

  ---------------- --------------- ----------------------------------------
  **Component**    **Role**        **Details**

  Core Framework   Orchestrator    State management, config validation,
                                   logging, type detection, concurrency.
                                   Exposes CLI commands: spec, check,
                                   discover, sync.

  Drivers          Data readers    Pluggable connectors (PostgreSQL, MySQL,
  (Sources)                        MongoDB, Oracle, Kafka). Implement the
                                   Driver interface; handle source-specific
                                   chunking and CDC.

  Writers          Data writers    Write to Iceberg (Glue/REST/Hive/JDBC
  (Destinations)                   catalogs) or Parquet on S3 / GCS / MinIO
                                   / ADLS.

  Protocol / Type  Data contracts  Interfaces, abstractions, and data-type
  System                           conversions between source and
                                   destination schemas.
  ---------------- --------------- ----------------------------------------

**Data Flow:**

Source DB → Driver (reads via chunking/CDC) → Core (dedup, schema
evolution, state) → Writer (Parquet/Iceberg) → Object Storage
(S3/GCS/MinIO) + Catalog (Glue/REST/Hive/JDBC).

1.4 Key Terminology

  ------------- ------------------------------------------------------------
  **DOC URL**   https://olake.io/docs/understanding/terminologies/general/

  **SEE ALSO**  OLake terminologies:
                https://olake.io/docs/understanding/terminologies/olake/

  **TAGS**      terminology · glossary

  **KEY         Stream, CDC, Incremental, oplog, binlog, pgoutput, Iceberg,
  ENTITIES**    catalog, normalization, chunking, state, olake_id

  **ANSWERS     What is CDC in OLake?\
  QUESTIONS     What is an oplog?\
  LIKE**        What does normalization mean in OLake?\
                What is a stream?

  **UPDATE      Update when new core concepts or config fields are
  WHEN**        introduced.
  ------------- ------------------------------------------------------------

  ------------------- ---------------------------------------------------
  **Term**            **Definition**

  Stream              A table or collection in the source database being
                      replicated.

  Full Refresh        Complete load of all rows from the source on every
                      run.

  CDC (Change Data    Real-time capture of inserts, updates, deletes via
  Capture)            database logs.

  Incremental Sync    Captures only rows changed since the last sync
                      using a cursor column (e.g., updated_at).

  Oplog               MongoDB operation log used for CDC.

  Binlog              MySQL binary log used for CDC.

  Pgoutput            Native PostgreSQL logical replication plugin used
                      for CDC (PostgreSQL 10+).

  Iceberg             Open table format for large analytics datasets with
                      ACID transactions.

  Catalog             Metadata store for Iceberg tables (Glue, Hive,
                      REST, JDBC).

  Normalization       Flattening level-1 nested JSON fields into
                      top-level columns.

  Chunking            Splitting large tables into virtual segments for
                      parallel reading.

  State               Checkpoint file (state.json) recording sync
                      progress for resumability.

  OLAKE_DIRECTORY     Local directory holding source.json,
                      destination.json, streams.json, state.json.

  olake_id            Synthetic primary key added by OLake for
                      deduplication.

  olake_timestamp   Writer timestamp column; used as a pseudo-partition
                      column via now().

  Replication Slot    PostgreSQL WAL consumer slot that retains log data
                      until consumed.

  Publication         PostgreSQL object defining which tables are
                      replicated via pgoutput.

  WAL                 Write-Ahead Log --- PostgreSQL transaction log used
                      for logical replication.
  ------------------- ---------------------------------------------------

§2 Installation & Quickstart

  ------------- ----------------------------------------------------------------------
  **DOC URL**   https://olake.io/docs/install/olake-ui/

  **SEE ALSO**  Docker CLI install: https://olake.io/docs/install/docker-cli/\
                Kubernetes / Helm: https://olake.io/docs/install/kubernetes/\
                Playground (local demo):
                https://olake.io/docs/getting-started/playground/\
                Quickstart guide: https://olake.io/docs/getting-started/quickstart/\
                First pipeline guide:
                https://olake.io/docs/getting-started/creating-first-pipeline/\
                Offline install (AWS):
                https://olake.io/docs/install/olake-ui/offline-environments-aws/\
                Offline install (generic):
                https://olake.io/docs/install/olake-ui/offline-environments-generic/

  **LAST        Jan 2026
  UPDATED**     

  **TAGS**      install · docker · docker-compose · kubernetes · helm · quickstart ·
                setup

  **KEY         Docker Compose, OLake UI, Temporal, Elasticsearch, PostgreSQL, Helm,
  ENTITIES**    Kubernetes

  **ANSWERS     How do I install OLake?\
  QUESTIONS     How do I run OLake with Docker?\
  LIKE**        What is the default login for OLake UI?\
                What ports does OLake use?\
                How do I update OLake to the latest version?\
                What are the minimum system requirements for OLake?\
                How do I configure an external PostgreSQL for OLake?\
                How do I run OLake offline or in an air-gapped environment?

  **UPDATE      Update port numbers, default credentials, system requirements, and
  WHEN**        docker-compose.yml changes when new releases ship.
  ------------- ----------------------------------------------------------------------

2.1 Option A --- Docker Compose + OLake UI (Recommended)

2.1.1 Stack Components

  ------------------ ------------------------------------ ---------------
  **Service**        **Role**                             **Default
                                                          Port**

  OLake UI           Main web interface --- job           8000
                     management, source/destination       
                     config, monitoring                   

  Temporal Worker    Background worker that executes data ---
                     replication jobs                     

  PostgreSQL         Stores job data, connection configs, 5432 (internal)
                     and sync state                       

  Temporal Server    Workflow orchestration engine        7233 (internal)

  Temporal UI        Web UI for monitoring workflows and  8088 (internal)
                     debugging                            

  Elasticsearch      Search/index backend for Temporal    9200 (internal)
                     workflow history                     

  Signup Init        One-time service that creates the    ---
                     default admin user on first run      
  ------------------ ------------------------------------ ---------------

2.1.2 System Requirements

  ----------------------- ----------------------- -----------------------
  **Tier**                **CPU**                 **RAM**

  Minimum                 8 vCPU                  16 GB

  Recommended             16 vCPU                 32 GB
  ----------------------- ----------------------- -----------------------

2.1.3 One-Command Setup

> curl -sSL
> https://raw.githubusercontent.com/datazip-inc/olake-ui/master/docker-compose.yml
> \| docker compose -f - up -d

Access OLake UI at http://localhost:8000. Default credentials:
username=admin, password=password.

2.1.4 Upgrading to Latest Version

> curl -sSL
> https://raw.githubusercontent.com/datazip-inc/olake-ui/master/docker-compose.yml
> \| docker compose -f - down && \\
>
> curl -sSL
> https://raw.githubusercontent.com/datazip-inc/olake-ui/master/docker-compose.yml
> \| docker compose -f - up -d

*Note: Data and configurations persist in olake-data/ directory and
Docker volumes across upgrades.*

2.1.5 Key docker-compose.yml Configuration Options

**Admin credentials (set before first start):**

> x-signup-defaults:
>
> username: &defaultUsername \"your-username\"
>
> password: &defaultPassword \"your-secure-password\"
>
> email: &defaultEmail \"your-email@example.com\"

**Encryption key:**

  ------------------ ------------------------------------ ----------------------
  **Mode**           **Config Value**                     **Notes**

  Custom passphrase  key: \"your-passphrase\"             OLake generates
                                                          SHA-256 hash
                                                          internally.

  AWS KMS            key:                                 Recommended for
  (production)       \"arn:aws:kms:region:acct:key/ID\"   production.

  Disabled           key: \"\"                            Not recommended for
                                                          production.
  ------------------ ------------------------------------ ----------------------

**Custom data directory:**

> x-app-defaults:
>
> host_persistence_path: &hostPersistencePath /custom/path/olake-data

**External PostgreSQL (edit x-db-envs):**

> x-db-envs:
>
> DB_HOST: &DBHost your-postgres-host
>
> DB_PORT: &DBPort 5432
>
> DB_USER: &DBUser temporal
>
> DB_PASSWORD: &DBPassword temporal
>
> DB_SSLMODE: &DBSSLMode disable
>
> OLAKE_DB_NAME: &olakeDBName postgres
>
> TEMPORAL_DB_NAME: &temporalDBName temporal

For TLS connections to external PostgreSQL, uncomment SQL_TLS,
SQL_TLS_ENABLED, etc. under services.temporal.env in docker-compose.yml.

2.1.6 Data Persistence

  ------------------ ----------------------------- ------------------------------
  **Storage**        **Path / Name**               **Contains**

  Bind-mount         ./olake-data (or custom path) Streams configs, connection
  directory                                        settings, sync state. Persists
                                                   across container restarts.

  Docker volume      temporal-postgresql-data      PostgreSQL data: workflow
                                                   history, job metadata, sync
                                                   state.

  Docker volume      temporal-elasticsearch-data   Elasticsearch search index for
                                                   Temporal.
  ------------------ ----------------------------- ------------------------------

2.1.7 Log Retention

Runs daily at midnight via cron. Default: 30 days. Configure via
LOG_RETENTION_PERIOD env var on temporal-worker service.

> services:
>
> temporal-worker:
>
> environment:
>
> LOG_RETENTION_PERIOD: \"30\" \# days

2.1.8 Troubleshooting --- Docker Compose

  ------------------ --------------------- ------------------------------
  **Problem**        **Diagnosis**         **Fix**

  Port 8000 conflict lsof -i :8000         Stop conflicting service or
                                           change port in
                                           docker-compose.yml.

  DB connection      docker compose ps;    Check PostgreSQL container
  failing            docker compose logs   health.
                     postgresql            

  Out of memory      docker stats          Ensure Docker Desktop has ≥4
                                           GB RAM allocated.

  Permission denied  ls -la ./olake-data   Add user to docker group
                                           (Linux). Check directory
                                           permissions.

  Full reset (DATA   ---                   docker compose down -v &&
  LOSS)                                    docker compose up -d
  ------------------ --------------------- ------------------------------

2.2 Option B --- Docker CLI (Advanced / Automation)

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/install/docker-cli/

  **SEE ALSO**  CLI commands & flags:
                https://olake.io/docs/community/commands-and-flags/

  **TAGS**      docker-cli · automation · CI/CD · discover · sync

  **KEY         discover, sync, check, spec, streams.json, source.json,
  ENTITIES**    destination.json, state.json

  **ANSWERS     How do I run OLake from the command line?\
  QUESTIONS     How do I use the Docker CLI for OLake?\
  LIKE**        What is the discover command?\
                How do I run a sync with the CLI?\
                What flags does the sync command support?

  **UPDATE      Update when new CLI commands, flags, or Docker image
  WHEN**        names are added.
  ------------- ---------------------------------------------------------

Each source connector has a dedicated Docker image:
olakego/source-\[SOURCE-TYPE\]:latest (e.g.,
olakego/source-postgres:latest). For production, pin to a specific
version tag.

**Step 1 --- Discover (generates streams.json):**

> docker run \--pull=always \\
>
> -v \"\[PATH_TO_CONFIG_FOLDER\]:/mnt/config\" \\
>
> olakego/source-\[SOURCE-TYPE\]:latest \\
>
> discover \--config /mnt/config/source.json

**Step 2 --- Sync:**

> docker run \--pull=always \\
>
> -v \"\[PATH_TO_CONFIG_FOLDER\]:/mnt/config\" \\
>
> olakego/source-\[SOURCE-TYPE\]:latest \\
>
> sync \\
>
> \--config /mnt/config/source.json \\
>
> \--streams /mnt/config/streams.json \\
>
> \--destination /mnt/config/destination.json

*For CDC/Incremental, add: \--state /mnt/config/state.json*

**CLI Commands Reference:**

  ------------- ---------------------------------- --------------------------------
  **Command**   **Description**                    **Key Flags**

  spec          Returns JSON Schema + UI Schema    \--destination-type
                for connector config. Used by UI   iceberg\|parquet
                (RJSF) to render forms.            

  check         Validates connection to source or  \--config, \--destination
                destination.                       

  discover      Returns all available streams      \--config, \--no-save,
                (tables/collections) and their     \--streams (merge mode)
                schemas.                           

  sync          Executes replication: reads        \--config, \--streams,
                source, writes destination.        \--destination, \--state,
                                                   \--clear-destination,
                                                   \--destination-database-prefix

  help / -h     Lists all commands and flags for   ---
                current CLI version.               
  ------------- ---------------------------------- --------------------------------

**Important Flags:**

  -------------------------------- ----------------------------------------------
  **Flag**                         **Purpose**

  \--state PATH                    Path to state.json. Enables
                                   resumable/incremental/CDC syncs.

  \--clear-destination             Clears destination data for selected streams
                                   and resets state. Use before re-sync.

  \--destination-database-prefix X Adds prefix X to the destination database name
                                   (e.g., source db \"sales\" →
                                   \"X_mysql_sales\").

  \--encryption-key KEY            Decrypts encrypted config files using KEY
                                   (supports KMS ARN, UUID, or custom string).

  \--no-save                       Prevents writing of any generated files
                                   (useful in CI pipelines).

  \--streams PATH                  Merge mode for discover: preserves manual
                                   edits, adds newly detected tables.

  \--timeout SECONDS               Overrides default command timeout.
  -------------------------------- ----------------------------------------------

**Progress Monitoring via stats.json (created at sync start):**

Fields: Estimated Remaining Time, Memory, Running Threads, Seconds
Elapsed, Speed (rps), Synced Records.

2.3 Option C --- Kubernetes (Helm)

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/install/kubernetes/

  **SEE ALSO**  Helm chart repo:
                https://github.com/datazip-inc/olake-helm

  **TAGS**      kubernetes · helm · k8s · production · deployment

  **KEY         Helm, Kubernetes, olake-helm
  ENTITIES**    

  **ANSWERS     How do I deploy OLake on Kubernetes?\
  QUESTIONS     Is there a Helm chart for OLake?
  LIKE**        

  **UPDATE      Update when Helm chart values or minimum K8s version
  WHEN**        changes.
  ------------- ---------------------------------------------------------

OLake provides official Helm charts via datazip-inc/olake-helm. See
https://olake.io/docs/install/kubernetes/ for full chart values
reference and production deployment guide.

2.4 Playground --- Local Demo Environment

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/getting-started/playground/

  **TAGS**      playground · demo · local · presto · mysql

  **KEY         Playground, Presto, MySQL, Temporal UI, weather dataset
  ENTITIES**    

  **ANSWERS     How do I try OLake locally?\
  QUESTIONS     What is the OLake playground?\
  LIKE**        How do I query Iceberg tables with Presto?

  **UPDATE      Update if playground components or default dataset
  WHEN**        change.
  ------------- ---------------------------------------------------------

Zero-config demo environment for exploring lakehouse architecture.
Includes MySQL source, OLake UI, Temporal, and Presto for querying ---
all launched with one command. The weather dataset is pre-loaded into
MySQL.

> git clone https://github.com/datazip-inc/olake.git
>
> cd olake/examples
>
> docker compose up

  --------------- ----------------------- ---------------------------------
  **Service**     **URL**                 **Credentials**

  OLake UI        http://localhost:8000   admin / password

  Presto CLI      http://localhost:80     No auth; connects to Iceberg
                                          catalog

  Temporal UI     http://localhost:8088   No auth
  --------------- ----------------------- ---------------------------------

**Querying Iceberg tables in Presto:**

> USE iceberg.weather;
>
> SHOW TABLES;
>
> SELECT \* FROM weather LIMIT 10;

§3 OLake Features

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/features/

  **SEE ALSO**  What makes OLake fast (blog):
                https://olake.io/blog/what-makes-olake-fast/\
                Schema evolution blog:
                https://olake.io/blog/2025/10/03/iceberg-metadata/\
                Iceberg partitioning:
                https://olake.io/docs/writers/iceberg/partitioning/

  **LAST        Nov 2025
  UPDATED**     

  **TAGS**      features · sync-modes · cdc · chunking · schema-evolution
                · deduplication · partitioning · normalization ·
                data-filter · append-mode · DLQ

  **KEY         Full Refresh, Incremental, CDC, Strict CDC, chunking,
  ENTITIES**    deduplication, Iceberg partitioning, Hive partitioning,
                normalization, schema evolution, type promotion, DLQ,
                data filter, append mode

  **ANSWERS     What sync modes does OLake support?\
  QUESTIONS     What is Strict CDC?\
  LIKE**        How does OLake handle schema changes?\
                Does OLake deduplicate data?\
                What is normalization in OLake?\
                How does OLake partition Iceberg tables?\
                What data type promotions does OLake support?\
                What happens when an unsupported type change occurs?\
                Can I filter which rows get replicated?\
                What is the Dead Letter Queue (DLQ) in OLake?

  **UPDATE      Update when new sync modes, partitioning transforms, or
  WHEN**        type promotion rules are added.
  ------------- ---------------------------------------------------------

3.1 Source-Level Features

3.1.1 Parallelised Chunking

Splits large tables into virtual chunks processed simultaneously ---
without modifying source data. Used in Full Refresh, Full Refresh + CDC,
and Full Refresh + Incremental modes.

  ------------------ ----------------------------------------------------
  **Source**         **Chunking Strategy**

  PostgreSQL         CTID ranges, batch-size splits, next-query paging

  MySQL              Range splits with LIMIT/OFFSET

  MongoDB            Split-Vector, Bucket-Auto, Timestamp-based

  Oracle             DBMS_PARALLEL_EXECUTE

  Kafka              Partition-level reading via consumer group
  ------------------ ----------------------------------------------------

3.1.2 Sync Modes

  --------------------- ---------------------------- --------------- --------------
  **Mode**              **Description**              **Stateful?**   **Notes**

  Full Refresh          Loads entire table on every  No              Always append
                        run.                                         mode at
                                                                     destination.

  Full Refresh +        Initial full load, then      Yes             Resumable;
  Incremental           captures new/changed rows                    cursor is
                        via cursor column (e.g.,                     primary or
                        updated_at).                                 fallback
                                                                     column.

  Full Refresh + CDC    Initial full load, then near Yes             Recommended
                        real-time                                    for most
                        inserts/updates/deletes via                  production use
                        log-based CDC.                               cases.

  Strict CDC            Log-based CDC only --- no    Yes             Use when
                        initial full load.                           snapshot is
                                                                     not needed.
  --------------------- ---------------------------- --------------- --------------

3.1.3 Stateful, Resumable Syncs

Maintains a state.json checkpoint. On interruption (crash, network
failure, pause), the next sync resumes from the last saved position.
Eliminates restarting from scratch. Reduces duplication and processing
time.

3.1.4 Configurable Max Connections

Set via max_threads in source.json. Controls how many parallel database
connections OLake opens, preventing source system overload.

3.1.5 Exact Source Data Type Mapping

OLake guarantees accurate mapping from source DB types to
Iceberg/Parquet types, maintaining schema integrity end-to-end.

3.1.6 Data Filters

Column-condition row filtering applied at the source. Reduces DB load,
saves storage, and speeds downstream queries. Available for Full
Refresh, Full Refresh + Incremental, and Full Refresh + CDC modes.

*Example condition: dropoff_datetime \>= 2010-01-01 00:00:00*

3.2 Destination-Level Features

3.2.1 Data Deduplication

Automatic upsert using source primary key. Each primary key maps to
exactly one destination row (via Iceberg equality deletes). Each row
receives a synthetic olake_id column. Upsert mode writes a delete entry
for existing rows before inserting the new version.

3.2.2 Append Mode

All incoming data added without deduplication. Full Refresh always uses
append mode. For CDC/Incremental syncs, enabling append mode disables
upsert behaviour.

3.2.3 Partitioning

Two partitioning flavours:

-   Iceberg partitioning: Metadata-driven. No directory-based layouts.
    Enables partition pruning and schema evolution. Configured via
    partition_regex in streams.json.

-   S3-style (Hive) partitioning: Traditional folder layout (e.g.,
    year=2025/month=08/day=22/) for compatibility with external tools.

Supported Iceberg partition transforms: identity, year, month, day,
hour, bucket(N), truncate(W), void. The now() pseudo-column maps to
\_olake_timestamp.

*RAM note: each partition writer uses \~20-50 MB. Total RAM = threads ×
partitions × 20-50 MB.*

3.2.4 Normalization (L1 JSON Flattening)

When enabled per stream, OLake expands level-1 nested JSON fields into
top-level Iceberg columns. Preserves all data; simplifies SQL queries.
Configure per stream in streams.json or via the UI.

3.2.5 Schema Evolution --- Column-Level Changes

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/features/

  **TAGS**      schema-evolution · column-add · column-drop ·
                column-rename

  **KEY         schema evolution, Iceberg field-ID, column add, column
  ENTITIES**    delete, column rename

  **ANSWERS     What happens when I add a column in the source?\
  QUESTIONS     What happens when I rename a column?\
  LIKE**        How does OLake handle column deletions?

  **UPDATE      Update if OLake adds rename-by-field-ID support
  WHEN**        (currently WIP).
  ------------- ---------------------------------------------------------

  ------------------- -------------------------- --------------- ---------------
  **Change**          **OLake Behaviour**        **Impact**      **Tips**

  Add column          Detected at sync start via No breakage. No Monitor write
                      schema discovery.          user action.    throughput if
                      Automatically added to                     source
                      Iceberg schema with a new                  back-fills
                      field-ID. New data                         historical
                      includes values;                           rows.
                      historical rows show NULL.                 

  Delete column       Detected at sync start. No No breakage.    BI tools may
                      new values written; column Old snapshots   show column
                      remains in Iceberg         queryable.      full of NULLs
                      metadata for historical                    after deletion.
                      query access.                              Communicate
                                                                 schema changes
                                                                 to downstream
                                                                 teams.

  Rename column       Old column retained        No breakage.    Update
                      (null-filled). New column                  downstream SQL
                      created with updated name.                 to use new
                      WIP: field-ID rename                       column name.
                      (instant, no rewrites).                    

  JSON key            Added keys appear          No breakage.    ---
  add/remove/rename   automatically. Removed                     
                      keys vanish from new rows.                 
                      Renamed keys treated as                    
                      remove + add.                              
  ------------------- -------------------------- --------------- ---------------

*Note: A sparse new column will not be synced to the destination unless
at least 1 non-NULL value exists (Iceberg stores data column-wise as
Parquet).*

3.2.6 Schema Evolution --- Table-Level Changes

  --------------- ---------------------------------- ---------------------
  **Change**      **OLake Behaviour**                **Impact**

  Add table       New table appears in UI/streams    No breakage to
                  list. Synced when selected.        existing pipelines.

  Delete table    No new data written. Iceberg table No breakage. Historic
                  and historical data remain.        data preserved.

  Rename table    Treated as a new table. Old        Post-rename data
                  Iceberg table retains historic     lands in separate
                  data. Enable sync for new table to table. Merge
                  continue replication.              histories manually if
                                                     continuous lineage is
                                                     needed.
  --------------- ---------------------------------- ---------------------

3.2.7 Data Type Changes --- Iceberg v2 Type Promotions

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/features/

  **TAGS**      type-promotion · schema-data-type · Iceberg-v2 · DLQ

  **KEY         INT, LONG, BIGINT, FLOAT, DOUBLE, DATE, TIMESTAMP,
  ENTITIES**    DECIMAL, STRING, DLQ

  **ANSWERS     What type changes does OLake support?\
  QUESTIONS     What happens if I change a column from INT to STRING?\
  LIKE**        What is a narrowing type conversion?

  **UPDATE      Update when DLQ feature ships or when new Iceberg type
  WHEN**        promotions are added.
  ------------- ---------------------------------------------------------

**Supported (widening) promotions --- handled automatically:**

  ------------------ -------------------------- -------------------------
  **From**           **To**                     **Notes**

  INT                LONG (BIGINT)              Safe widening.

  FLOAT              DOUBLE                     Higher precision, no data
                                                loss.

  DATE               TIMESTAMP / TIMESTAMP_NS   Dates safely promoted to
                                                timestamps.

  DECIMAL(P,S)       DECIMAL(P\',S) where       Widening precision only.
                     P\'\>P                     

  INT / BIGINT       FLOAT / DOUBLE             Safe numeric conversion
                                                (not a schema change in
                                                Iceberg).
  ------------------ -------------------------- -------------------------

**Handled gracefully --- validated at runtime:**

-   BIGINT → INT: OLake validates each value fits INT range before
    writing.

-   DOUBLE → FLOAT: Similarly validated.

-   (INT, LONG, FLOAT, DOUBLE) → STRING: Values converted to string
    representation and stored as STRING.

**Unsupported --- sync fails:**

-   Writing a FLOAT value into an INT column.

-   Writing a STRING value into INT / DOUBLE / LONG / FLOAT column.

*WIP: Dead Letter Queue (DLQ) columns will capture incompatible values
without halting the sync.*

3.2.8 Dead Letter Queue (DLQ) --- WIP

Future feature. Will capture values with incompatible type changes in a
separate DLQ column, preventing sync failures. Pipelines continue; users
fix mismatches at their convenience.

§4 Source Connectors

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/connectors/postgres/

  **SEE ALSO**  PostgreSQL connector:
                https://olake.io/docs/connectors/postgres/\
                MySQL connector: https://olake.io/docs/connectors/mysql/\
                MongoDB connector:
                https://olake.io/docs/connectors/mongodb/\
                Oracle connector:
                https://olake.io/docs/connectors/oracle/\
                Kafka connector: https://olake.io/docs/connectors/kafka/

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      connectors · source · postgres · mysql · mongodb · oracle
                · kafka

  **KEY         PostgreSQL, MySQL, MongoDB, Oracle, Kafka, pgoutput,
  ENTITIES**    binlog, oplog, CDC, replica set

  **ANSWERS     Which databases does OLake support as sources?\
  QUESTIONS     Does OLake support Kafka as a source?\
  LIKE**        What is the maximum throughput for PostgreSQL
                replication?

  **UPDATE      Add new H2 subsections when new source connectors are
  WHEN**        released.
  ------------- ---------------------------------------------------------

4.1 PostgreSQL Connector

  ------------- ----------------------------------------------------------------
  **DOC URL**   https://olake.io/docs/connectors/postgres/

  **SEE ALSO**  Generic PostgreSQL CDC setup:
                https://olake.io/docs/connectors/postgres/setup/generic/\
                RDS PostgreSQL setup:
                https://olake.io/docs/connectors/postgres/setup/rds/\
                Aurora PostgreSQL setup:
                https://olake.io/docs/connectors/postgres/setup/aurora/\
                Azure PostgreSQL setup:
                https://olake.io/docs/connectors/postgres/setup/azure/\
                Postgres → Iceberg (blog):
                https://olake.io/blog/how-to-set-up-postgres-apache-iceberg/\
                CDC on AWS RDS (blog):
                https://olake.io/blog/how-to-set-up-postgresql-cdc-on-aws-rds/

  **LAST        Jan 2026
  UPDATED**     

  **TAGS**      postgres · postgresql · CDC · pgoutput · logical-replication ·
                RDS · Aurora · Supabase · Azure · replication-slot · publication
                · WAL

  **KEY         PostgreSQL, pgoutput, wal_level, replication slot, publication,
  ENTITIES**    WAL, RDS, Aurora, Supabase, Azure PostgreSQL, CTID,
                pg_create_logical_replication_slot

  **ANSWERS     How do I set up PostgreSQL as an OLake source?\
  QUESTIONS     How do I configure CDC for PostgreSQL?\
  LIKE**        What is pgoutput?\
                How do I create a replication slot for OLake?\
                Does OLake support RDS PostgreSQL?\
                Does OLake support Aurora PostgreSQL?\
                Does OLake support Supabase?\
                How do I set wal_level to logical?\
                What PostgreSQL permissions does OLake need?\
                How do I troubleshoot WAL bloat caused by OLake?

  **UPDATE      Update config fields and CDC setup steps if pgoutput API
  WHEN**        changes, or if new PostgreSQL-compatible variants are supported.
  ------------- ----------------------------------------------------------------

  ---------------------- ------------------------------------------------
  **Property**           **Value**

  Sync Modes             Full Refresh, Full Refresh + Incremental, Full
                         Refresh + CDC, Strict CDC

  CDC Mechanism          pgoutput (native PostgreSQL logical replication,
                         PG 10+)

  Chunking               CTID ranges, batch-size splits, next-query
                         paging

  Full Load RPS          580,113 (benchmark; Azure D64ls v5 / Azure
                         D32ads_v5 DB)

  CDC RPS                55,555 (50 M rows in 15 min)

  Supported Variants     PostgreSQL, RDS, Aurora, Supabase, Cloud SQL,
                         Azure Flexible Server, any pgoutput-compatible
                         instance
  ---------------------- ------------------------------------------------

4.1.1 source.json Configuration (PostgreSQL)

> {
>
> \"host\": \"localhost\",
>
> \"port\": 5432,
>
> \"database\": \"main\",
>
> \"username\": \"olake_user\",
>
> \"password\": \"password\",
>
> \"jdbc_url_params\": { \"connectTimeout\": \"20\" },
>
> \"retry_count\": 3,
>
> \"ssl\": { \"mode\": \"disable\" },
>
> \"update_method\": { // omit for Full Refresh / Incremental
>
> \"replication_slot\": \"postgres_slot\",
>
> \"publication\": \"postgres_pub\",
>
> \"initial_wait_time\": 120
>
> },
>
> \"max_threads\": 5,
>
> \"ssh_config\": { // optional SSH tunnel
>
> \"host\": \"tunnel-host\",
>
> \"port\": 22,
>
> \"username\": \"tunnel-user\",
>
> \"password\": \"tunnel-pass\"
>
> }
>
> }

4.1.2 CDC Prerequisites (pgoutput)

  -------------------------- -------------------------------------------------------
  **Requirement**            **Action**

  PostgreSQL 10+             Verify: SELECT version();

  wal_level = logical        ALTER SYSTEM SET wal_level = \'logical\'; \-- then
                             restart PostgreSQL

  max_replication_slots ≥4   ALTER SYSTEM SET max_replication_slots = 4; \-- or
                             higher

  max_wal_senders ≥4         ALTER SYSTEM SET max_wal_senders = 4;

  Replication slot           SELECT
                             pg_create_logical_replication_slot(\'postgres_slot\',
                             \'pgoutput\');

  Publication                CREATE PUBLICATION postgres_pub FOR ALL TABLES;

  REPLICATION role           ALTER USER olake_user WITH REPLICATION;

  Table SELECT grant         GRANT SELECT ON ALL TABLES IN SCHEMA public TO
                             olake_user;
  -------------------------- -------------------------------------------------------

4.1.3 Variant-Specific Setup

**RDS PostgreSQL:**

-   Create a custom DB parameter group (default group cannot be
    modified).

-   Set rds.logical_replication = 1 in the parameter group.

-   Reboot the RDS instance (static parameter --- requires restart).

-   Grant replication: GRANT rds_replication TO cdc_user;

-   Enable automated backups (backup_retention \> 0) for WAL retention.

-   Monitor WAL disk: CloudWatch → TransactionLogsDiskUsage.

-   Reference: https://olake.io/docs/connectors/postgres/setup/rds/

**Aurora PostgreSQL:**

-   Modify the cluster parameter group (not instance-level).

-   Set rds.logical_replication = 1 and reboot the writer node.

-   Use default postgres user (rds_superuser) or grant rds_superuser to
    custom user.

-   PostgreSQL 16+: logical replication on read replicas supported with
    caveats.

-   Reference: https://olake.io/docs/connectors/postgres/setup/aurora/

**Azure PostgreSQL Flexible Server:**

-   Set wal_level = logical in server parameters.

-   User needs azure_pg_admin + REPLICATION roles.

-   Connection string format: servername.postgres.database.azure.com.

-   Reference: https://olake.io/docs/connectors/postgres/setup/azure/

**Self-Hosted / Generic:**

-   Edit postgresql.conf: wal_level = logical, max_replication_slots =
    4, max_wal_senders = 4.

-   Edit pg_hba.conf to allow replication connections from OLake host.

-   Restart PostgreSQL to apply.

-   Reference: https://olake.io/docs/connectors/postgres/setup/generic/

4.1.4 Replica Identity for CDC

  ------------ --------------- -------------- --------------------------------
  **Mode**     **Uses**        **Overhead**   **Recommendation**

  DEFAULT      Primary key     Low            Use if table has a PK
                                              (recommended).

  FULL         All columns     High           Use for tables without PK.

  INDEX        Unique index    Medium         Use specific unique index.

  NOTHING      None            None           Only INSERT operations
                                              replicated; deletes/updates not
                                              captured.
  ------------ --------------- -------------- --------------------------------

> ALTER TABLE public.my_table REPLICA IDENTITY DEFAULT; \-- recommended
>
> ALTER TABLE public.my_table REPLICA IDENTITY FULL; \-- tables without
> PK

4.1.5 Troubleshooting --- PostgreSQL

  ---------------------- --------------------- -----------------------------------
  **Error / Symptom**    **Cause**             **Fix**

  Permission denied for  Missing REPLICATION   GRANT rds_replication TO user; or
  replication slot       role                  ALTER ROLE user WITH REPLICATION;

  pgoutput not found     wal_level not logical Set wal_level=logical; restart;
                         or version \< 10      verify PG version.

  WAL bloat / disk full  Inactive replication  Monitor
                         slot retaining WAL    pg_replication_slots.restart_lsn;
                                               restart CDC or drop slot if
                                               lagging.

  No changes captured    wal_level wrong or    Check: SELECT \* FROM
                         slot inactive         pg_replication_slots; verify
                                               active=t.

  Parameter group not    Reboot not done or    Verify instance uses custom group;
  applying (RDS)         wrong parameter group reboot after saving changes.

  ERROR: publication is  Missing publication   Add \"publication\":
  required for pgoutput  name in source.json   \"postgres_pub\" to update_method
                                               block.
  ---------------------- --------------------- -----------------------------------

4.2 MySQL Connector

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/connectors/mysql/

  **SEE ALSO**  RDS MySQL setup:
                https://olake.io/docs/connectors/mysql/setup/rds/\
                Aurora MySQL setup:
                https://olake.io/docs/connectors/mysql/setup/aurora/\
                Azure MySQL setup:
                https://olake.io/docs/connectors/mysql/setup/azure/\
                GCP Cloud SQL MySQL:
                https://olake.io/docs/connectors/mysql/setup/gcp/

  **LAST        Nov 2025
  UPDATED**     

  **TAGS**      mysql · binlog · CDC · RDS · Aurora · Azure · GCP · Cloud
                SQL

  **KEY         MySQL, binlog, log-bin, binlog_format, ROW, REPLICATION
  ENTITIES**    SLAVE, REPLICATION CLIENT, RDS MySQL, Aurora MySQL

  **ANSWERS     How do I configure MySQL as an OLake source?\
  QUESTIONS     How do I enable binlog for CDC?\
  LIKE**        What MySQL permissions does OLake need?\
                Does OLake support Aurora MySQL?\
                How do I set binlog_format = ROW?

  **UPDATE      Update if MySQL versions change or new MySQL-compatible
  WHEN**        variants are added.
  ------------- ---------------------------------------------------------

  ---------------------- ------------------------------------------------
  **Property**           **Value**

  Sync Modes             Full Refresh, Full Refresh + Incremental, Full
                         Refresh + CDC, Strict CDC

  CDC Mechanism          Binary logs (binlog) with ROW format

  Chunking               Range splits with LIMIT/OFFSET

  Full Load RPS          338,005 (benchmark; AWS c6i.16xlarge / Azure
                         D32as_v6)

  CDC RPS                51,867 (50 M rows in 16 min)

  Supported              MySQL, RDS MySQL, Aurora MySQL, Cloud SQL, Azure
                         MySQL, community versions
  ---------------------- ------------------------------------------------

4.2.1 source.json Configuration (MySQL)

> {
>
> \"hosts\": \"localhost\",
>
> \"username\": \"root\",
>
> \"password\": \"password\",
>
> \"database\": \"main\",
>
> \"port\": 3306,
>
> \"tls_skip_verify\": true,
>
> \"update_method\": { // omit for Full Refresh
>
> \"intial_wait_time\": 10
>
> },
>
> \"max_threads\": 5,
>
> \"backoff_retry_count\": 4
>
> }

4.2.2 CDC Prerequisites (Binlog)

  ---------------------- ------------------------------------------------
  **Requirement**        **Command / Config**

  Enable binlog          Add log-bin = mysql-bin to my.cnf; restart
                         MySQL.

  Set ROW format         Add binlog-format = ROW to my.cnf; restart
                         MySQL.

  Verify                 SHOW BINARY LOGS; and SHOW MASTER STATUS;

  CDC user grants        GRANT SELECT, REPLICATION SLAVE, REPLICATION
                         CLIENT ON \*.\* TO \'cdc_user\'@\'%\';
  ---------------------- ------------------------------------------------

4.2.3 Variant-Specific Notes

**RDS MySQL:**

-   Create a custom DB parameter group; set binlog_format = ROW, log_bin
    = ON.

-   Reboot after parameter group change.

-   Set binlog retention: CALL mysql.rds_set_configuration(\'binlog
    retention hours\', 24);

-   Reference: https://olake.io/docs/connectors/mysql/setup/rds/

**Aurora MySQL:**

-   Modify cluster parameter group (not instance-level) ---
    binlog_format must be cluster-level.

-   Reboot cluster writer node after change.

-   Reference: https://olake.io/docs/connectors/mysql/setup/aurora/

**GCP Cloud SQL MySQL:**

-   Set log_bin = ON and binlog_format = ROW database flags; restart
    instance.

-   For read replica CDC: set log_slave_updates = ON.

-   Reference: https://olake.io/docs/connectors/mysql/setup/gcp/

**Azure MySQL Flexible Server:**

-   Set log_bin = ON and binlog_format = ROW in server parameters;
    restart.

-   Connection format: servername.mysql.database.azure.com.

-   Reference: https://olake.io/docs/connectors/mysql/setup/azure/

4.2.4 Troubleshooting --- MySQL

  -------------------------- --------------------------------------------
  **Error / Symptom**        **Fix**

  Binary logging not enabled Add log-bin = mysql-bin to my.cnf; restart.

  binlog_format not ROW      Set binlog-format = ROW; restart.

  Cannot find my.cnf         Run: mysql \--help \| grep \"Default
                             options\"

  Binlog purged too quickly  Increase retention: CALL
  (RDS)                      mysql.rds_set_configuration(\'binlog
                             retention hours\', 72);
  -------------------------- --------------------------------------------

4.3 MongoDB Connector

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/connectors/mongodb/

  **SEE ALSO**  Local MongoDB setup:
                https://olake.io/docs/connectors/mongodb/setup/local/\
                Atlas MongoDB setup:
                https://olake.io/docs/connectors/mongodb/setup/atlas/

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      mongodb · oplog · change-streams · CDC · replica-set ·
                sharded · Atlas

  **KEY         MongoDB, oplog, change streams, replica set, sharded
  ENTITIES**    cluster, Atlas, Split-Vector, Bucket-Auto

  **ANSWERS     How do I configure MongoDB as an OLake source?\
  QUESTIONS     What MongoDB versions does OLake support?\
  LIKE**        How does OLake capture changes from MongoDB?\
                Does OLake support sharded MongoDB clusters?\
                Does OLake support MongoDB Atlas?

  **UPDATE      Update if oplog/change-stream API changes or new cluster
  WHEN**        topologies are supported.
  ------------- ---------------------------------------------------------

  ---------------------- ------------------------------------------------
  **Property**           **Value**

  Sync Modes             Full Refresh, Full Refresh + Incremental, Full
                         Refresh + CDC, Strict CDC

  CDC Mechanism          Oplog / Change Streams

  Chunking               Split-Vector, Bucket-Auto, Timestamp-based

  Full Load RPS          37,879 (benchmark; 233 M tweets rows)

  CDC RPS                10,692 (50 M changes in 39 min)

  Supported              Replica set clusters, sharded clusters, MongoDB
                         Atlas
  ---------------------- ------------------------------------------------

4.3.1 source.json Configuration (MongoDB)

> {
>
> \"hosts\": \"primary_host:27017\",
>
> \"username\": \"admin\",
>
> \"password\": \"password\",
>
> \"auth_source\": \"admin\",
>
> \"replica_set\": \"rs0\",
>
> \"database\": \"mydb\",
>
> \"max_threads\": 10,
>
> \"update_method\": { // omit for Full Refresh
>
> \"initial_wait_time\": 10
>
> }
>
> }

In Docker environments, replace localhost with host.docker.internal to
reach the host machine.

4.3.2 Notes on MongoDB Schema

-   MongoDB is schema-less; OLake detects evolving document structures
    and handles new column creation automatically.

-   Non-breaking data type changes are handled via schema evolution
    rules (§3.2.7).

-   Nested documents: use normalization (L1 flattening) for top-level
    key promotion.

4.4 Oracle Connector

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/connectors/oracle/

  **LAST        Jan 2026
  UPDATED**     

  **TAGS**      oracle · full-refresh · incremental ·
                DBMS_PARALLEL_EXECUTE

  **KEY         Oracle, DBMS_PARALLEL_EXECUTE, RDS Oracle, service_name
  ENTITIES**    

  **ANSWERS     How do I configure Oracle as an OLake source?\
  QUESTIONS     Does OLake support Oracle CDC?\
  LIKE**        What Oracle versions does OLake support?

  **UPDATE      Update when Oracle CDC support is added (currently WIP).
  WHEN**        
  ------------- ---------------------------------------------------------

  ---------------------- ------------------------------------------------
  **Property**           **Value**

  Sync Modes             Full Refresh, Full Refresh + Incremental (CDC
                         --- WIP)

  Chunking               DBMS_PARALLEL_EXECUTE

  Full Load RPS          526,337 (benchmark; Azure D64ls v5 / AWS RDS
                         db.r6i.4xlarge)

  Supported              Oracle Database (on-prem and AWS RDS Oracle)
  ---------------------- ------------------------------------------------

4.4.1 source.json Configuration (Oracle)

> {
>
> \"host\": \"oracle-host\",
>
> \"username\": \"oracle-user\",
>
> \"password\": \"oracle-password\",
>
> \"service_name\": \"oracle-service-name\",
>
> \"port\": 1521,
>
> \"max_threads\": 10,
>
> \"retry_count\": 0,
>
> \"jdbc_url_params\": {},
>
> \"ssl\": { \"mode\": \"disable\" }
>
> }

4.5 Apache Kafka Connector

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/connectors/kafka/

  **LAST        Dec 2025
  UPDATED**     

  **TAGS**      kafka · streaming · consumer-group · append-only · MSK

  **KEY         Kafka, consumer group, topic, partition, MSK, append-only
  ENTITIES**    

  **ANSWERS     How does OLake work with Kafka?\
  QUESTIONS     Does OLake support Kafka as a source?\
  LIKE**        How fast is OLake for Kafka?\
                What is the throughput for Kafka ingestion into Iceberg?

  **UPDATE      Update when Kafka CDC or non-append modes are added.
  WHEN**        
  ------------- ---------------------------------------------------------

  ---------------------- ------------------------------------------------
  **Property**           **Value**

  Sync Mode              Consumer Group Based Streaming (Append Only)

  Chunking               Partition-level; each consumer handles its
                         assigned partitions

  Throughput             154,320 MPS (benchmark; 1 B messages, AWS MSK
                         3×m7g.4xlarge, Azure D64ls v6)

  Notes                  Data is appended; no deduplication for Kafka
                         sources.
  ---------------------- ------------------------------------------------

§5 Destination Connectors

  ------------- -------------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/iceberg/catalog/glue/

  **SEE ALSO**  Iceberg Glue writer:
                https://olake.io/docs/writers/iceberg/catalog/glue/\
                Iceberg REST writer:
                https://olake.io/docs/writers/iceberg/catalog/rest/\
                Iceberg Hive writer:
                https://olake.io/docs/writers/iceberg/catalog/hive/\
                Iceberg JDBC writer:
                https://olake.io/docs/writers/iceberg/catalog/jdbc/\
                Iceberg partitioning:
                https://olake.io/docs/writers/iceberg/partitioning/\
                S3 Parquet writer: https://olake.io/docs/writers/parquet/s3/\
                GCS Parquet writer:
                https://olake.io/docs/writers/parquet/gcs/\
                Catalog compatibility:
                https://olake.io/docs/understanding/compatibility-catalogs/

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      destination · iceberg · glue · REST · nessie · polaris ·
                unity · lakekeeper · s3-tables · hive · jdbc · parquet · s3 ·
                gcs · minio

  **KEY         Apache Iceberg, AWS Glue, Nessie, Polaris, Unity Catalog,
  ENTITIES**    LakeKeeper, S3 Tables, Hive Metastore, JDBC, Parquet, S3,
                GCS, MinIO, destination.json

  **ANSWERS     How do I configure OLake to write to Iceberg?\
  QUESTIONS     How do I set up AWS Glue as the Iceberg catalog?\
  LIKE**        How do I use Nessie with OLake?\
                How do I configure Polaris as the Iceberg REST catalog?\
                How do I write Parquet files to S3?\
                How do I configure GCS as the OLake destination?\
                What IAM permissions does OLake need for AWS Glue?\
                How do I configure a JDBC catalog?\
                What is the destination.json structure?

  **UPDATE      Update destination.json configs when new catalog fields or
  WHEN**        authentication methods are added.
  ------------- -------------------------------------------------------------

5.1 Apache Iceberg --- AWS Glue Catalog

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/iceberg/catalog/glue/

  **TAGS**      glue · AWS · S3 · IAM · Athena

  **KEY         AWS Glue, S3, IAM, Athena, glue:CreateTable,
  ENTITIES**    glue:GetTable, catalog_type=glue

  **ANSWERS     How do I configure AWS Glue as the OLake Iceberg
  QUESTIONS     catalog?\
  LIKE**        What IAM permissions are needed?\
                How do I query OLake Iceberg tables with Athena?
  ------------- ---------------------------------------------------------

**Required IAM Permissions:**

-   Glue: CreateTable, CreateDatabase, GetTable, GetDatabase,
    GetDatabases, SearchTables, UpdateDatabase, UpdateTable,
    GetPartitions

-   S3: ListBucket, GetBucket\*, s3:\*Object on target bucket and path

**destination.json:**

> {
>
> \"type\": \"ICEBERG\",
>
> \"writer\": {
>
> \"catalog_type\": \"glue\",
>
> \"catalog_name\": \"olake_iceberg\",
>
> \"iceberg_s3_path\": \"s3://\<BUCKET_NAME\>/\",
>
> \"aws_region\": \"us-east-1\",
>
> \"aws_access_key\": \"XXX\",
>
> \"aws_secret_key\": \"XXX\"
>
> }
>
> }

**Query with Athena:**

> SELECT \* FROM \"ICEBERG_DATABASE_NAME\".\"TABLE_NAME\" LIMIT 10;

5.2 Apache Iceberg --- REST Catalog (Nessie, Polaris, Unity, LakeKeeper,
S3 Tables)

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/iceberg/catalog/rest/

  **TAGS**      REST · nessie · polaris · unity · lakekeeper · s3-tables
                · oauth2

  **KEY         REST catalog, Nessie, Polaris, Unity Catalog, LakeKeeper,
  ENTITIES**    S3 Tables, OAuth2, catalog_type=rest

  **ANSWERS     How do I configure Nessie as the Iceberg catalog?\
  QUESTIONS     How does Polaris OAuth2 work with OLake?\
  LIKE**        How do I use Unity Catalog with OLake?
  ------------- ---------------------------------------------------------

**Generic REST destination.json:**

> {
>
> \"type\": \"ICEBERG\",
>
> \"writer\": {
>
> \"catalog_type\": \"rest\",
>
> \"rest_catalog_url\": \"http://\<REST_ENDPOINT\>:8181/api/catalog\",
>
> \"catalog_name\": \"olake_iceberg\",
>
> \"iceberg_s3_path\": \"warehouse\",
>
> \"iceberg_db\": \"ICEBERG_DATABASE_NAME\"
>
> }
>
> }

**For Polaris (OAuth2):**

> \"rest_auth_type\": \"oauth2\",
>
> \"oauth2_uri\": \"http://\<HOST\>:8181/api/catalog/v1/oauth/tokens\",
>
> \"credential\": \"\<client_id\>:\<client_secret\>\",
>
> \"scope\": \"PRINCIPAL_ROLE:ALL\",
>
> \"aws_region\": \"\<S3_REGION\>\"

  ---------------- --------------------------------- --------------------
  **Catalog        **Key Feature**                   **Auth Method**
  Variant**                                          

  Nessie           Git-like branch/tag/merge for     None / Bearer token
                   data                              

  Polaris          OAuth2, fine-grained RBAC,        OAuth2 (client_id +
                   Iceberg REST API                  secret)

  Unity Catalog    Databricks-managed REST catalog   Bearer token

  LakeKeeper       Governance and monitoring         Bearer token
                   extensions over REST API          

  S3 Tables        AWS-managed REST catalog backed   AWS Signature V4
                   directly by S3                    
  ---------------- --------------------------------- --------------------

Constraint: catalog_name must be lowercase letters and underscores only
--- no spaces or special characters.

5.3 Apache Iceberg --- Hive Metastore Catalog

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/iceberg/catalog/hive/

  **TAGS**      hive · metastore · HMS

  **KEY         Hive Metastore, hive_uri, catalog_type=hive, Thrift
  ENTITIES**    

  **ANSWERS     How do I configure Hive Metastore as the Iceberg catalog?
  QUESTIONS     
  LIKE**        
  ------------- ---------------------------------------------------------

**destination.json:**

> {
>
> \"type\": \"ICEBERG\",
>
> \"writer\": {
>
> \"catalog_type\": \"hive\",
>
> \"hive_uri\": \"http://localhost:9083\",
>
> \"iceberg_s3_path\": \"s3a://warehouse/\",
>
> \"aws_region\": \"us-east-1\",
>
> \"aws_access_key\": \"admin\",
>
> \"aws_secret_key\": \"password\",
>
> \"s3_endpoint\": \"http://localhost:9000\"
>
> }
>
> }

5.4 Apache Iceberg --- JDBC Catalog

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/iceberg/catalog/jdbc/

  **TAGS**      jdbc · postgres-catalog · mysql-catalog · minio

  **KEY         JDBC, jdbc_url, catalog_type=jdbc, iceberg_tables,
  ENTITIES**    s3_path_style, MinIO

  **ANSWERS     How do I use PostgreSQL or MySQL as the OLake Iceberg
  QUESTIONS     catalog?\
  LIKE**        When should I use JDBC catalog?\
                How do I configure MinIO with JDBC catalog?
  ------------- ---------------------------------------------------------

Uses a PostgreSQL or MySQL database as the Iceberg metadata catalog.
Data stored in S3 / MinIO. Required DB permissions: CREATE, INSERT,
UPDATE, DELETE, SELECT.

**destination.json:**

> {
>
> \"type\": \"ICEBERG\",
>
> \"writer\": {
>
> \"catalog_type\": \"jdbc\",
>
> \"jdbc_url\": \"jdbc:postgresql://DB_URL:5432/iceberg\",
>
> \"catalog_name\": \"olake_iceberg\",
>
> \"jdbc_username\": \"iceberg\",
>
> \"jdbc_password\": \"password\",
>
> \"iceberg_s3_path\": \"s3://warehouse\",
>
> \"s3_endpoint\": \"http://S3_ENDPOINT\",
>
> \"s3_use_ssl\": false,
>
> \"s3_path_style\": true, // required for MinIO
>
> \"aws_access_key\": \"admin\",
>
> \"aws_region\": \"us-east-1\",
>
> \"aws_secret_key\": \"password\"
>
> }
>
> }

Set s3_path_style: true for MinIO and non-AWS S3 services.

5.5 Iceberg Partitioning Configuration

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/iceberg/partitioning/

  **TAGS**      partitioning · partition-regex · transforms · now() ·
                \_olake_timestamp

  **KEY         partition_regex, identity, year, month, day, hour,
  ENTITIES**    bucket, truncate, void, now(), \_olake_timestamp

  **ANSWERS     How do I partition Iceberg tables in OLake?\
  QUESTIONS     What is partition_regex?\
  LIKE**        What partitioning transforms are available?\
                How do I use now() as a partition column?

  **UPDATE      Update when new partition transforms are added or
  WHEN**        partition_regex syntax changes.
  ------------- ---------------------------------------------------------

Configured per stream in streams.json or via the UI Streams →
Partitioning tab.

**Syntax:**

> \"partition_regex\": \"/{column_name, transform}/{column_name2,
> transform2}\"

**Examples:**

> // Partition by year and month from event_date
>
> \"partition_regex\": \"/{event_date, year}/{event_date, month}\"
>
> // Day-level partitioning of transaction_date + identity on
> account_type
>
> \"partition_regex\": \"/{transaction_date, day}/{account_type,
> identity}\"
>
> // Use OLake write timestamp when no time column exists
>
> \"partition_regex\": \"/{now(), day}\"

  --------------- ------------------------------ -------------------------
  **Transform**   **Description**                **Good For**

  identity        Exact value match.             Low-cardinality
                                                 categorical columns
                                                 (e.g., region, status).

  year            Extracts year from             Time-series data
                  date/timestamp.                partitioned annually.

  month           Extracts month.                Monthly analytics.

  day             Extracts day.                  Daily analytics / logs.

  hour            Extracts hour.                 High-volume event
                                                 streams.

  bucket(N)       Distributes rows into N hash   High-cardinality IDs; no
                  buckets.                       ordering preserved.

  truncate(W)     Truncates to width W (strings) Grouping text prefixes or
                  or interval (numbers).         numeric ranges.

  void            Always produces null; used to  Iceberg v2 partition
                  drop a partition field.        evolution --- dropping an
                                                 existing field.
  --------------- ------------------------------ -------------------------

Constraint: Iceberg does not support two transforms on the same column
within one partition spec (e.g., year + month on event_date requires
separate levels using different column aliases).

5.6 S3 Parquet Writer

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/writers/parquet/s3/

  **SEE ALSO**  GCS Parquet writer:
                https://olake.io/docs/writers/parquet/gcs/

  **TAGS**      parquet · s3 · minio · gcs · raw-files

  **KEY         Parquet, S3, MinIO, GCS, HMAC keys, s3_bucket,
  ENTITIES**    s3_endpoint

  **ANSWERS     How do I write raw Parquet files to S3?\
  QUESTIONS     Does OLake support GCS as a destination?\
  LIKE**        How do I configure MinIO as the Parquet writer
                destination?

  **UPDATE      Update when ADLS or new object storage backends are
  WHEN**        formally documented.
  ------------- ---------------------------------------------------------

**destination.json (AWS S3):**

> {
>
> \"type\": \"PARQUET\",
>
> \"writer\": {
>
> \"s3_bucket\": \"my-bucket\",
>
> \"s3_region\": \"us-east-1\",
>
> \"s3_access_key\": \"XXX\",
>
> \"s3_secret_key\": \"XXX\",
>
> \"s3_path\": \"data/\"
>
> }
>
> }

**destination.json (MinIO):**

> {
>
> \"type\": \"PARQUET\",
>
> \"writer\": {
>
> \"s3_bucket\": \"warehouse\",
>
> \"s3_region\": \"us-east-1\",
>
> \"s3_access_key\": \"admin\",
>
> \"s3_secret_key\": \"password\",
>
> \"s3_endpoint\": \"http://localhost:9000\",
>
> \"s3_path\": \"\"
>
> }
>
> }

**GCS:**

Use GCS HMAC keys (Access Key + Secret Key). Set endpoint to
https://storage.googleapis.com. Refer to
https://olake.io/docs/writers/parquet/gcs/ --- detailed docs coming
soon.

§6 Jobs & Pipeline Management (OLake UI)

  ------------- ----------------------------------------------------------------
  **DOC URL**   https://olake.io/docs/getting-started/creating-first-pipeline/

  **SEE ALSO**  Quickstart guide:
                https://olake.io/docs/getting-started/quickstart/\
                Creating a job (blog):
                https://olake.io/blog/creating-job-olake-docker-cli/

  **LAST        Jan 2026
  UPDATED**     

  **TAGS**      jobs · pipeline · UI · streams · schedule · sync · monitor

  **KEY         Job, stream, schedule, normalization, partitioning, data filter,
  ENTITIES**    Temporal, sync mode

  **ANSWERS     How do I create a job in OLake?\
  QUESTIONS     How do I schedule a data sync?\
  LIKE**        How do I configure streams in OLake?\
                How do I run a sync manually?\
                How do I monitor a running sync?\
                How do I delete a source or destination in OLake?

  **UPDATE      Update when UI workflow steps or scheduling options change.
  WHEN**        
  ------------- ----------------------------------------------------------------

6.1 Job Creation Workflow

  ---------- -------------------------- ---------------------------------------
  **Step**   **Action**                 **Notes**

  1          Navigate to Jobs → Create  ---
             Job.                       

  2          Set Job Name and Schedule  E.g., Every Day at 12:00 AM.
             (frequency + time).        

  3          Configure Source: choose   Test connection before proceeding.
             connector type, OLake      Create new or reuse existing source.
             version, fill connection   
             details.                   

  4          Configure Destination:     Test connection. Create new or reuse
             choose connector type,     existing destination.
             catalog, fill details.     

  5          Configure Streams: select  See §6.2 for stream-level options.
             tables, set sync mode,     
             normalization,             
             partitioning, filters.     

  6          Save / Create Job.         Job is now scheduled. Runs at the
                                        configured time or manually.
  ---------- -------------------------- ---------------------------------------

*Tip: For CDC jobs, ensure the replication slot already exists on the
source before creating the job.*

6.2 Stream-Level Configuration

  ------------------ ---------------------- -----------------------------
  **Option**         **Location in UI**     **Description**

  Select streams     Streams tab →          Choose which
                     checkboxes             tables/collections to
                                            replicate.

  Sync Mode          Stream settings panel  Full Refresh, Incremental,
                     → Sync Mode            Full Refresh + CDC, Strict
                                            CDC.

  Normalization      Stream settings panel  Enable L1 JSON flattening.
                     → toggle               Expands nested JSON fields.

  Partitioning       Stream settings panel  Configure partition_regex
                     → Partitioning tab     (see §5.5).

  Destination DB     Stream settings panel  Override the Iceberg DB or S3
  name                                      folder name.

  Data Filters       Stream settings panel  Column-condition row filter
                                            (e.g., created_at \>
                                            2020-01-01).
  ------------------ ---------------------- -----------------------------

6.3 Job Operations

  ------------------ ---------------------- -----------------------------
  **Action**         **How to**             **Notes**

  Run manually       Jobs page → options    Triggers an immediate sync
                     menu (⋮) → Sync Now    regardless of schedule.

  Monitor status     Jobs page → status     Badge shows Running,
                     badge                  Completed, or Failed.

  View logs          Options menu (⋮) → Job Per-stream log output,
                     Logs and History       timing, row counts.

  Edit job           Click job name         Opens job configuration
                                            wizard.

  Delete source      Destinations tab →     Confirm deletion. Jobs using
                     Actions (⋮) → Delete   the source will break.
  ------------------ ---------------------- -----------------------------

§7 Compatibility

  ------------- -------------------------------------------------------------
  **DOC URL**   https://olake.io/docs/understanding/compatibility-catalogs/

  **SEE ALSO**  Query engine compatibility:
                https://olake.io/docs/understanding/compatibility-engines/\
                Catalog compatibility:
                https://olake.io/docs/understanding/compatibility-catalogs/

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      compatibility · catalog · query-engine · object-storage ·
                Athena · Trino · Spark · DuckDB · Snowflake

  **KEY         AWS Glue, Nessie, Polaris, Unity Catalog, LakeKeeper, S3
  ENTITIES**    Tables, Hive Metastore, JDBC, Athena, Trino, Spark, Flink,
                Presto, Hive, Snowflake, DuckDB, ClickHouse, BigQuery,
                Databricks, S3, GCS, MinIO, ADLS

  **ANSWERS     Which query engines work with OLake Iceberg tables?\
  QUESTIONS     Does OLake work with Snowflake?\
  LIKE**        Does OLake work with DuckDB?\
                Which Iceberg catalogs does OLake support?\
                Does OLake support GCS?\
                Can I query OLake Iceberg tables with Athena?

  **UPDATE      Update when new query engines are verified or catalog support
  WHEN**        changes.
  ------------- -------------------------------------------------------------

7.1 Iceberg Catalog Compatibility

  ------------------ ---------- ------------------------------------------
  **Catalog**        **Type**   **Key Notes**

  AWS Glue           Managed    Most common production setup. Native AWS
                                SDK integration.

  Nessie             REST       Git-like versioning: branch, tag, merge
                                Iceberg tables.

  Apache Polaris     REST       OAuth2 authentication, fine-grained RBAC.

  Unity Catalog      REST       Databricks-managed REST catalog.

  LakeKeeper         REST       Governance and monitoring extensions over
                                REST Catalog API.

  AWS S3 Tables      REST       AWS-managed REST catalog. AWS Signature V4
                                auth.

  Hive Metastore     Hive       Traditional Thrift-based catalog. Supports
                                MinIO + S3.

  JDBC (PG/MySQL)    JDBC       Relational DB as catalog. Use
                                s3_path_style=true for MinIO.
  ------------------ ---------- ------------------------------------------

7.2 Query Engine Compatibility

  ------------------ --------------------- -------------------------------
  **Engine**         **Catalog Support**   **Notes**

  AWS Athena         Glue only             Iceberg v2 tables only when
                                           registered in Glue.

  Trino              REST (v0.288+), Glue  MPP; federate across multiple
                     (AWS SDK jar)         catalogs.

  Apache Spark       All catalogs          Full Iceberg v2 support
                                           including time travel.

  Apache Flink       All catalogs          Streaming + batch queries on
                                           Iceberg.

  Presto / Prestodb  REST (v0.288+), Glue  Compatible with Iceberg tables.

  Apache Hive v4.0+  Glue (AWS bundle),    Requires AWS bundle for Glue.
                     Hive HMS              

  Snowflake          REST (read-only       Reads external REST catalogs;
                     external tables)      read-only.

  Databricks         All catalogs via      Unity endpoint allows
                     Unity federation      federation with Glue, Hive,
                                           Snowflake.

  DuckDB             REST (Nessie,         Glue/Hive not yet supported
                     Tabular)              natively.

  ClickHouse         REST (stable v24.12+) Iceberg tables are read-only.

  BigQuery           None (reads manifests Reads Iceberg manifests without
                     directly)             a catalog.

  Dremio             Polaris, REST, Nessie Native support; JDBC not
                                           supported.

  Impala             Hive Metastore        Glue/REST only via Hive
                                           federation.

  StarRocks          All catalogs          High-performance OLAP.
  ------------------ --------------------- -------------------------------

7.3 Object Storage Compatibility

  ------------------ --------------- ------------------------------------
  **Storage**        **Protocol**    **Notes**

  AWS S3             Native S3       Primary production object store.

  MinIO              S3-compatible   On-prem or Docker. Use
                                     s3_path_style=true and custom
                                     endpoint.

  Google Cloud GCS   S3-compatible   Use HMAC keys; set endpoint to
                     HMAC            https://storage.googleapis.com.

  Azure ADLS         ABFS /          Supported as output; detailed docs
                     S3-compat       in progress.
  ------------------ --------------- ------------------------------------

§8 Benchmarks

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/benchmarks/

  **SEE ALSO**  AWS DMS vs OLake: https://olake.io/docs/dmsvsolake/\
                Debezium vs OLake:
                https://olake.io/blog/debezium-vs-olake/\
                Benchmark data repo:
                https://github.com/datazip-inc/nyc-taxi-data-benchmark

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      benchmarks · performance · throughput · cost · RPS · MPS
                · Fivetran · Airbyte · Debezium · Estuary

  **KEY         RPS, MPS, full load, CDC, Fivetran, Airbyte, Debezium,
  ENTITIES**    Estuary, NYC Taxi, AWS Glue, S3

  **ANSWERS     How fast is OLake compared to Fivetran?\
  QUESTIONS     How fast is OLake compared to Airbyte?\
  LIKE**        How fast is OLake compared to Debezium?\
                What is the throughput of OLake for PostgreSQL?\
                How much does OLake cost compared to Fivetran?\
                What is the CDC throughput for OLake?

  **UPDATE      Update numbers after each new benchmark run. Dates are
  WHEN**        embedded in each row.
  ------------- ---------------------------------------------------------

Dataset: NYC Taxi (trips + fhv_trips), \~4 B rows total. Destination:
AWS Glue + S3. Benchmark repo:
https://github.com/datazip-inc/nyc-taxi-data-benchmark

8.1 PostgreSQL Benchmarks

Environment: Azure Standard D64ls v5 (64 vCPU, 128 GB) / Azure
Standard_D32ads_v5 DB (32 vCores)

**Full Load:**

  --------------------- ------------- ------------------ -----------------
  **Tool (Date)**       **Rows        **Throughput       **vs OLake**
                        Synced**      (RPS)**            

  OLake (Jan 2026)      4.01 B        580,113            ---

  Fivetran (Apr 2025)   4.01 B        46,395             12.5× slower

  Debezium memiiso (Apr 1.28 B        14,839             39.1× slower
  2025)                                                  

  Estuary (Apr 2025)    0.34 B        3,982              146× slower

  Airbyte Cloud (Apr    12.7 M        457                1270× slower
  2025)                                                  
  --------------------- ------------- ------------------ -----------------

**CDC (50 M rows):**

  --------------------- ------------- ------------------ -----------------
  **Tool (Date)**       **Window**    **Throughput       **vs OLake**
                                      (RPS)**            

  OLake                 15 min        55,555             ---

  Fivetran              31 min        26,910             2× slower

  Debezium memiiso      60 min        13,808             4× slower

  Estuary               4.5 h         3,085              18× slower

  Airbyte Cloud         23 h          585                95× slower
  --------------------- ------------- ------------------ -----------------

**Cost (Postgres):**

  ----------------- ------------------------ --------------- -------------
  **Tool**          **Scenario**             **Cost (USD)**  **Rows**

  OLake             Full Load + CDC (D64ls   \< \$6          4.01 B / 50 M
                    v5, 1.91 hrs)                            

  Fivetran          Full Load                \$0             4.01 B

  Fivetran          CDC                      \$2,375.80      50 M

  Estuary           Full Load                \$1,668         0.34 B

  Airbyte Cloud     Full Load                \$5,560         12.7 M

  Airbyte Cloud     CDC                      \$148.95        50 M
  ----------------- ------------------------ --------------- -------------

8.2 MySQL Benchmarks

Environment: AWS EC2 c6i.16xlarge (64 vCPU, 128 GB) / Azure D32as_v6

**Full Load:**

  --------------------- ------------- ------------------ -----------------
  **Tool (Date)**       **Rows        **Throughput       **vs OLake**
                        Synced**      (RPS)**            

  OLake (Nov 2025)      4.0 B         338,005            ---

  Fivetran (Nov 2025)   4.0 B         119,106            2.83× slower
  --------------------- ------------- ------------------ -----------------

**CDC (50 M rows):**

  --------------------- ------------- ------------------ -----------------
  **Tool**              **Window**    **Throughput       **vs OLake**
                                      (RPS)**            

  OLake                 16 min        51,867             ---

  Fivetran              30 min        27,901             1.85× slower
  --------------------- ------------- ------------------ -----------------

8.3 MongoDB Benchmarks

Environment: AWS EC2 c6i.16xlarge / 3 × Azure Standard D16as_v5 nodes.
Dataset: 233 M tweets (664 GB).

**Full Load:**

  --------------------- ------------- ------------------ -----------------
  **Tool (Date)**       **Rows        **Throughput       **vs OLake**
                        Synced**      (RPS)**            

  OLake (Feb 2026)      233 M         37,879             ---

  Fivetran (Feb 2026)   233 M         14,997             2.5× slower
  --------------------- ------------- ------------------ -----------------

**CDC (50 M rows):**

  --------------------- ------------- ------------------ -----------------
  **Tool**              **Window**    **Throughput       **vs OLake**
                                      (RPS)**            

  OLake                 39 min        10,692             ---

  Fivetran              72 min        5,787              1.85× slower
  --------------------- ------------- ------------------ -----------------

8.4 Oracle Benchmarks

Environment: Azure D64ls v5 / AWS RDS db.r6i.4xlarge. Dataset: NYC Taxi
4.01 B rows.

  --------------------- ------------- ------------------ -----------------
  **Tool (Date)**       **Rows        **Throughput       **Cost**
                        Synced**      (RPS)**            

  OLake (Jan 2026)      4.01 B        526,337            \< \$6 (D64ls v5,
                                                         2.11 hrs)
  --------------------- ------------- ------------------ -----------------

8.5 Kafka Benchmarks

Environment: Azure D64ls v6 / AWS MSK 3-broker m7g.4xlarge. Dataset: 1 B
NYC Taxi-schema messages, 5 partitions.

  --------------- ------------ --------------- ------------------ ---------
  **Tool (Date)** **Messages   **Throughput    **Cost**           **vs
                  Synced**     (MPS)**                            OLake**

  OLake (Dec      1.0 B        154,320         \$14.08 (compute + ---
  2025)                                        broker, 1.8 hrs)   

  Flink (Dec      1.0 B        85,470          \$26.13 (compute + 1.8×
  2025)                                        broker, 3.25 hrs)  slower
  --------------- ------------ --------------- ------------------ ---------

§9 Community & Contribution

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/community/contributing/

  **SEE ALSO**  Dev environment setup:
                https://olake.io/docs/community/setting-up-a-dev-env/\
                Commands & flags ref:
                https://olake.io/docs/community/commands-and-flags/\
                Issues & PR guide:
                https://olake.io/docs/community/issues-and-prs/\
                Code of conduct:
                https://olake.io/docs/community/code-of-conduct/\
                Channels: https://olake.io/docs/community/channels/

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      community · contributing · open-source · Slack · GitHub ·
                dev-setup · Helm · GSoC

  **KEY         Slack, GitHub, olake-helm, GSoC, Temporal, Golang, Java
  ENTITIES**    17, Docker

  **ANSWERS     How do I contribute to OLake?\
  QUESTIONS     How do I set up a development environment for OLake?\
  LIKE**        Where can I get help with OLake?\
                What is the OLake Slack?\
                How do I report a bug in OLake?

  **UPDATE      Update when community programs (GSoC, contributor
  WHEN**        program) or dev prerequisites change.
  ------------- ---------------------------------------------------------

9.1 Repositories

  ---------------- ------------------------------------------- -------------------------
  **Repository**   **URL**                                     **Language / Purpose**

  olake            https://github.com/datazip-inc/olake        Golang --- core
                                                               replication engine, CLI

  olake-ui         https://github.com/datazip-inc/olake-ui     TypeScript/React --- web
                                                               UI and BFF

  olake-docs       https://github.com/datazip-inc/olake-docs   MDX/Docusaurus ---
                                                               documentation site

  olake-helm       https://github.com/datazip-inc/olake-helm   Helm --- Kubernetes
                                                               deployment charts
  ---------------- ------------------------------------------- -------------------------

9.2 Community Channels

  ---------------- --------------------------------------------- -----------------------
  **Channel**      **URL / Contact**                             **Purpose**

  Slack            https://olake.io/slack                        Real-time support,
                                                                 roadmap, bug help

  GitHub Issues    https://github.com/datazip-inc/olake/issues   Bug reports, feature
                                                                 requests

  Security         hello@olake.io (private)                      Security
                                                                 vulnerabilities --- do
                                                                 NOT create public
                                                                 issues

  Email            hello@olake.io                                General inquiries

  Twitter/X        https://x.com/\_olake                         Announcements

  LinkedIn         https://linkedin.com/company/datazipio        Company updates

  YouTube          https://youtube.com/@olakeio                  Tutorials, webinars
  ---------------- --------------------------------------------- -----------------------

9.3 Development Environment Setup

-   Prerequisites: Go 1.22+, Java 17 (Iceberg writer), Docker, Maven.

-   Clone: git clone https://github.com/datazip-inc/olake.git && cd
    olake

-   Build binary: ./build.sh (Linux/macOS). On Windows: use Git Bash,
    WSL, or Docker CLI.

-   Spin up local stack (Postgres + Iceberg + Parquet):

> sh -c \'curl -fsSL
> https://raw.githubusercontent.com/datazip-inc/olake-docs/master/docs/community/docker-compose.yml
> -o docker-compose.source.yml && \\
>
> curl -fsSL
> https://raw.githubusercontent.com/datazip-inc/olake/master/destination/iceberg/local-test/docker-compose.yml
> -o docker-compose.destination.yml && \\
>
> docker compose -f docker-compose.source.yml \--profile postgres -f
> docker-compose.destination.yml up -d\'

-   Switch source: replace \--profile postgres with \--profile mongo or
    \--profile mysql.

-   Reference: https://olake.io/docs/community/setting-up-a-dev-env/

9.4 Contribution Guidelines

-   Check open issues before filing:
    https://github.com/datazip-inc/olake/issues

-   Discuss significant changes in Slack before opening a PR.

-   Bug reports must include: steps to reproduce, logs, source.json
    (redacted), OLake version, environment.

-   Feature proposals: discuss in Slack → open GitHub Discussion in
    Ideas category → open PR once approved.

-   PR guide: https://olake.io/docs/community/issues-and-prs/

-   Code of Conduct: https://olake.io/docs/community/code-of-conduct/

§10 Use Cases

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/core/use-cases/

  **LAST        Nov 2025
  UPDATED**     

  **TAGS**      use-cases · lakehouse · real-time · analytics · ML ·
                cost-reduction · open-source-stack · historical ·
                CDC-pipeline

  **KEY         lakehouse, analytics, ML, CDC, Iceberg, cost reduction,
  ENTITIES**    historical data, feature store

  **ANSWERS     What can I use OLake for?\
  QUESTIONS     Is OLake good for real-time analytics?\
  LIKE**        Can I use OLake for ML feature stores?\
                How does OLake reduce cloud data warehouse costs?\
                Can OLake replace Debezium + Kafka?

  **UPDATE      Update if new use cases are documented or existing
  WHEN**        descriptions change.
  ------------- ---------------------------------------------------------

  --------------------- ---------------------------- --------------------
  **Use Case**          **Description**              **Key OLake Features
                                                     Used**

  Real-Time Analytics   Replicate PostgreSQL / MySQL CDC, Full Refresh +
  Lakehouse             / MongoDB / Oracle into      CDC, parallelised
                        Iceberg for near real-time   chunking, Iceberg
                        analytics. Keep production   partitioning.
                        DB unaffected.               

  Open-Source Data      Replace proprietary ETL      Open Iceberg format,
  Stack                 tools. Standardise on        no vendor lock-in.
                        Iceberg for engine-agnostic  
                        querying (Trino, Presto,     
                        Spark, DuckDB, Dremio).      

  Near Real-Time        Sub-minute latency via       Strict CDC / Full
  Analytics             log-based CDC. Suitable for  Refresh + CDC,
                        operational dashboards and   Iceberg hidden
                        time-sensitive reporting.    partitioning,
                                                     metadata pruning.

  Long-Term Retention / Store historical data on     Schema evolution,
  Compliance            cost-efficient S3            Iceberg time-travel,
                        (\~\$0.023/GB) vs RDS        object storage.
                        (\~\$0.115/GB). Instantly    
                        queryable via Iceberg.       

  AI / ML Feature       Continuous replication keeps CDC, Iceberg +
  Stores                ML training datasets and     PySpark / DuckDB
                        feature stores current.      integration.

  Cloud DWH Cost        Offload raw/historical data  Full Refresh + CDC,
  Reduction             from expensive warehouses to Iceberg Parquet
                        Iceberg on object storage.   format, query engine
                                                     compatibility.

  CDC Pipeline          Open-source CDC alternative  pgoutput / binlog /
  Standardisation       to Debezium + Kafka.         oplog CDC, schema
                        Log-based,                   evolution, DLQ
                        schema-evolution-aware, DLQ  (WIP).
                        for reliable error handling. 
  --------------------- ---------------------------- --------------------

§11 Release Notes

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/release/overview/

  **SEE ALSO**  GitHub releases:
                https://github.com/datazip-inc/olake/releases\
                GitHub (UI releases):
                https://github.com/datazip-inc/olake-ui/releases

  **LAST        Feb 2026
  UPDATED**     

  **TAGS**      release-notes · changelog · versions · new-features

  **KEY         OLake UI, Kafka connector, Oracle connector, Kubernetes
  ENTITIES**    Helm, Data Filters, offline install, performance

  **ANSWERS     What is new in the latest OLake release?\
  QUESTIONS     What version of OLake is current?\
  LIKE**        When was the Kafka connector added?

  **UPDATE      Append new entries here with each release. Full changelog
  WHEN**        at olake.io/docs/release/overview/
  ------------- ---------------------------------------------------------

Full release notes: https://olake.io/docs/release/overview/

  -------------------------- ------------ ---------------------------------
  **Milestone / Feature**    **Date       **Notes**
                             (approx)**   

  OLake UI (beta) launched   Late 2024    Web-based interface for job
                                          management, source/destination
                                          config, and sync monitoring.

  Kubernetes / Helm support  2024         Official Helm charts via
                                          datazip-inc/olake-helm.

  Oracle connector (Full     Jan 2026     526,337 RPS benchmark.
  Refresh + Incremental)                  

  Kafka connector (Consumer  Dec 2025     154,320 MPS benchmark.
  Group Streaming)                        Append-only mode.

  Data Filters feature       Nov 2025     Column-based row filtering for
                                          Full Refresh syncs.

  Offline install support    Dec 2025     Air-gapped AWS and generic
                                          environment installations.

  PostgreSQL benchmark       Jan 2026     580,113 RPS full load --- 12.5×
  update                                  faster than Fivetran.

  MongoDB benchmark update   Feb 2026     37,879 RPS full load --- 2.5×
                                          faster than Fivetran.

  7× Iceberg writer          2025         Go-side type detection, Arrow
  performance boost                       writes, improved batching.

  DLQ (Dead Letter Queue)    WIP          Will capture incompatible
  columns                                 type-change values without
                                          halting syncs.

  Oracle CDC                 WIP          Full CDC support for Oracle
                                          (currently Full Refresh +
                                          Incremental only).
  -------------------------- ------------ ---------------------------------

§12 Quick Reference

  ------------- ---------------------------------------------------------
  **DOC URL**   https://olake.io/docs/

  **TAGS**      quick-reference · summary · URLs · cheatsheet

  **KEY         source connectors, destination connectors, key URLs
  ENTITIES**    

  **ANSWERS     What sources does OLake support?\
  QUESTIONS     What destinations does OLake support?\
  LIKE**        Where is the OLake documentation?

  **UPDATE      Update URLs and connector lists when new
  WHEN**        sources/destinations are released.
  ------------- ---------------------------------------------------------

12.1 Source Connector Summary

  ------------ ------------------------------------ --------------- ------------- ---------------
  **Source**   **Doc URL**                          **Sync Modes**  **CDC         **Benchmark**
                                                                    Mechanism**   

  PostgreSQL   olake.io/docs/connectors/postgres/   FR, Inc,        pgoutput (PG  580K RPS (full)
                                                    FR+CDC, Strict  10+)          / 55K RPS (CDC)
                                                    CDC                           

  MySQL        olake.io/docs/connectors/mysql/      FR, Inc,        Binlog ROW    338K RPS (full)
                                                    FR+CDC, Strict  format        / 52K RPS (CDC)
                                                    CDC                           

  MongoDB      olake.io/docs/connectors/mongodb/    FR, Inc,        Oplog /       38K RPS (full)
                                                    FR+CDC, Strict  Change        / 11K RPS (CDC)
                                                    CDC             Streams       

  Oracle       olake.io/docs/connectors/oracle/     FR, Incremental N/A           526K RPS (full)
                                                    (CDC WIP)                     

  Kafka        olake.io/docs/connectors/kafka/      Streaming       Consumer      154K MPS
                                                    Append Only     Group         
  ------------ ------------------------------------ --------------- ------------- ---------------

12.2 Destination Summary

  ------------------ --------------------------------------------- ------------- -----------------
  **Destination**    **Doc URL**                                   **Storage**   **Notes**

  Iceberg + AWS Glue olake.io/docs/writers/iceberg/catalog/glue/   S3            Most common
                                                                                 production setup.

  Iceberg + Nessie   olake.io/docs/writers/iceberg/catalog/rest/   S3/MinIO      Git-like data
  (REST)                                                                         versioning.

  Iceberg + Polaris  olake.io/docs/writers/iceberg/catalog/rest/   S3/MinIO      OAuth2,
  (REST)                                                                         fine-grained
                                                                                 RBAC.

  Iceberg + Unity    olake.io/docs/writers/iceberg/catalog/rest/   S3            Databricks
  (REST)                                                                         managed.

  Iceberg +          olake.io/docs/writers/iceberg/catalog/rest/   S3/MinIO      Governance
  LakeKeeper                                                                     extensions.

  Iceberg + S3       olake.io/docs/writers/iceberg/catalog/rest/   S3            AWS-managed REST
  Tables                                                                         catalog.

  Iceberg + Hive     olake.io/docs/writers/iceberg/catalog/hive/   S3/MinIO      Traditional Hive
  Metastore                                                                      catalog.

  Iceberg + JDBC     olake.io/docs/writers/iceberg/catalog/jdbc/   S3/MinIO      PG or MySQL as
                                                                                 catalog.

  Parquet on S3      olake.io/docs/writers/parquet/s3/             S3            Raw Parquet, no
                                                                                 catalog.

  Parquet on GCS     olake.io/docs/writers/parquet/gcs/            GCS           Via S3-compatible
                                                                                 HMAC API.

  Parquet on MinIO   olake.io/docs/writers/parquet/s3/             MinIO         Local/on-prem S3
                                                                                 alternative.
  ------------------ --------------------------------------------- ------------- -----------------

12.3 Key URL Reference

  ------------------------------ ----------------------------------------------------------------
  **Resource**                   **URL**

  Introduction                   https://olake.io/docs/

  Benchmarks                     https://olake.io/docs/benchmarks/

  Features                       https://olake.io/docs/features/

  Install --- Docker Compose UI  https://olake.io/docs/install/olake-ui/

  Install --- Docker CLI         https://olake.io/docs/install/docker-cli/

  Install --- Kubernetes         https://olake.io/docs/install/kubernetes/

  Playground                     https://olake.io/docs/getting-started/playground/

  First Pipeline Guide           https://olake.io/docs/getting-started/creating-first-pipeline/

  PostgreSQL Connector           https://olake.io/docs/connectors/postgres/

  MySQL Connector                https://olake.io/docs/connectors/mysql/

  MongoDB Connector              https://olake.io/docs/connectors/mongodb/

  Oracle Connector               https://olake.io/docs/connectors/oracle/

  Kafka Connector                https://olake.io/docs/connectors/kafka/

  Iceberg Glue Writer            https://olake.io/docs/writers/iceberg/catalog/glue/

  Iceberg REST Writer            https://olake.io/docs/writers/iceberg/catalog/rest/

  Iceberg Hive Writer            https://olake.io/docs/writers/iceberg/catalog/hive/

  Iceberg JDBC Writer            https://olake.io/docs/writers/iceberg/catalog/jdbc/

  Iceberg Partitioning           https://olake.io/docs/writers/iceberg/partitioning/

  S3 Parquet Writer              https://olake.io/docs/writers/parquet/s3/

  GCS Parquet Writer             https://olake.io/docs/writers/parquet/gcs/

  Catalog Compatibility          https://olake.io/docs/understanding/compatibility-catalogs/

  Query Engine Compatibility     https://olake.io/docs/understanding/compatibility-engines/

  Terminologies                  https://olake.io/docs/understanding/terminologies/general/

  Architecture                   https://olake.io/docs/core/architecture/

  Use Cases                      https://olake.io/docs/core/use-cases/

  Release Notes                  https://olake.io/docs/release/overview/

  Commands & Flags               https://olake.io/docs/community/commands-and-flags/

  Contributing Guide             https://olake.io/docs/community/contributing/

  Dev Environment Setup          https://olake.io/docs/community/setting-up-a-dev-env/

  Issues & PR Guide              https://olake.io/docs/community/issues-and-prs/

  Code of Conduct                https://olake.io/docs/community/code-of-conduct/

  Slack Community                https://olake.io/slack

  GitHub (core)                  https://github.com/datazip-inc/olake

  GitHub (UI)                    https://github.com/datazip-inc/olake-ui

  GitHub (docs)                  https://github.com/datazip-inc/olake-docs

  GitHub (Helm)                  https://github.com/datazip-inc/olake-helm
  ------------------------------ ----------------------------------------------------------------

*End of OLake Comprehensive Knowledge-Base Document --- Feb 2026 ---
Source: olake.io/docs*
