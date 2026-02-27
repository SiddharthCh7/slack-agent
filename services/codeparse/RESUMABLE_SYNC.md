# Resumable Sync System

## Overview

The resumable sync system ensures that:
1. **All files are tracked** - Every file from the diff API is tracked
2. **Failed files are retried** - Only failed files are re-fetched on retry
3. **commit_state NOT updated until complete** - Prevents losing track of unprocessed files
4. **Rate limits handled gracefully** - Automatic pause and resume
5. **Progress is persisted** - Can resume after restart

---

## How It Works

### Normal Sync Flow (Without Resumable)

```
Get commit diff → Fetch files → Process → Update commit_state
                         ↓
                   Rate limited!
                         ↓
              Some files not fetched
                         ↓
              commit_state updated (WRONG!)
                         ↓
              Next sync thinks all files done
```

### Resumable Sync Flow

```
Get commit diff → Track ALL files → Fetch files → Process
                                            ↓
                                      Rate limited!
                                            ↓
                                   Mark failed files
                                            ↓
                                   Pause and wait
                                            ↓
                                   Retry only failed
                                            ↓
                                   All complete?
                                            ↓  Yes
                                   Update commit_state ✓
```

---

## Configuration

Add to `sync_config.yaml`:

```yaml
sync:
  # Maximum retry attempts per file
  max_retries: 3
  
  # Time to wait before retrying failed files (seconds)
  retry_wait_seconds: 60
  
  # Time to wait when rate limited (seconds)
  rate_limit_wait_seconds: 60
  
  # Maximum files to process in parallel
  max_workers: 4
  
  # If true, pause on rate limit and resume automatically
  pause_on_rate_limit: true
```

---

## File Status Tracking

Each file goes through these states:

```
PENDING → PROCESSING → COMPLETED
                      → FAILED (retry)
                      → SKIPPED (unchanged)
```

### Status Meanings

| Status | Meaning | Action |
|--------|---------|--------|
| `PENDING` | Not yet processed | Will be processed |
| `PROCESSING` | Currently being fetched/parsed | In progress |
| `COMPLETED` | Successfully processed | Done |
| `FAILED` | Error during processing | Will retry |
| `SKIPPED` | Unchanged from cache | Done (no work needed) |

---

## Usage

### Basic Usage

```python
from services.codeparse import (
    Config,
    CodeSyncEngine,
    ResumableSyncManager,
)
from agent.embedding import embed_texts

# Load config
config = Config.load("sync_config.yaml")

# Initialize engine
with CodeSyncEngine(config, embed_texts) as engine:
    codebase = config.get_codebase_by_name("olake")
    
    # Get latest commit
    latest_commit = engine.github.get_latest_commit(
        codebase.repo_url,
        codebase.branch,
    )
    
    # Get file tree
    file_tree = engine.github.get_file_tree(
        codebase.repo_url,
        latest_commit.sha,
    )
    
    # Filter to code files
    code_files = engine._filter_code_files(
        file_tree,
        codebase.repo_url,
        config.processing.exclude_patterns,
        config.processing.supported_languages,
    )
    
    # Start resumable sync
    sync_manager = ResumableSyncManager(
        cache=engine.cache,
        github=engine.github,
        qdrant=engine.qdrant,
        parser=engine.parser,
        embed_fn=embed_texts,
        sync_config=config.sync,
    )
    
    # Execute sync
    success = sync_manager.start_sync(
        codebase=codebase,
        commit_hash=latest_commit.sha,
        file_entries=code_files,
    )
    
    # Check progress
    progress = sync_manager.get_progress()
    print(f"Progress: {progress['progress_percent']:.1f}%")
    print(f"Completed: {progress['completed']}/{progress['total_files']}")
    print(f"Failed: {progress['failed']}")
```

### Retry After Rate Limit

```python
# First sync attempt (gets rate limited)
success = sync_manager.start_sync(codebase, commit_hash, files)

if not success:
    # Some files failed
    progress = sync_manager.get_progress()
    print(f"Sync incomplete: {progress['failed']} files failed")
    
    # Wait configured time
    import time
    time.sleep(config.sync.retry_wait_seconds)
    
    # Retry (only failed files)
    success = sync_manager.start_sync(codebase, commit_hash, files)
```

### Check Progress

```python
progress = sync_manager.get_progress()

if progress:
    print(f"""
Sync Progress:
  Commit: {progress['commit_hash']}
  Total: {progress['total_files']}
  Completed: {progress['completed']}
  Failed: {progress['failed']}
  Pending: {progress['pending']}
  Progress: {progress['progress_percent']:.1f}%
  Complete: {progress['is_complete']}
""")
```

---

## State Persistence

Sync state is persisted to disk, allowing:
- **Process restart** - Can stop and resume later
- **Retry after fix** - Fix rate limit, then retry
- **Progress tracking** - See exactly what's pending

### State File Location

```
cache/
├── codeparse.db      # SQLite cache
└── sync_state.json   # Sync state (created during sync)
```

### State File Contents

```json
{
  "repo_url": "https://github.com/datazip-inc/olake",
  "commit_hash": "f096b4b4...",
  "total_files": 178,
  "file_statuses": {
    "src/file1.py": "completed",
    "src/file2.py": "completed",
    "src/file3.py": "failed",
    "src/file4.py": "pending"
  },
  "file_errors": {
    "src/file3.py": "Rate limit exceeded"
  },
  "file_retry_counts": {
    "src/file3.py": 1
  },
  "started_at": "2026-02-25T22:00:00Z",
  "last_updated": "2026-02-25T22:05:00Z",
  "is_complete": false
}
```

---

## Rate Limit Handling

### Automatic Handling

When rate limit is detected:

1. **Detection**: GitHub API returns 403 with rate limit header
2. **Pause**: Wait `rate_limit_wait_seconds` (default: 60s)
3. **Retry**: Re-fetch the file that hit the limit
4. **Continue**: Resume processing remaining files

### Manual Handling

```python
# Check rate limit status
rate_info = engine.github.check_rate_limit()
print(f"Remaining: {rate_info.get('remaining', 'N/A')}/{rate_info.get('limit', 'N/A')}")
print(f"Resets at: {rate_info.get('reset', 'N/A')}")

# If low, wait before starting
if rate_info.get('remaining', 100) < 20:
    print("Rate limit low, waiting...")
    time.sleep(config.sync.rate_limit_wait_seconds)
```

---

## Example: Sync with Retry

```python
from services.codeparse import Config, CodeSyncEngine, ResumableSyncManager
from agent.embedding import embed_texts
import time

config = Config.load("sync_config.yaml")

with CodeSyncEngine(config, embed_texts) as engine:
    codebase = config.get_codebase_by_name("olake")
    
    # Get commit and files
    commit = engine.github.get_latest_commit(codebase.repo_url, codebase.branch)
    file_tree = engine.github.get_file_tree(codebase.repo_url, commit.sha)
    code_files = engine._filter_code_files(file_tree, codebase.repo_url, ...)
    
    # Create sync manager
    sync_manager = ResumableSyncManager(
        cache=engine.cache,
        github=engine.github,
        qdrant=engine.qdrant,
        parser=engine.parser,
        embed_fn=embed_texts,
        sync_config=config.sync,
    )
    
    # Attempt sync
    max_attempts = config.sync.max_retries
    for attempt in range(max_attempts):
        print(f"Sync attempt {attempt + 1}/{max_attempts}")
        
        success = sync_manager.start_sync(codebase, commit.sha, code_files)
        
        if success:
            print("✓ Sync completed successfully")
            break
        else:
            progress = sync_manager.get_progress()
            print(f"✗ Sync incomplete: {progress['failed']} files failed")
            
            if attempt < max_attempts - 1:
                print(f"Waiting {config.sync.retry_wait_seconds}s before retry...")
                time.sleep(config.sync.retry_wait_seconds)
    
    # Final status
    progress = sync_manager.get_progress()
    print(f"""
Final Status:
  Complete: {progress['is_complete']}
  Progress: {progress['progress_percent']:.1f}%
  Failed: {progress['failed']}
""")
```

---

## Benefits

### Before (Without Resumable Sync)

```
Sync 178 files:
- File 1-50: ✓ Completed
- File 51: ✗ Rate limit hit
- File 52-178: ✗ Not fetched
- commit_state: Updated (WRONG!)
- Result: Lost track of 128 files
```

### After (With Resumable Sync)

```
Sync 178 files:
- File 1-50: ✓ Completed
- File 51: ✗ Rate limit hit
- File 52-178: ⏸ Pending (tracked)
- commit_state: NOT updated (correct!)
- Retry: Only fetch 51-178
- Result: All 178 files processed
```

---

## Troubleshooting

### Sync Stuck on Pending

```python
# Check state file
import json
with open("cache/sync_state.json") as f:
    state = json.load(f)
    print(f"Pending: {len([k for k, v in state['file_statuses'].items() if v == 'pending'])}")
```

### Too Many Retries

```yaml
# Increase max_retries in sync_config.yaml
sync:
  max_retries: 5  # Default: 3
```

### Rate Limit Too Frequent

```yaml
# Increase wait time
sync:
  rate_limit_wait_seconds: 120  # Default: 60
  
# Or add GitHub token for higher limit
# See GITHUB_TOKEN_SETUP.md
```

---

## API Reference

### ResumableSyncManager

```python
class ResumableSyncManager:
    def start_sync(
        codebase: CodebaseConfig,
        commit_hash: str,
        file_entries: list[GitTreeEntry],
    ) -> bool:
        """Start or resume sync. Returns True if complete."""
    
    def get_progress() -> Optional[dict[str, Any]]:
        """Get current sync progress."""
```

### ResumableSyncState

```python
class ResumableSyncState:
    @property
    def pending_files(self) -> list[str]:
        """Files still needing processing."""
    
    @property
    def completed_files(self) -> list[str]:
        """Successfully processed files."""
    
    @property
    def failed_files(self) -> list[str]:
        """Files that failed."""
    
    @property
    def progress_percent(self) -> float:
        """Progress percentage."""
```

---

## Best Practices

1. **Always use resumable sync for large repos** (>50 files)
2. **Add GitHub token** to avoid rate limits
3. **Check progress** after sync completes
4. **Retry failed files** automatically
5. **Monitor rate limit** during sync

```python
# Recommended pattern
with CodeSyncEngine(config, embed_texts) as engine:
    sync_manager = ResumableSyncManager(...)
    
    for attempt in range(config.sync.max_retries):
        if sync_manager.start_sync(...):
            break
        time.sleep(config.sync.retry_wait_seconds)
```
