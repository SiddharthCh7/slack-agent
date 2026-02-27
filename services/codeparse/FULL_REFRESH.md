# Full Refresh Command

## Overview

The `full-refresh` command completely resets a codebase and starts from scratch:

1. **Clears all cached data** (SQLite database)
2. **Deletes Qdrant collection**
3. **Re-clones repository** with `git clone --depth 1`
4. **Processes all files fresh**
5. **Stores everything anew**

---

## When to Use

Use `full-refresh` when:
- ✅ You want a completely fresh start
- ✅ Data is corrupted
- ✅ Schema changed in the code
- ✅ You modified the config significantly
- ✅ You want to test the full sync process
- ✅ After fixing parsing errors

---

## Commands

### Full Refresh Single Codebase

```bash
# Interactive (asks for confirmation)
uv run python -m services.codeparse.cli full-refresh --codebase olake

# Skip confirmation
uv run python -m services.codeparse.cli full-refresh --codebase olake --force

# With verbose logging
uv run python -m services.codeparse.cli full-refresh --codebase olake --verbose --force
```

### Full Refresh All Codebases

```bash
# Interactive
uv run python -m services.codeparse.cli full-refresh --all

# Skip confirmation
uv run python -m services.codeparse.cli full-refresh --all --force
```

---

## What It Does

### Step-by-Step Process

```
full-refresh --codebase olake
    ↓
Step 1: Clear SQLite cache
  - file_registry entries
  - symbol_registry entries
  - commit_state entry
    ↓
Step 2: Delete Qdrant collection
  - All vectors removed
  - Collection deleted
    ↓
Step 3: Clone repository
  git clone --depth 1 <repo_url>
    ↓
Step 4: Process files locally
  - Parse with tree-sitter
  - Generate embeddings
  - Upsert to Qdrant
    ↓
Step 5: Update commit_state
    ↓
Step 6: Delete cloned repo
    ↓
Done! ✓
```

---

## Example Output

```bash
$ uv run python -m services.codeparse.cli full-refresh --codebase olake --force

Starting full refresh...

Step 1/4: Clearing cache for olake...
Step 2/4: Deleting Qdrant collection...
Step 3/4: Cloning and processing...
Cloning https://github.com/datazip-inc/olake (branch: main)
Clone successful: https://github.com/datazip-inc/olake @ f096b4b4
Found 178 code files
Processing local repo...
Progress: 50/178 files
Progress: 100/178 files
Progress: 150/178 files
Local sync complete: 178 files, 450 symbols, 450 vectors
Cleaned up cloned repo

╭──────────────────────────────────────────────────────────────╮
│ Full Refresh Complete: olake                                 │
├──────────────────────────────────────────────────────────────┤
│ Files processed: 178                                         │
│ Files skipped: 0                                             │
│ Symbols: 450                                                 │
│ Vectors upserted: 450                                        │
│ Errors: 0                                                    │
╰──────────────────────────────────────────────────────────────╯
```

---

## Comparison: Commands

| Command | What It Does | When to Use |
|---------|--------------|-------------|
| `sync` | Incremental update | Daily sync, only changed files |
| `fresh-sync` | Clone if no data | First-time sync |
| `full-refresh` | **Delete everything + re-clone** | **Complete reset** |

---

## Use Cases

### Use Case 1: After Fixing Parse Errors

```bash
# Fixed einops error in parser
# Now do full refresh to re-process all files
uv run python -m services.codeparse.cli full-refresh --codebase olake --force
```

### Use Case 2: Corrupted Data

```bash
# Data is inconsistent
# Full refresh clears everything
uv run python -m services.codeparse.cli full-refresh --all --force
```

### Use Case 3: Config Changes

```bash
# Changed chunking strategy in config
# Re-process all files with new strategy
uv run python -m services.codeparse.cli full-refresh --all --force
```

### Use Case 4: Schema Changes

```bash
# Modified CodeChunk dataclass
# Need to re-store all data
uv run python -m services.codeparse.cli full-refresh --all --force
```

---

## Safety Features

### Confirmation Prompt

By default, asks for confirmation:

```bash
$ uv run python -m services.codeparse.cli full-refresh --codebase olake

This will DELETE all data for 'olake' and re-clone from scratch. Continue? (y/N):
```

### Skip Confirmation

Use `--force` flag:

```bash
uv run python -m services.codeparse.cli full-refresh --codebase olake --force
```

### Verbose Logging

See detailed progress:

```bash
uv run python -m services.codeparse.cli full-refresh --codebase olake --verbose --force
```

---

## Python API

```python
from services.codeparse import Config, CodeSyncEngine, GitCloneSync
from agent.embedding import embed_texts

config = Config.load("sync_config.yaml")

with CodeSyncEngine(config, embed_texts) as engine:
    git_sync = GitCloneSync(
        cache=engine.cache,
        qdrant=engine.qdrant,
        parser=engine.parser,
        embed_fn=embed_texts,
        sync_config=config.sync,
    )
    
    codebase = config.get_codebase_by_name("olake")
    
    # Clear cache
    git_sync.cache.clear_repo_data(codebase.repo_url)
    
    # Delete collection
    git_sync.qdrant.delete_collection(codebase.collection_name)
    
    # Fresh sync
    result = git_sync.sync_codebase(codebase)
    
    print(f"Full refresh complete: {result.files_processed} files")
```

---

## Troubleshooting

### Command Not Found

```bash
# Update CLI
uv sync

# Verify commands
uv run python -m services.codeparse.cli --help
```

### Permission Denied

```bash
# Clear cache manually
uv run python -m services.codeparse.cli cache-clear --all --force

# Then full refresh
uv run python -m services.codeparse.cli full-refresh --codebase olake --force
```

### Qdrant Collection Not Deleted

```bash
# Manually delete via Python
uv run python -c "
from services.codeparse import Config, QdrantCodeStore
config = Config.load('sync_config.yaml')
qdrant = QdrantCodeStore(host=config.qdrant.host, port=config.qdrant.port)
qdrant.delete_collection('codebase_olake')
"
```

---

## Related Commands

```bash
# Regular sync (incremental)
uv run python -m services.codeparse.cli sync --codebase olake

# Fresh sync (clone if no data)
uv run python -m services.codeparse.cli fresh-sync --codebase olake

# Full refresh (delete + re-clone)
uv run python -m services.codeparse.cli full-refresh --codebase olake --force

# Clear cache only
uv run python -m services.codeparse.cli cache-clear --all --force

# Check status
uv run python -m services.codeparse.cli status
```

---

## Summary

**`full-refresh`** is the nuclear option for resetting a codebase:

- Deletes ALL cached data
- Deletes Qdrant collection
- Re-clones repository
- Re-processes everything
- Stores everything fresh

**Command:**
```bash
uv run python -m services.codeparse.cli full-refresh --codebase olake --force
```

**Use when:**
- Data corrupted
- Schema changed
- After fixing parse errors
- Complete reset needed
