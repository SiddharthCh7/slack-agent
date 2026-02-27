# 🚀 Quick Start - Code Documentation System

## One-Liner Start

```bash
# Start Qdrant + Sync + Search in 3 commands
docker-compose up -d && \
uv run python -m services.codeparse.cli sync --codebase myproject --verbose && \
uv run python -m services.codeparse.cli search "your query" --codebase myproject
```

---

## Essential Commands

### 1️⃣ Start Qdrant (Required First Step)
```bash
docker-compose up -d
```

### 2️⃣ Check Everything is Working
```bash
uv run python -m services.codeparse.cli status
```

### 3️⃣ Sync Your Code
```bash
# Sync specific repo
uv run python -m services.codeparse.cli sync --codebase myproject --verbose

# Sync all repos
uv run python -m services.codeparse.cli sync --all --verbose
```

### 4️⃣ Search Your Code
```bash
uv run python -m services.codeparse.cli search "authentication" --codebase myproject
```

---

## Logging Flags

| Flag | What You See | When to Use |
|------|--------------|-------------|
| *(none)* | Just results | Normal operation |
| `--verbose` | Each file processed | Debugging sync |
| `--debug` | Every single operation | Deep debugging |

```bash
# Examples
uv run python -m services.codeparse.cli sync --codebase myproject           # Clean output
uv run python -m services.codeparse.cli sync --codebase myproject -v       # Show files
uv run python -m services.codeparse.cli sync --codebase myproject --debug  # Show everything
```

---

## Pretty Terminal Output

### Status Command
```
╭──────────────────────────────────────────────────────────────────╮
│ Code Documentation System Status                                 │
╰──────────────────────────────────────────────────────────────────╯

Health Checks
  ✓ Qdrant (localhost:6333): Qdrant is ready
  ✓ GitHub API: GitHub API is reachable
  ✓ Cache (./cache/codeparse.db): Cache database is accessible
```

### Search Command
```
Found 3 results in myproject

╭──────────────────────────────────────────────────────────────────╮
│ Result 1                                                         │
├──────────────────────────────────────────────────────────────────┤
│ MyClass.authenticate                                             │
│ File: src/auth.py:45-67                                          │
│ Type: method | Language: python | Score: 0.892                   │
│                                                                  │
│ def authenticate(self, token):                                   │
│     """Authenticate user with token."""                          │
│     ...                                                          │
╰──────────────────────────────────────────────────────────────────╯
```

### Sync Command (Verbose)
```
2026-02-25 22:00:00 | INFO | sync:sync_codebase | Starting sync for myproject
2026-02-25 22:00:01 | INFO | sync:sync_codebase | New commit detected
2026-02-25 22:00:02 | INFO | sync:_process_file | Processing 15 code files
2026-02-25 22:00:10 | INFO | qdrant:upsert_points | Upserted 12 vectors
2026-02-25 22:00:11 | INFO | sync:sync_codebase | Sync completed

╭──────────────────────────────────────────────────────────────────╮
│ Sync Results                                                     │
├──────────────────────────────────────────────────────────────────┤
│ Files checked: 15                                                │
│ Files changed: 5                                                 │
│ Vectors upserted: 12                                             │
│ Duration: 11.23s                                                 │
╰──────────────────────────────────────────────────────────────────╯
```

---

## Common Workflows

### Workflow 1: First Time Setup
```bash
docker-compose up -d                           # Start Qdrant
uv sync                                        # Install deps
uv run python -m services.codeparse.cli status # Verify
uv run python -m services.codeparse.cli sync --all --verbose  # Initial sync
```

### Workflow 2: Daily Use
```bash
# Check status
uv run python -m services.codeparse.cli status

# Search for code
uv run python -m services.codeparse.cli search "database connection"

# If needed, manual sync
uv run python -m services.codeparse.cli sync --all
```

### Workflow 3: Debugging
```bash
# Clear everything
uv run python -m services.codeparse.cli cache-clear --all --force

# Resync with maximum logging
uv run python -m services.codeparse.cli sync --codebase myproject --debug

# Watch logs in real-time
tail -f logs/codeparse.log
```

---

## Log Files

```bash
# View latest logs
tail -20 logs/codeparse.log

# Follow logs in real-time
tail -f logs/codeparse.log

# Search for errors
grep ERROR logs/codeparse.log

# Search for specific operation
grep "Processing file" logs/codeparse.log
```

---

## Troubleshooting

### Qdrant Not Starting
```bash
docker-compose down
docker-compose up -d
docker-compose logs qdrant
```

### Sync Failing
```bash
# Check GitHub connectivity
uv run python -m services.codeparse.cli status

# Clear cache and retry
uv run python -m services.codeparse.cli cache-clear --all --force
uv run python -m services.codeparse.cli sync --all --verbose
```

### Search Returning Nothing
```bash
# Check if data exists
uv run python -m services.codeparse.cli cache-stats

# If empty, sync first
uv run python -m services.codeparse.cli sync --all
```

---

## Python API Quick Start

```python
from services.codeparse import Config, CodeSearcher, CodeSyncEngine
from agent.embedding import embed_texts, embed_query

# Load config
config = Config.load("sync_config.yaml")

# Sync
with CodeSyncEngine(config, embed_texts) as engine:
    cb = config.get_codebase_by_name("myproject")
    result = engine.sync_codebase(cb)
    print(f"Synced {result.stats.files_changed} files")

# Search
with CodeSearcher(config, embed_query) as searcher:
    results = searcher.search_code("auth", "codebase_myproject")
    for r in results:
        print(f"{r.fully_qualified_name}: {r.code_text[:100]}")
```

---

## Need Help?

```bash
# Show all commands
uv run python -m services.codeparse.cli --help

# Help for specific command
uv run python -m services.codeparse.cli sync --help
uv run python -m services.codeparse.cli search --help
```

---

## Full Documentation

- [STARTUP_GUIDE.md](STARTUP_GUIDE.md) - Complete startup guide
- [services/codeparse/README.md](services/codeparse/README.md) - API docs
- [services/codeparse/CONTEXT_EXPANSION.md](services/codeparse/CONTEXT_EXPANSION.md) - Context system
