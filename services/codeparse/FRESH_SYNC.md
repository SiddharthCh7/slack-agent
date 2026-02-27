# Fresh Sync (Git Clone Method)

## Overview

The **fresh sync** feature uses `git clone --depth 1` for efficient initial repository synchronization:

- ✅ **No API rate limits** - Local file access, no GitHub API calls
- ✅ **Much faster** - Single clone vs hundreds of API calls
- ✅ **Automatic cleanup** - Cloned repo deleted after processing
- ✅ **Smart detection** - Only clones if no cached data exists

---

## When to Use

### Use Fresh Sync When:
- ✅ Initial sync of a large repository
- ✅ Resetting corrupted data
- ✅ Avoiding GitHub API rate limits
- ✅ You want the fastest possible sync

### Use Regular Sync When:
- ✅ Repository already has cached data
- ✅ Incremental updates (only changed files)
- ✅ You have a GitHub token with high rate limit

---

## Commands

### Fresh Sync Single Codebase

```bash
# Clear data and clone fresh
uv run python -m services.codeparse.cli fresh-sync --codebase olake

# With verbose logging
uv run python -m services.codeparse.cli fresh-sync --codebase olake --verbose
```

### Fresh Sync All Codebases

```bash
# Clear and clone all enabled codebases
uv run python -m services.codeparse.cli fresh-sync --all
```

### Alternative: Use --fresh flag

```bash
# Same as fresh-sync command
uv run python -m services.codeparse.cli sync --codebase olake --fresh
```

---

## How It Works

### Workflow

```
1. Check commit_state in cache
   ↓
2. No cached data? → Clone with git clone --depth 1
   ↓
3. Process all files locally (no API calls)
   ↓
4. Upsert vectors to Qdrant
   ↓
5. Update commit_state
   ↓
6. Delete cloned repo
   ↓
Done!
```

### Comparison: Fresh Sync vs API Sync

| Aspect | Fresh Sync | API Sync |
|--------|------------|----------|
| **Method** | git clone | GitHub REST API |
| **API Calls** | 0 | ~2 per file + overhead |
| **Rate Limit** | None | 60/hour (unauth) or 5000/hour (auth) |
| **Speed** | Very fast | Slower (API latency) |
| **Best For** | Initial sync | Incremental updates |
| **Cleanup** | Automatic | N/A |

---

## Example Output

```bash
$ uv run python -m services.codeparse.cli fresh-sync --codebase olake

Starting fresh sync (git clone method)
Fresh syncing: olake
Clearing existing data...
Cloning https://github.com/datazip-inc/olake (branch: main) to /tmp/codeparse_clones/olake_20260226_001800
Clone successful: https://github.com/datazip-inc/olake @ f096b4b4
Found 178 code files
Processing local repo at /tmp/...
Progress: 50/178 files
Progress: 100/178 files
Progress: 150/178 files
Local sync complete: 178 files, 450 symbols, 450 vectors
Cleaned up cloned repo: /tmp/...

╭──────────────────────────────────────────────────────────────╮
│ Fresh Sync Complete                                          │
├──────────────────────────────────────────────────────────────┤
│ Files processed: 178                                         │
│ Files skipped: 0                                             │
│ Symbols: 450                                                 │
│ Vectors upserted: 450                                        │
│ Errors: 0                                                    │
╰──────────────────────────────────────────────────────────────╯
```

---

## Configuration

Add to `sync_config.yaml`:

```yaml
sync:
  # Git clone settings
  max_retries: 3
  retry_wait_seconds: 60
  
  # Performance
  max_workers: 4  # Parallel file processing
```

---

## Technical Details

### Shallow Clone

```bash
git clone --depth 1 --single-branch --branch main <repo_url>
```

- `--depth 1`: Only latest commit (fastest)
- `--single-branch`: Only specified branch
- `--branch`: Branch to clone

### File Detection

Automatically detects code files by extension:
- `.py`, `.js`, `.ts`, `.tsx`, `.jsx`
- `.go`, `.rs`, `.java`, `.rb`
- `.c`, `.cpp`, `.h`, `.hpp`
- `.cs`, `.php`, `.swift`, `.kt`

Excludes:
- `__pycache__`, `node_modules`, `vendor`
- `.git`, `.venv`, `venv`
- `dist`, `build`, `target`
- `*.min.js`, `*.bundle.js`

### Cleanup

Cloned repositories are stored in:
```
/tmp/codeparse_clones/olake_YYYYMMDD_HHMMSS/
```

Automatically deleted after processing (even on errors).

---

## Python API Usage

```python
from services.codeparse import (
    Config,
    CodeSyncEngine,
    GitCloneSync,
)
from agent.embedding import embed_texts

config = Config.load("sync_config.yaml")

with CodeSyncEngine(config, embed_texts) as engine:
    # Create git clone sync
    git_sync = GitCloneSync(
        cache=engine.cache,
        qdrant=engine.qdrant,
        parser=engine.parser,
        embed_fn=embed_texts,
        sync_config=config.sync,
    )
    
    # Check if should clone
    if git_sync.should_clone("https://github.com/datazip-inc/olake"):
        print("No cached data, will clone")
    else:
        print("Cached data exists, using API")
    
    # Fresh sync (clone + process + delete)
    codebase = config.get_codebase_by_name("olake")
    result = git_sync.sync_codebase(codebase)
    
    print(f"Processed {result.files_processed} files")
    print(f"Upserted {result.vectors_upserted} vectors")
    
    # Clear data manually
    git_sync.clear_codebase_data(codebase)
```

---

## Troubleshooting

### Clone Failed

```bash
# Check git is installed
git --version

# Check repo URL is accessible
git ls-remote https://github.com/datazip-inc/olake

# Try manual clone
git clone --depth 1 https://github.com/datazip-inc/olake /tmp/test_clone
```

### Permission Denied

```bash
# For private repos, use token
export GITHUB_TOKEN=ghp_your_token

# Or use SSH
git clone git@github.com:owner/repo.git
```

### Out of Disk Space

```bash
# Check temp directory space
df -h /tmp

# Change temp directory
export CODEPARSE_TEMP=/path/to/larger/disk
```

### Timeout

Clone times out after 5 minutes. For very large repos:
- Increase timeout in `git_clone_sync.py`
- Use shallow clone (already enabled)
- Check network connection

---

## Best Practices

1. **Use fresh sync for initial sync** - Much faster than API
2. **Use regular sync for updates** - Only processes changed files
3. **Add GitHub token** - For when you need API sync
4. **Monitor disk space** - Clones can be large temporarily
5. **Run during off-peak** - For very large repos

---

## Comparison Table

| Scenario | Recommended Method |
|----------|-------------------|
| First-time sync (1000+ files) | `fresh-sync` |
| First-time sync (<100 files) | Either works |
| Daily incremental sync | Regular `sync` |
| After data corruption | `fresh-sync --all` |
| Rate limit exceeded | `fresh-sync` |
| Private repo | `fresh-sync` (with token) |

---

## Related Commands

```bash
# Regular sync (API-based)
uv run python -m services.codeparse.cli sync --codebase olake

# Fresh sync (git clone)
uv run python -m services.codeparse.cli fresh-sync --codebase olake

# Check status
uv run python -m services.codeparse.cli status

# Clear cache manually
uv run python -m services.codeparse.cli cache-clear --all --force
```

---

## Summary

**Fresh sync** is the fastest way to initially sync a repository:

- Uses `git clone --depth 1` (shallow clone)
- Processes files locally (no API calls)
- Automatically cleans up after itself
- Perfect for large repositories or rate limit avoidance

**Command:**
```bash
uv run python -m services.codeparse.cli fresh-sync --codebase olake
```
