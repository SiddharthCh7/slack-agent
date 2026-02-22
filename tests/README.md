# RAG Unit Tests

Comprehensive unit tests for the OLake RAG (Retrieval-Augmented Generation) components with CLI output.

## Quick Start

```bash
# Run all tests
python -m tests.run_all

# Run specific component tests
python -m tests.run_all chunker
python -m tests.run_all retriever
python -m tests.run_all embedder
python -m tests.run_all indexer
python -m tests.run_all config

# Run multiple components
python -m tests.run_all chunker config
```

## Test Components

### 1. Chunker Tests (`tests/unit/test_chunker.py`)

Tests the document chunking strategy with pretty-printed output.

```bash
# Show chunk statistics
python -m tests.unit.test_chunker --stats

# Show first chunk detail
python -m tests.unit.test_chunker --first

# Show §4.1.3 variant sub-chunks
python -m tests.unit.test_chunker --variants

# Show glossary terms
python -m tests.unit.test_chunker --glossary

# Show §12 summary chunks
python -m tests.unit.test_chunker --summary

# Search chunks by keyword
python -m tests.unit.test_chunker --search CDC

# Verify overlap between chunks
python -m tests.unit.test_chunker --overlap
```

### 2. Retriever Tests (`tests/unit/test_retriever.py`)

Tests document and code retrieval with query examples.

```bash
# Search with a query
python -m tests.unit.test_retriever --query "How do I configure PostgreSQL CDC?"

# Search with custom top-k
python -m tests.unit.test_retriever --query "PostgreSQL setup" --top-k 5

# Test hybrid search (docs + code)
python -m tests.unit.test_retriever --query "docker compose" --hybrid

# Filter by connector
python -m tests.unit.test_retriever --query "CDC" --filter-connector postgres

# Test summary filtering logic
python -m tests.unit.test_retriever --summary-filter

# Test multi-query search
python -m tests.unit.test_retriever --multi-query
```

### 3. Embedder Tests (`tests/unit/test_embedder.py`)

Tests embedding model loading and vector generation.

```bash
# Test document embedding
python -m tests.unit.test_embedder --test-doc

# Test query embedding
python -m tests.unit.test_embedder --test-query

# Test sparse (BM25) embedding
python -m tests.unit.test_embedder --test-sparse

# Test batch embedding performance
python -m tests.unit.test_embedder --batch

# Test cosine similarity calculation
python -m tests.unit.test_embedder --similarity

# Test prefix handling (document vs query)
python -m tests.unit.test_embedder --prefix
```

### 4. Indexer Tests (`tests/unit/test_indexer.py`)

Tests Qdrant collection management and chunk operations.

```bash
# List all collections
python -m tests.unit.test_indexer --collections

# Show collection statistics
python -m tests.unit.test_indexer --stats

# Create test collection
python -m tests.unit.test_indexer --create

# Test upsert chunk
python -m tests.unit.test_indexer --upsert

# Test get chunk by ID
python -m tests.unit.test_indexer --get

# Test collection schema detection
python -m tests.unit.test_indexer --schema
```

### 5. Config Tests (`tests/unit/test_config.py`)

Tests configuration values and validation.

```bash
# Show all configuration values
python -m tests.unit.test_config --show

# Validate configuration
python -m tests.unit.test_config --validate

# Check environment variables
python -m tests.unit.test_config --env

# Test chunking configuration
python -m tests.unit.test_config --chunking

# Test retrieval configuration
python -m tests.unit.test_config --retrieval
```

## Output Format

All tests produce formatted CLI output with:

- **Headers**: Clear section separators
- **Statistics**: Bar charts and percentages
- **Previews**: Content snippets with context
- **Validation**: Pass/fail indicators (✓/✗)
- **Search Results**: Ranked with scores and highlights

### Example Output

```
======================================================================
  CHUNK STATISTICS
======================================================================

--- By Chunk Type ---
  metadata       1 
  prose         70 ███████████████████████████████████
  summary        3 █

--- By H1 Section ---
  §4 Source Connectors                      20 chunks
  §3 OLake Features                         14 chunks
  ...

--- Metadata Coverage ---
  With DOC URL:      74 / 74 (100%)
  With Tags:          0 / 74 (  0%)
```

## Test Structure

```
tests/
├── __init__.py
├── run_all.py              # Unified test runner
└── unit/
    ├── __init__.py
    ├── test_chunker.py     # Chunking tests
    ├── test_retriever.py   # Retrieval tests
    ├── test_embedder.py    # Embedding tests
    ├── test_indexer.py     # Index/Qdrant tests
    └── test_config.py      # Configuration tests
```

## Requirements

- Python 3.11+ (Note: Python 3.14 has embedding library compatibility issues)
- Dependencies from `pyproject.toml`
- Qdrant running (for indexer/retriever tests)
- `.env` file configured (optional, uses defaults)

## Known Issues

### Python 3.14 Embedding Compatibility

The embedding libraries (sentence-transformers, transformers) have compatibility issues with Python 3.14 that cause segmentation faults during batch processing.

**Affected operations:**
- Document ingestion (`ingest_docs.py`)
- Embedder tests that require model loading

**Workarounds:**
1. Use Docker for ingestion: `docker-compose exec rag python ingest_docs.py`
2. Use Python 3.11 environment for embedding operations
3. Run chunking/config tests which don't require embedding

**Tests that work on Python 3.14:**
- `test_chunker.py` - All tests ✓
- `test_config.py` - All tests ✓
- `test_indexer.py` - Collection management tests ✓

**Tests requiring Python 3.11:**
- `test_retriever.py` - Needs populated index
- `test_embedder.py` - Model loading crashes

## Environment Variables

Tests respect environment variables from `.env`:

```bash
# Chunking
MAX_CHUNK_CHARS=2500
OVERLAP_CHARS=400

# Retrieval
DOC_RELEVANCE_THRESHOLD=0.35
MAX_RETRIEVED_DOCS=6

# Qdrant
QDRANT_URL=./qdrant_db
DOCS_COLLECTION=olake_docs
CODE_COLLECTION=olake_code
```

## Troubleshooting

### Import Errors

If you see `ModuleNotFoundError`, ensure you're running from the project root:

```bash
cd /path/to/slack-agent
python -m tests.run_all
```

### Qdrant Connection Errors

For indexer/retriever tests, ensure Qdrant is running:

```bash
# Local file storage
QDRANT_URL=./qdrant_db

# Or Docker
docker-compose up -d qdrant
```

### Embedding Model Download

First run will download the embedding model (~100MB):

```
nomic-ai/nomic-embed-text-v1.5
```

Subsequent runs use the cached model.
