# OLake RAG - Local Development Setup

This guide explains how to set up the OLake RAG system for local development using Python 3.11.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Local Python  │────▶│   Qdrant Docker  │◀────│   Local Files   │
│   3.11 venv     │     │   (Port 6333)    │     │   (qdrant_data) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
       │
       ├── RAG Service (port 7070)
       ├── Agent Service (port 8080)
       └── Tests
```

## Quick Start

### 1. Install Python 3.11

```bash
brew install python@3.11
```

### 2. Run Setup Script

```bash
./setup_local.sh
```

### 3. Start Qdrant

```bash
docker-compose up -d
```

### 4. Activate Environment

```bash
source .venv/bin/activate
```

### 5. Ingest Documents

```bash
PYTHONPATH=services/rag python services/rag/ingest_memory_efficient.py
```

### 6. Run Tests

```bash
PYTHONPATH=services/rag python -m tests.run_all
```

---

## Detailed Setup

### Prerequisites

- **Python 3.11**: `brew install python@3.11`
- **Docker**: For running Qdrant
- **uv**: Python package manager (installed automatically)

### Step 1: Create Virtual Environment

```bash
cd /Users/siddharth/code/slack-agent

# Create Python 3.11 venv
/opt/homebrew/opt/python@3.11/libexec/bin/python3.11 -m venv .venv

# Activate
source .venv/bin/activate
```

### Step 2: Install Dependencies

```bash
# Sync project dependencies
uv sync

# Install RAG-specific dependencies
uv pip install qdrant-client sentence-transformers einops fastembed
```

### Step 3: Configure Environment

Edit `.env` to use Docker Qdrant:

```bash
QDRANT_URL=http://localhost:6333
```

### Step 4: Start Qdrant

```bash
docker-compose up -d

# Verify
curl http://localhost:6333/readyz
# Should return: "all shards are ready"
```

### Step 5: Ingest Documents

```bash
PYTHONPATH=services/rag python services/rag/ingest_memory_efficient.py
```

Expected output:
```
COMPLETE: 74 documents indexed
```

---

## Running Services

### RAG Server

```bash
source .venv/bin/activate
PYTHONPATH=services/rag python -m services.rag.server
```

Access at: http://localhost:7070

### Agent Server

```bash
source .venv/bin/activate
python -m agent.main
```

Access at: http://localhost:8080

---

## Running Tests

### All Tests

```bash
PYTHONPATH=services/rag python -m tests.run_all
```

### Specific Components

```bash
# Chunker tests
PYTHONPATH=services/rag python -m tests.unit.test_chunker --stats

# Config tests
PYTHONPATH=services/rag python -m tests.unit.test_config --show

# Retriever tests (requires ingestion)
PYTHONPATH=services/rag python -m tests.unit.test_retriever --query "PostgreSQL CDC"

# Embedder tests
PYTHONPATH=services/rag python -m tests.unit.test_embedder --test-doc
```

---

## Common Commands

```bash
# Activate environment
source .venv/bin/activate

# Start Qdrant
docker-compose up -d

# Stop Qdrant
docker-compose down

# View Qdrant logs
docker-compose logs -f

# Check Qdrant status
curl http://localhost:6333/readyz

# Re-ingest documents
PYTHONPATH=services/rag python services/rag/ingest_memory_efficient.py

# Run all tests
PYTHONPATH=services/rag python -m tests.run_all
```

---

## Troubleshooting

### Python Version Error

```bash
# Check Python version
python --version  # Should be 3.11.x

# If wrong, re-activate venv
deactivate
source .venv/bin/activate
```

### Qdrant Not Starting

```bash
# Check if port is in use
lsof -i :6333

# Stop existing Qdrant
docker-compose down

# Remove old data
rm -rf qdrant_data

# Restart
docker-compose up -d
```

### Import Errors

```bash
# Make sure venv is activated
source .venv/bin/activate

# Set PYTHONPATH
export PYTHONPATH=services/rag

# Reinstall dependencies
uv pip install qdrant-client sentence-transformers einops fastembed
```

### Memory Issues

If you run into memory issues during embedding:

```bash
# Use the memory-efficient ingestion script
PYTHONPATH=services/rag python services/rag/ingest_memory_efficient.py
```

---

## Project Structure

```
slack-agent/
├── .venv/                 # Python 3.11 virtual environment
├── qdrant_data/           # Qdrant data (Docker volume)
├── services/
│   └── rag/
│       ├── chunker.py     # Document chunking
│       ├── embedder.py    # Text embeddings
│       ├── indexer.py     # Qdrant operations
│       ├── retriever.py   # Search/retrieval
│       └── server.py      # RAG API server
├── tests/
│   └── unit/
│       ├── test_chunker.py
│       ├── test_retriever.py
│       ├── test_embedder.py
│       ├── test_indexer.py
│       └── test_config.py
├── docker-compose.yml     # Qdrant only
├── .env                   # Environment variables
└── setup_local.sh         # Setup script
```

---

## Comparison: Docker vs Local

| Component | Docker | Local (Python 3.11) |
|-----------|--------|---------------------|
| Qdrant    | ✓      | ✗ (run in Docker)   |
| RAG       | ✓      | ✓ (recommended)     |
| Agent     | ✓      | ✓ (recommended)     |
| Tests     | ✓      | ✓ (faster)          |
| Ingestion | ✓      | ✓ (faster)          |

**Recommendation:** Run Qdrant in Docker, everything else locally for faster iteration.

---

## Next Steps

1. **Explore the API**: http://localhost:7070/docs
2. **Run tests**: `python -m tests.run_all`
3. **Start developing**: Modify code and test immediately
4. **Check logs**: `docker-compose logs -f qdrant`
