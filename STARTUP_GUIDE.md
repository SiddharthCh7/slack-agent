# 🚀 Code Documentation System - Startup Guide

## Quick Start

### 1. Start Qdrant (Required)

```bash
# Start Qdrant vector database in Docker
docker-compose up -d

# Verify Qdrant is running
docker-compose ps

# View Qdrant logs
docker-compose logs -f qdrant
```

### 2. Install Dependencies

```bash
# Install all dependencies
uv sync

# Verify installation
uv run python -c "from services.codeparse import Config; print('✓ Dependencies OK')"
```

### 3. Configure the System

Edit `sync_config.yaml` to add your repositories:

```yaml
codebases:
  - name: myproject
    repo_url: https://github.com/your-username/your-repo
    branch: main
    poll_interval: 300  # 5 minutes
    collection_name: codebase_myproject
    enabled: true
```

### 4. Validate Configuration

```bash
uv run python -m services.codeparse.cli validate-config
```

---

## 📋 All Available Commands

### System Status

```bash
# Check system health and status
uv run python -m services.codeparse.cli status

# With verbose output
uv run python -m services.codeparse.cli status --verbose
```

### Manual Sync

```bash
# Sync a specific codebase
uv run python -m services.codeparse.cli sync --codebase myproject

# Sync all enabled codebases
uv run python -m services.codeparse.cli sync --all

# With verbose logging (detailed terminal output)
uv run python -m services.codeparse.cli sync --codebase myproject --verbose

# With debug logging (most detailed)
uv run python -m services.codeparse.cli sync --codebase myproject --debug
```

### Start Background Scheduler

```bash
# Start scheduler (monitors repos continuously)
uv run python -m services.codeparse.cli start

# With verbose logging
uv run python -m services.codeparse.cli start --verbose

# With debug logging (shows every operation)
uv run python -m services.codeparse.cli start --debug
```

### Search Code

```bash
# Search for code
uv run python -m services.codeparse.cli search "authentication function"

# Search in specific codebase
uv run python -m services.codeparse.cli search "authenticate" --codebase myproject

# Get more results
uv run python -m services.codeparse.cli search "auth" --codebase myproject --top-k 10

# Filter by language
uv run python -m services.codeparse.cli search "database" --codebase myproject --language python

# Filter by chunk type (function, class, import)
uv run python -m services.codeparse.cli search "MyClass" --codebase myproject --type class
```

### Cache Management

```bash
# View cache statistics
uv run python -m services.codeparse.cli cache-stats

# Clear cache for specific repo
uv run python -m services.codeparse.cli cache-clear --repo https://github.com/owner/repo

# Clear entire cache (requires confirmation)
uv run python -m services.codeparse.cli cache-clear --all

# Force clear without confirmation
uv run python -m services.codeparse.cli cache-clear --all --force
```

### Configuration

```bash
# Validate configuration file
uv run python -m services.codeparse.cli validate-config
```

---

## 📝 Logging Options

### Logging Levels

| Flag | Level | Description |
|------|-------|-------------|
| (none) | INFO | Standard operation messages |
| `--verbose` | DEBUG | Detailed operation messages |
| `--debug` | DEBUG + module names | Most detailed with module:function |

### Examples

```bash
# Standard logging (clean output)
uv run python -m services.codeparse.cli sync --codebase myproject

# Verbose (shows each file being processed)
uv run python -m services.codeparse.cli sync --codebase myproject --verbose

# Debug (shows every operation with module names)
uv run python -m services.codeparse.cli sync --codebase myproject --debug
```

### Log Files

All logs are written to:
- `logs/codeparse.log` - Main log file (rotates at 50MB)
- Old logs are compressed and kept (5 backups)

View logs in real-time:
```bash
# Follow logs
tail -f logs/codeparse.log

# Search logs
grep "ERROR" logs/codeparse.log
```

---

## 🔧 Complete Workflow Examples

### Example 1: Initial Setup and Sync

```bash
# 1. Start Qdrant
docker-compose up -d

# 2. Verify Qdrant is running
uv run python -m services.codeparse.cli status

# 3. Validate configuration
uv run python -m services.codeparse.cli validate-config

# 4. Initial sync (with detailed logging)
uv run python -m services.codeparse.cli sync --codebase myproject --verbose

# 5. Check results
uv run python -m services.codeparse.cli cache-stats
```

### Example 2: Start Continuous Monitoring

```bash
# Start scheduler with verbose logging
uv run python -m services.codeparse.cli start --verbose

# In another terminal, check status
uv run python -m services.codeparse.cli status
```

### Example 3: Search and Explore

```bash
# Search for authentication code
uv run python -m services.codeparse.cli search "authenticate user" --codebase myproject

# Search for a specific class
uv run python -m services.codeparse.cli search "MyClass" --codebase myproject --type class

# Search for functions in a specific file
uv run python -m services.codeparse.cli search "database" --codebase myproject --language python
```

### Example 4: Debugging Issues

```bash
# Clear cache and resync
uv run python -m services.codeparse.cli cache-clear --all --force
uv run python -m services.codeparse.cli sync --codebase myproject --debug

# Check detailed logs
tail -f logs/codeparse.log | grep ERROR
```

---

## 🎯 Python API Usage

### Sync Programmatically

```python
from services.codeparse import Config, CodeSyncEngine
from agent.embedding import embed_texts

# Load configuration
config = Config.load("sync_config.yaml")

# Initialize sync engine
with CodeSyncEngine(config, embed_texts) as engine:
    # Sync a codebase
    codebase = config.get_codebase_by_name("myproject")
    result = engine.sync_codebase(codebase)
    
    # Print results
    print(f"Files changed: {result.stats.files_changed}")
    print(f"Vectors upserted: {result.stats.vectors_upserted}")
```

### Search Programmatically

```python
from services.codeparse import Config, CodeSearcher
from agent.embedding import embed_query

config = Config.load("sync_config.yaml")

with CodeSearcher(config, embed_query) as searcher:
    results = searcher.search_code(
        query="authentication",
        collection_name="codebase_myproject",
        top_k=5,
    )
    
    for result in results:
        print(f"Match: {result.fully_qualified_name}")
        print(f"Code: {result.code_text[:200]}")
        
        # Auto-expanded context
        if result.parent_context:
            print(f"Parent: {result.parent_context[:100]}")
        if result.siblings_context:
            print(f"Siblings: {result.siblings_context[:100]}")
```

### Start Scheduler Programmatically

```python
from services.codeparse import create_scheduler
from agent.embedding import embed_texts

# Create and start scheduler
scheduler = create_scheduler(
    config_path="sync_config.yaml",
    embed_fn=embed_texts,
)

scheduler.start()
scheduler.wait()  # Blocks until stopped
```

---

## 🐛 Troubleshooting

### Qdrant Connection Issues

```bash
# Check if Qdrant is running
docker-compose ps

# Restart Qdrant
docker-compose down
docker-compose up -d

# Check Qdrant logs
docker-compose logs qdrant
```

### Cache Issues

```bash
# View cache statistics
uv run python -m services.codeparse.cli cache-stats

# Clear cache and resync
uv run python -m services.codeparse.cli cache-clear --all --force
uv run python -m services.codeparse.cli sync --all --verbose
```

### Configuration Issues

```bash
# Validate configuration
uv run python -m services.codeparse.cli validate-config

# Check config file syntax
cat sync_config.yaml | python -c "import yaml, sys; yaml.safe_load(sys.stdin); print('✓ Valid YAML')"
```

### Logging Issues

```bash
# Check if log directory exists
ls -la logs/

# Create if missing
mkdir -p logs

# Check log file permissions
chmod 644 logs/codeparse.log
```

---

## 📊 Monitoring

### Real-time Monitoring

```bash
# Watch sync operations in real-time
tail -f logs/codeparse.log | grep -E "INFO|ERROR"

# Watch only errors
tail -f logs/codeparse.log | grep ERROR

# Watch file processing
tail -f logs/codeparse.log | grep "Processing file"
```

### System Health

```bash
# Full status check
uv run python -m services.codeparse.cli status

# Check individual components
uv run python -c "
from services.codeparse.utils import check_qdrant_health, check_github_connectivity, check_cache_health
from services.codeparse import Config

config = Config.load('sync_config.yaml')

print('Qdrant:', check_qdrant_health(config.qdrant.host, config.qdrant.port))
print('GitHub:', check_github_connectivity())
print('Cache:', check_cache_health(config.cache.path))
"
```

---

## 🎨 Pretty Output Examples

### Status Command Output
```
╭──────────────────────────────────────────────────────────────────╮
│ Code Documentation System Status                                 │
╰──────────────────────────────────────────────────────────────────╯

Health Checks
  ✓ Qdrant (localhost:6333): Qdrant is ready
  ✓ GitHub API: GitHub API is reachable
  ✓ Cache (./cache/codeparse.db): Cache database is accessible

Configured Codebases
╭───────────┬───────────────────┬────────┬──────────┬─────────────╮
│ Name      │ Repository        │ Branch │ Interval │ Collection  │
├───────────┼───────────────────┼────────┼──────────┼─────────────┤
│ myproject │ https://github... │ main   │ 300s     │ codebase_...│
╰───────────┴───────────────────┴────────┴──────────┴─────────────╯
```

### Sync Output (Verbose)
```
2026-02-25 22:00:00 | INFO     | sync:sync_codebase | Starting sync for myproject
2026-02-25 22:00:01 | INFO     | sync:sync_codebase | New commit detected: none → abc12345
2026-02-25 22:00:02 | INFO     | sync:_process_file | Processing 15 code files
2026-02-25 22:00:05 | DEBUG    | sync:_process_file | File unchanged: README.md
2026-02-25 22:00:06 | DEBUG    | sync:_process_file | Symbol new: MyClass.authenticate
2026-02-25 22:00:10 | INFO     | qdrant_client:upsert_points | Upserted 12 vectors to Qdrant
2026-02-25 22:00:11 | INFO     | sync:sync_codebase | Sync completed: 5 files changed, 12 vectors
```

### Search Output
```
Found 3 results in myproject

╭──────────────────────────────────────────────────────────────────╮
│ Result 1                                                         │
├──────────────────────────────────────────────────────────────────┤
│ MyClass.authenticate                                             │
│                                                                  │
│ File: src/auth.py:45-67                                          │
│ Type: method | Language: python                                  │
│ Score: 0.892                                                     │
│                                                                  │
│ def authenticate(self, token):                                   │
│     """Authenticate user with token."""                          │
│     if not self.validate_token(token):                           │
│         raise AuthenticationError                                │
│     ...                                                          │
╰──────────────────────────────────────────────────────────────────╯
```

---

## 📚 Additional Resources

- [CONTEXT_EXPANSION.md](services/codeparse/CONTEXT_EXPANSION.md) - Context expansion system
- [README.md](services/codeparse/README.md) - Full API documentation
- [IMPLEMENTATION_SUMMARY.md](services/codeparse/IMPLEMENTATION_SUMMARY.md) - Implementation details

---

## ✅ Quick Reference Card

```bash
# Start everything
docker-compose up -d                                    # Start Qdrant
uv run python -m services.codeparse.cli start --verbose # Start scheduler

# Manual operations
uv run python -m services.codeparse.cli sync --all      # Sync all repos
uv run python -m services.codeparse.cli search "query"  # Search code

# Monitoring
uv run python -m services.codeparse.cli status          # Check health
tail -f logs/codeparse.log                              # Watch logs

# Debugging
uv run python -m services.codeparse.cli cache-clear --all --force  # Clear cache
uv run python -m services.codeparse.cli sync --debug    # Debug sync
```
