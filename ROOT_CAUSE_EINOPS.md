# ✅ Root Cause Analysis: Einops Error Fixed

## Root Cause Found

The error `This modeling file requires einops` was **NOT** from tree-sitter-go.

**Actual Source**: The **embedding model** (`sentence-transformers` loading `nomic-ai/nomic-embed-text-v1.5`) requires `einops` as a dependency.

### Error Trace

```
agent/embedding.py:42 in embed_texts()
  → _get_model()
  → SentenceTransformer()
  → transformers library loads model
  → check_imports() finds einops missing
  → ImportError: This modeling file requires einops
```

---

## Solution

**Added einops to dependencies** in `pyproject.toml`:

```toml
"einops>=0.8.0",  # Required by nomic-ai embedding model
```

Install with:
```bash
uv add einops
```

---

## Cleanup

Removed unnecessary suppression code from `parser.py`:
- Removed `warnings.filterwarnings()` for einops
- Removed `_suppress_stderr()` context manager
- Removed stderr suppression from language init and parsing

The error was never from tree-sitter, so no suppression was needed.

---

## Current Status

✅ **Einops error: FIXED**
✅ **Parsing works correctly**
✅ **No more suppression hacks**

### New Issue (Separate)

Embedding model is running out of GPU memory (26.85 GiB requested on M1):
```
Invalid buffer size: 26.85 GiB
Insufficient Memory (kIOGPUCommandBufferCallbackErrorOutOfMemory)
```

This is a **different issue** - the embedding model is too large for available GPU memory.

**Solutions**:
1. Use CPU-only mode for embeddings
2. Use a smaller embedding model
3. Add GPU memory limits

---

## Commands

```bash
# Install einops (already done)
uv add einops

# Full refresh (will work now, but may hit GPU memory limit)
uv run python -m services.codeparse.cli full-refresh --codebase olake --force
```

---

## Lesson Learned

**Always find the ROOT CAUSE before applying fixes:**
1. ❌ Don't just suppress errors
2. ✅ Trace the actual source
3. ✅ Fix the underlying issue
4. ✅ Clean up unnecessary workarounds

The error message was misleading - it appeared during Go file processing but was actually from the embedding step that happened after parsing.
