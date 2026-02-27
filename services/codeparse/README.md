# Incremental Code Documentation System

A modular system for monitoring GitHub repositories, parsing code changes with tree-sitter, and storing everything in Qdrant vector database with smart incremental updates.

## Features

- **Incremental Sync**: Only processes changed files using a three-level hash strategy
- **Tree-sitter Parsing**: Extracts semantic code chunks (functions, classes, imports) with rich metadata
- **Smart Reuse**: Reuses existing vectors for unchanged symbols to avoid redundant embeddings
- **One Collection Per Codebase**: Clean isolation of different repositories in Qdrant
- **SQLite Cache**: Fast local hash registry to minimize Qdrant API calls
- **Background Scheduler**: Automatic polling of GitHub repositories with configurable intervals
- **Config Hot-Reload**: Configuration changes detected and applied without restart
- **Rich Metadata**: Stores docstrings, signatures, complexity scores, and symbol relationships

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   GitHub API    │────▶│  CodeParseCache │────▶│  QdrantCodeStore│
│  (Polling)      │     │  (SQLite)       │     │  (Vectors)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  GitHubClient   │     │  HashIdentity   │     │  CodeSearcher   │
│                 │     │  (3-level hash) │     │  (Search API)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│   CodeParser    │     │ CodeSyncEngine  │
│  (tree-sitter)  │     │ (Orchestration) │
└─────────────────┘     └─────────────────┘
```

## Installation

```bash
# Install dependencies
uv sync

# Ensure Qdrant is running
docker-compose up -d
```

## Configuration

Edit `sync_config.yaml` to configure codebases:

```yaml
codebases:
  - name: myproject
    repo_url: https://github.com/owner/myproject
    branch: main
    poll_interval: 300  # seconds
    collection_name: codebase_myproject
    enabled: true

processing:
  chunk_strategies: [function_level, class_level, module_level]
  max_chunk_size: 1000
  overlap_tokens: 50

cache:
  type: sqlite
  path: ./cache/codeparse.db

qdrant:
  host: localhost
  port: 6333
  vector_size: 768
  distance: COSINE
```

## Usage

### CLI Commands

```bash
# Validate configuration
uv run python -m services.codeparse.cli validate-config

# Check system status
uv run python -m services.codeparse.cli status

# Manual sync for a specific codebase
uv run python -m services.codeparse.cli sync --codebase myproject

# Sync all enabled codebases
uv run python -m services.codeparse.cli sync --all

# Start background scheduler
uv run python -m services.codeparse.cli start

# Search code semantically
uv run python -m services.codeparse.cli search "how to authenticate" --codebase myproject

# View cache statistics
uv run python -m services.codeparse.cli cache-stats
```

### Python API

```python
from services.codeparse import (
    Config,
    CodeSyncEngine,
    CodeSearcher,
    CodeParser,
    HashIdentity,
)
from agent.embedding import embed_texts, embed_query

# Load configuration
config = Config.load("sync_config.yaml")

# Initialize sync engine
with CodeSyncEngine(config, embed_texts) as engine:
    # Sync a codebase
    codebase = config.get_codebase_by_name("myproject")
    result = engine.sync_codebase(codebase)
    print(f"Synced {result.stats.files_changed} files")

# Search code
with CodeSearcher(config, embed_query) as searcher:
    results = searcher.search_code(
        query="authentication",
        collection_name="codebase_myproject",
        top_k=5,
    )
    for result in results:
        print(f"{result.fully_qualified_name}: {result.code_text[:100]}")
        
        # Parent context is automatically populated for methods
        if result.parent_context:
            print(f"  Parent class: {result.parent_context[:100]}")

# Parse code directly
parser = CodeParser()
chunks = parser.parse_file(
    file_path="src/utils.py",
    content=open("src/utils.py").read(),
    language="python",
)
for chunk in chunks:
    print(f"{chunk.chunk_type}: {chunk.fully_qualified_name}")
```

### Context Expansion

The system provides multiple levels of context expansion:

```python
with CodeSearcher(config, embed_query) as searcher:
    results = searcher.search_code("authenticate", "codebase_myproject")
    
    for result in results:
        # 1. Parent Context (automatic for methods)
        if result.parent_context:
            print(f"Class: {result.parent_context}")
        
        # 2. File Context (on-demand)
        symbols = searcher.get_file_symbols(result.file_path, "codebase_myproject")
        
        # 3. Import Dependencies (on-demand)
        imports = searcher.get_import_context(result, "codebase_myproject")
        
        # 4. Reverse Dependencies (on-demand)
        dependents = searcher.get_reverse_dependencies(
            result.stable_symbol_key,
            "codebase_myproject",
        )
        
        # 5. Code Neighbors (on-demand)
        neighbors = searcher.get_neighbors(result, "codebase_myproject")
        
        # 6. Full Expansion (convenience method)
        expanded = searcher.expand_result_context(
            result,
            "codebase_myproject",
            expand_parent=True,
            expand_imports=True,
            expand_neighbors=True,
        )
```

See [CONTEXT_EXPANSION.md](CONTEXT_EXPANSION.md) for detailed documentation.

## Hash-Based Identity System

The system uses a three-level hash strategy for smart incremental updates:

### 1. stable_symbol_key (SHA256)
```
hash(repo_url + file_path + fully_qualified_name)
```
- **Stable semantic identity** that survives across commits
- Does NOT include `start_line` (vulnerable to line insertions)
- Does NOT include `commit_hash` (breaks cross-commit reuse)
- Used as primary lookup key for reuse decisions

### 2. content_hash (SHA256)
```
hash(entire_file_content)
```
- Detects file-level changes
- If unchanged from cache, skip entire file processing
- Fast file-level change detection

### 3. chunk_hash (SHA256)
```
hash(normalized_symbol_source)
```
- Detects actual code changes within a symbol
- Normalized whitespace for stability
- If unchanged, reuse existing vector (NO re-embedding)

### Smart Reuse Logic

```
For each file in changed commit:

1. Check content_hash in local cache
   - If match → skip entire file (nothing changed)
   - If mismatch → proceed to symbol-level check

2. Parse file with tree-sitter, extract symbols/chunks

3. For each symbol:
   stable_key = hash(repo_url + file_path + fully_qualified_name)
   chunk_hash = hash(normalized_symbol_source)
   
   if stable_key exists in symbol_registry:
       if chunk_hash matches cached_chunk_hash:
           reuse vector_id (NO Qdrant operation)
       else:
           code changed → re-embed + upsert to Qdrant
   else:
       new symbol → embed + upsert to Qdrant

4. Detect deletions:
   - Compare current file's stable_keys with cached stable_keys
   - Deleted stable_keys → remove from Qdrant
```

## Chunking Strategy

### Function/Method Level (Primary)
- Complete function signature + docstring + body
- Never breaks mid-sentence
- Includes 50-token overlap from parent class context if method

### Class Level (Secondary)
- Full class if under 1000 tokens
- Otherwise split into methods, include class docstring with each

### Module Level (Tertiary)
- Imports block (complete import section)
- Constants block
- Module-level code sections

## Rich Metadata Extraction

For each chunk, the system extracts:

| Field | Description |
|-------|-------------|
| `stable_symbol_key` | Semantic identity hash |
| `fully_qualified_name` | Complete symbol path (e.g., `MyClass.my_method`) |
| `chunk_type` | function/class/import/module |
| `signature` | Function/class signature |
| `file_path` | Path within repository |
| `language` | Programming language |
| `start_line`, `end_line` | Location in file (metadata only) |
| `repo_url`, `commit_hash` | Source tracking |
| `code_text` | Actual source code |
| `chunk_hash`, `content_hash` | Change detection |
| `parent_symbols` | Class hierarchy |
| `imports` | Import statements |
| `docstring` | Documentation |
| `complexity_score` | Cyclomatic complexity |

## Supported Languages

- Python (full support)
- JavaScript (full support)
- TypeScript (full support)
- Go (full support)
- Rust (partial - requires tree-sitter-rust)
- Java (partial - requires tree-sitter-java)
- Ruby (partial - requires tree-sitter-ruby)

## Performance Optimizations

- **Batch Operations**: Upsert chunks to Qdrant in batches of 100
- **Parallel Processing**: Process multiple files concurrently (configurable thread pool)
- **Cache Warming**: Pre-load registries on startup
- **Lazy Parsing**: Only download/parse files with changed content_hash
- **Payload Indexes**: Qdrant indexes on file_path, commit_hash, language, chunk_type

## Error Handling

- **GitHub Rate Limits**: Exponential backoff, automatic retry
- **Parse Failures**: Fallback to file-level chunking
- **Network Errors**: Retry 3x with delays
- **Transaction Safety**: Only update cache after successful processing
- **Cache Corruption**: Auto-rebuild from Qdrant if inconsistent

## Monitoring

```bash
# Check system health
uv run python -m services.codeparse.cli status

# View scheduler job statuses (when running)
# Access via Python API:
from services.codeparse import create_scheduler
scheduler = create_scheduler()
print(scheduler.get_job_statuses())
```

## Project Structure

```
services/codeparse/
├── __init__.py          # Module exports
├── config.py            # Configuration management
├── cache.py             # SQLite cache layer
├── hasher.py            # Hash-based identity system
├── github_client.py     # GitHub API client
├── parser.py            # Tree-sitter parser
├── qdrant_client.py     # Qdrant vector store
├── sync.py              # Sync engine (orchestration)
├── search.py            # Search and retrieval
├── scheduler.py         # Background scheduler
├── utils.py             # Utilities (logging, errors, retry)
└── cli.py               # CLI interface
```

## Testing

```bash
# Run tests
uv run pytest tests/test_codeparse.py -v
```

## Troubleshooting

### Qdrant Connection Issues
```bash
# Check Qdrant is running
docker-compose ps

# View Qdrant logs
docker-compose logs -f qdrant
```

### Cache Issues
```bash
# Clear cache for a repo
uv run python -m services.codeparse.cli cache-clear --repo https://github.com/owner/repo

# Clear entire cache
uv run python -m services.codeparse.cli cache-clear --all
```

### Parser Issues
```bash
# Check tree-sitter languages
uv run python -c "from services.codeparse import CodeParser; p = CodeParser(); print(p._languages.keys())"
```

## License

MIT
