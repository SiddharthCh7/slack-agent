## 1. Project Context & Background

### 1.1 What is OLake?
OLake (`olake.io`) is a **blazing-fast, open-source EL (Extract–Load) framework**, written entirely in Go for memory efficiency and high throughput. It replicates data from operational databases directly into **Apache Iceberg** and Parquet — giving teams a simple, vendor lock-in-free path to building a modern data lakehouse.

### 1.2 Key Product Facts (use these to inform every comment the agent writes)
| Attribute | Detail |
|---|---|
| **What it does** | Replicates databases → Apache Iceberg / Parquet in real time |
| **How it works** | Full Refresh, Incremental Sync, and Change Data Capture (CDC) via native DB logs (pgoutput, binlogs, oplogs) |
| **Supported sources** | PostgreSQL, MySQL, MongoDB, Oracle, Kafka |
| **Supported destinations** | Apache Iceberg (AWS Glue, REST Catalog / Nessie / Polaris / Unity, Hive Metastore, JDBC Catalog), S3 Parquet (MinIO, S3, GCS) |
| **Query-engine ready** | Athena, Trino, Spark, Flink, Presto, Hive, Snowflake |
| **Benchmark claim** | Up to 5–500× faster ingest than common alternatives |
| **Key differentiator** | No intermediate formats, no complex Debezium+Kafka+Spark pipelines — direct-to-Iceberg with exactly-once semantics |
| **Open-source repo** | `github.com/datazip-inc/olake` |
| **Tagline** | *"Fastest open-source tool for replicating databases to Apache Iceberg"* |

### 1.3 OLake LinkedIn Page
`linkedin.com/company/datazipio`
