# OLake RAG Ingestion Scripts

Robust, memory-efficient document ingestion for OLake documentation into Qdrant vector database.

## Features

- **Memory-efficient batch processing**: Processes documents in configurable batch sizes with GC hints to prevent memory exhaustion
- **Checkpoint-based crash recovery**: Automatically resumes from last successful batch on interruption
- **Progress tracking with ETA**: Real-time progress reporting including estimated completion time
- **Retry logic with exponential backoff**: Handles transient Qdrant/network errors gracefully
- **Comprehensive logging**: Logs to both console and file with configurable log levels
- **Data validation**: Validates chunks and embeddings before ingestion
- **Sparse vector support**: Generates BM25 sparse vectors for hybrid search (optional)
- **Dry-run mode**: Validate and parse documents without upserting to Qdrant

## Quick Start

### 1. Clear existing data (optional)

```bash
# List current collections
python clear_qdrant.py --list

# Clear both collections (with confirmation)
python clear_qdrant.py

# Clear without confirmation
python clear_qdrant.py --yes

# Clear only docs collection
python clear_qdrant.py --collection docs --yes
```

### 2. Ingest documentation

```bash
# Full ingestion with reset (recommended for fresh start)
python ingest_docs.py --reset

# Resume from checkpoint (if previous run was interrupted)
python ingest_docs.py

# Ingest only docs collection
python ingest_docs.py --collection docs

# Ingest only code collection
python ingest_docs.py --collection code

# Dry run (validate only, no upsert)
python ingest_docs.py --dry-run
```

## Usage

### ingest_docs.py

```bash
python ingest_docs.py [OPTIONS]

Options:
  --path, -p PATH       Path to documentation file (default: ./docs/olake_docs.md)
  --collection, -c      Which collection(s) to ingest: docs|code|both (default: both)
  --reset, -r           Drop and recreate collections before ingesting
  --dry-run, -n         Validate and parse only, don't upsert to Qdrant
  --batch-size, -b N    Batch size for embedding and upsert (default: 32)
  --log-level, -l LVL   Logging level: DEBUG|INFO|WARNING|ERROR (default: INFO)
  --help, -h            Show help message
```

### clear_qdrant.py

```bash
python clear_qdrant.py [OPTIONS]

Options:
  --collection, -c      Which collection(s) to clear: docs|code|both (default: both)
  --list, -l            List all collections without deleting
  --yes, -y             Skip confirmation prompt
  --help, -h            Show help message
```

## Environment Variables

Configure ingestion behavior via environment variables:

```bash
# Ingestion settings
export INGEST_BATCH_SIZE=32              # Batch size for embedding/upsert
export INGEST_MAX_RETRIES=3              # Max retry attempts per batch
export INGEST_MEMORY_THRESHOLD_MB=2048   # Memory threshold for GC triggers
export INGEST_CHECKPOINT_INTERVAL=10     # Save checkpoint every N batches
export INGEST_LOG_FILE=./ingest.log      # Log file path
export CHECKPOINT_DIR=./.ingest_checkpoints  # Checkpoint storage directory

# Qdrant settings
export QDRANT_URL=./qdrant_db            # Local path or HTTP URL
export QDRANT_API_KEY=xxx                # Required for Qdrant Cloud

# Collection names
export DOCS_COLLECTION=olake_docs        # Docs collection name
export CODE_COLLECTION=olake_code        # Code collection name

# Sparse vectors
export DISABLE_SPARSE_VECTORS=           # Set to "1" to disable sparse vectors
```

## Checkpoint Recovery

The ingestion script automatically saves checkpoints every N batches (configurable via `INGEST_CHECKPOINT_INTERVAL`). If the process is interrupted:

1. **Automatic resume**: Simply re-run the same command without `--reset`
2. **Checkpoint location**: Stored in `./.ingest_checkpoints/` directory
3. **Manual cleanup**: Delete checkpoint files to force full re-ingestion

Example:
```bash
# First run (interrupted at 50%)
python ingest_docs.py --reset

# Resume from checkpoint
python ingest_docs.py  # Automatically resumes from last checkpoint

# Force full re-ingestion (ignore checkpoint)
python ingest_docs.py --reset
```

## Logging

Logs are written to:
- **Console**: Real-time progress and status updates
- **File**: `./ingest.log` (configurable via `INGEST_LOG_FILE`)

Log levels:
- `DEBUG`: Detailed technical information for troubleshooting
- `INFO`: Normal operation messages (default)
- `WARNING`: Non-critical issues
- `ERROR`: Critical errors that may cause failure

Example log output:
```
2026-02-22 10:30:15 [INFO] Starting ingestion from ./docs/olake_docs.md
2026-02-22 10:30:15 [INFO] Target: both collection(s)
2026-02-22 10:30:15 [INFO] Reset: True, Dry run: False
2026-02-22 10:30:16 [INFO] Parsing document...
2026-02-22 10:30:18 [INFO] Parsed 450 total chunks
2026-02-22 10:30:18 [INFO]   Docs chunks: 380
2026-02-22 10:30:18 [INFO]   Code chunks: 70
2026-02-22 10:30:18 [INFO] Initializing collections...
2026-02-22 10:30:19 [INFO]   Reset collection: olake_docs
2026-02-22 10:30:20 [INFO]   Reset collection: olake_code
2026-02-22 10:30:21 [INFO] [olake_docs] Progress: 128/380 (33.7%) | Elapsed: 0:01:23 | Rate: 1.5 items/s | ETA: 0:02:50
```

## Performance Tuning

### Memory Optimization

For large documents or limited RAM:

```bash
# Reduce batch size
export INGEST_BATCH_SIZE=16

# Lower memory threshold to trigger GC more frequently
export INGEST_MEMORY_THRESHOLD_MB=1024
```

### Speed Optimization

For faster ingestion on powerful hardware:

```bash
# Increase batch size (uses more RAM)
export INGEST_BATCH_SIZE=64

# Reduce checkpoint frequency
export INGEST_CHECKPOINT_INTERVAL=20
```

### GPU Acceleration

If you have a CUDA-compatible GPU:

```bash
export EMBED_DEVICE=cuda
export EMBED_BATCH_SIZE=128
```

## Troubleshooting

### Out of Memory Errors

```bash
# Reduce batch size and memory threshold
export INGEST_BATCH_SIZE=8
export INGEST_MEMORY_THRESHOLD_MB=512
python ingest_docs.py --reset
```

### Qdrant Connection Errors

```bash
# Verify Qdrant URL
export QDRANT_URL=./qdrant_db  # For local file persistence
# or
export QDRANT_URL=http://localhost:6333  # For Docker

# Retry ingestion (checkpoint will resume)
python ingest_docs.py
```

### Slow Ingestion

```bash
# Check if sparse vectors are enabled (adds ~10% overhead)
# Disable if not needed:
export DISABLE_SPARSE_VECTORS=1

# Increase batch size
export INGEST_BATCH_SIZE=64
```

### Corrupted Checkpoint

```bash
# Delete checkpoint files
rm -rf ./.ingest_checkpoints/*

# Re-run with reset
python ingest_docs.py --reset
```

## Data Validation

The ingestion script validates:

1. **Chunk structure**: Ensures required fields (text, chunk_id, chunk_type) exist
2. **Text length**: Rejects chunks > 100KB to prevent embedding failures
3. **Chunk ID format**: Validates hex string format
4. **Embedding dimensions**: Ensures vectors match model output dimension
5. **Numeric validity**: Checks for NaN/Inf in embedding values

Invalid chunks are logged and skipped, allowing ingestion to continue.

## Monitoring

### Check Progress

The script reports progress every 15 seconds:

```
[olake_docs] Progress: 256/380 (67.4%) | Elapsed: 0:02:45 | Rate: 1.6 items/s | ETA: 0:01:32
```

### Check Qdrant Collections

```bash
# List collections and point counts
python clear_qdrant.py --list
```

### View Logs

```bash
# Real-time log tailing
tail -f ./ingest.log

# Search for errors
grep ERROR ./ingest.log
```

## Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Source Docs    │────▶│   Chunking   │────▶│  Embedding  │
│  (Markdown)     │     │  (H2-based)  │     │  (nomic-ai) │
└─────────────────┘     └──────────────┘     └─────────────┘
                                                      │
                                                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│  Qdrant DB      │◀────│   Upsert     │◀────│  Sparse     │
│  (Collections)  │     │  (Batched)   │     │  (BM25)     │
└─────────────────┘     └──────────────┘     └─────────────┘
         │
         ▼
┌─────────────────┐
│  Checkpoint     │
│  (Recovery)     │
└─────────────────┘
```

## File Structure

```
services/rag/
├── ingest_docs.py          # Main ingestion script
├── clear_qdrant.py         # Collection management utility
├── ingest_utils.py         # Shared utilities (checkpoint, progress, retry)
├── chunker.py              # Document chunking logic
├── embedder.py             # Embedding model wrapper
├── indexer.py              # Qdrant index management
├── retriever.py            # Search and retrieval
└── docs/
    └── olake_docs.md       # Source documentation
```

## Best Practices

1. **Always use `--reset` for fresh ingestion**: Ensures clean state
2. **Monitor memory usage**: Adjust batch size if memory pressure occurs
3. **Keep checkpoints enabled**: Allows crash recovery without data loss
4. **Review logs regularly**: Catch issues early
5. **Test with `--dry-run` first**: Validate parsing before upserting
6. **Schedule during low-traffic periods**: Ingestion can take time for large docs

## Example Workflows

### Daily Incremental Update

```bash
# Without reset, resumes from checkpoint if interrupted
python ingest_docs.py --collection docs
```

### Full Rebuild

```bash
# Complete rebuild with fresh data
python clear_qdrant.py --yes
python ingest_docs.py --reset
```

### CI/CD Pipeline

```bash
# Non-interactive, dry-run validation
python ingest_docs.py --dry-run --batch-size 16 --log-level WARNING

# If successful, run actual ingestion
if [ $? -eq 0 ]; then
    python ingest_docs.py --reset --batch-size 32
fi
```

### Large Document Handling

```bash
# Conservative settings for large docs
export INGEST_BATCH_SIZE=8
export INGEST_MEMORY_THRESHOLD_MB=512
export INGEST_CHECKPOINT_INTERVAL=5
python ingest_docs.py --reset
```
