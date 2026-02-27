# Context Expansion System

## Overview

When a chunk is retrieved through similarity search, the system **automatically expands context** based on chunk type:

```
User query
    ↓
Vector search → top-k chunks
    ↓
For each chunk:
    if method → attach parent class + sibling methods
    if class → attach all methods
    if import block → attach file header
    ↓
Send expanded context to LLM
```

**Additional on-demand expansions** are available if the agent needs more context.

---

## Automatic Expansion (Built into search_code) ✅

### 1. For Methods: Parent Class + Sibling Methods

**What happens**: When a method is matched, automatically attach:
- The parent class definition
- List of all sibling methods in the class

**Implementation**:
```python
# search.py - Automatic in expand_search_results()
if result.chunk_type == "method":
    # Get parent class
    result.parent_context = self._get_parent_context(...)
    
    # Get sibling methods
    class_methods = self.get_class_methods(class_name, ...)
    result.siblings_context = f"Class methods:\n{method_list}"
```

**Example Output**:
```
Search: "how to authenticate"

Result:
  Function: MyClass.authenticate
  Code: def authenticate(self, token): ...
  
  Parent Context (auto-attached):
    class MyClass:
        """Base class for authentication."""
        def __init__(self, token):
            self.token = token
  
  Sibling Methods (auto-attached):
    Class methods:
      - MyClass.__init__: def __init__(self, token)
      - MyClass.authenticate: def authenticate(self, token)
      - MyClass.refresh: def refresh(self)
```

---

### 2. For Classes: All Methods

**What happens**: When a class is matched, automatically attach list of all methods.

**Implementation**:
```python
# search.py
if result.chunk_type == "class":
    class_methods = self.get_class_methods(result.fully_qualified_name, ...)
    result.siblings_context = f"Class methods:\n{method_list}"
```

**Example Output**:
```
Search: "authentication class"

Result:
  Class: MyClass
  Code: class MyClass: ...
  
  Sibling Methods (auto-attached):
    Class methods:
      - MyClass.__init__: def __init__(self, token)
      - MyClass.authenticate: def authenticate(self, token)
      - MyClass.refresh: def refresh(self)
```

---

### 3. For Import Blocks: File Header

**What happens**: When an import block is matched, attach the complete file header including:
- Module docstring
- All imports
- Module-level constants

**Implementation**:
```python
# search.py
if result.chunk_type == "import":
    file_header = self.get_file_header(result.file_path, ...)
    result.context_header = file_header["full_header"]
```

**Example Output**:
```
Search: "imports for auth"

Result:
  Type: import
  Code: from .utils import Token
  
  Context Header (auto-attached):
    """Authentication module."""
    
    from .utils import Token
    from .config import AUTH_CONFIG
    
    MAX_RETRIES = 3
    TIMEOUT = 30
```

---

## On-Demand Expansion (Agent-Triggered)

The agent can request additional context if needed:

### 4. Full File Context

```python
# Get complete file with header and all symbols
file_context = searcher.get_file_context(
    file_path="src/auth.py",
    collection_name="codebase_myproject",
    include_header=True,
    include_all_symbols=True,  # Fetches full code for each symbol
)

print(file_context["full_code"])  # Complete file content
```

### 5. Import Dependencies

```python
# Find chunks that this chunk imports
imports = searcher.get_import_context(result, "codebase_myproject")
```

### 6. Reverse Dependencies (Callers)

```python
# Find chunks that call/use this symbol
callers = searcher.get_reverse_dependencies(
    result.stable_symbol_key,
    "codebase_myproject",
)
```

### 7. Code Neighbors

```python
# Get code before and after the chunk
neighbors = searcher.get_neighbors(
    result,
    "codebase_myproject",
    lines_before=10,
    lines_after=10,
)
```

---

## SearchResult Fields

After search, each result has these context fields:

| Field | Type | Auto-Populated | Description |
|-------|------|----------------|-------------|
| `parent_context` | `str` | ✅ For methods | Parent class code |
| `siblings_context` | `str` | ✅ For methods/classes | List of sibling methods |
| `context_header` | `str` | ✅ For imports | File header (docstring + imports + constants) |
| `imports_context` | `list` | ❌ | Imported chunks (call `get_import_context()`) |
| `neighbors_context` | `dict` | ❌ | Code before/after (call `get_neighbors()`) |

---

## Usage Examples

### Basic Search (Automatic Expansion)

```python
from services.codeparse import CodeSearcher

with CodeSearcher(config, embed_query) as searcher:
    results = searcher.search_code(
        query="authenticate user",
        collection_name="codebase_myproject",
        top_k=5,
    )
    
    for result in results:
        print(f"Match: {result.fully_qualified_name}")
        print(f"Code: {result.code_text[:200]}")
        
        # These are automatically populated:
        if result.parent_context:
            print(f"Parent: {result.parent_context[:200]}")
        
        if result.siblings_context:
            print(f"Sibling methods: {result.siblings_context}")
        
        if result.context_header:
            print(f"File header: {result.context_header[:200]}")
```

### On-Demand Full File Context

```python
# Agent decides it needs the full file
if needs_more_context:
    file_context = searcher.get_file_context(
        result.file_path,
        "codebase_myproject",
        include_all_symbols=True,
    )
    print(f"Full file:\n{file_context['full_code']}")
```

### Manual Expansion Control

```python
# Search without automatic expansion
results = searcher.search_code(
    query="authenticate",
    collection_name="codebase_myproject",
    top_k=5,
)

# Then expand manually with specific options
results = searcher.expand_search_results(
    results,
    "codebase_myproject",
    expand_methods=True,    # Get class methods
    expand_headers=True,    # Get file headers
)
```

---

## Implementation Status

| Feature | Status | Auto/On-Demand |
|---------|--------|----------------|
| Parent Context (methods) | ✅ Implemented | Auto |
| Sibling Methods | ✅ Implemented | Auto |
| File Header (imports) | ✅ Implemented | Auto |
| Full File Context | ✅ Implemented | On-Demand |
| Import Dependencies | ✅ Implemented | On-Demand |
| Reverse Dependencies | ✅ Implemented | On-Demand |
| Code Neighbors | ✅ Implemented | On-Demand |

---

## Metadata Available for Expansion

Each chunk stores:

| Field | Purpose | Expansion Use |
|-------|---------|---------------|
| `parent_symbols` | Class hierarchy | Parent context ✅ |
| `file_path` | File location | File context ✅ |
| `imports` | Import statements | Import dependencies ✅ |
| `fully_qualified_name` | Symbol path | Reverse lookup ✅ |
| `start_line`, `end_line` | Code location | Neighbor expansion ✅ |
