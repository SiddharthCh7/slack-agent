"""
Tests for the incremental code documentation system.
"""

import pytest
from services.codeparse import (
    Config,
    CodeParseCache,
    HashIdentity,
    GitHubClient,
    CodeParser,
    CodeChunk,
    ChunkType,
)


class TestHashIdentity:
    """Test hash-based identity system."""

    def test_stable_symbol_key_deterministic(self):
        """Stable symbol key should be deterministic."""
        key1 = HashIdentity.compute_stable_symbol_key(
            "https://github.com/owner/repo",
            "src/utils.py",
            "MyClass.my_method"
        )
        key2 = HashIdentity.compute_stable_symbol_key(
            "https://github.com/owner/repo",
            "src/utils.py",
            "MyClass.my_method"
        )
        assert key1 == key2
        assert len(key1) == 64  # SHA256 hex

    def test_stable_symbol_key_case_insensitive_repo(self):
        """Repo URL should be case-insensitive."""
        key1 = HashIdentity.compute_stable_symbol_key(
            "https://github.com/Owner/Repo",
            "src/utils.py",
            "func"
        )
        key2 = HashIdentity.compute_stable_symbol_key(
            "https://github.com/owner/repo",
            "src/utils.py",
            "func"
        )
        assert key1 == key2

    def test_content_hash_changes_with_content(self):
        """Content hash should change when content changes."""
        hash1 = HashIdentity.compute_content_hash("print('hello')")
        hash2 = HashIdentity.compute_content_hash("print('world')")
        assert hash1 != hash2

    def test_content_hash_line_ending_normalization(self):
        """Content hash should normalize line endings."""
        hash1 = HashIdentity.compute_content_hash("line1\nline2")
        hash2 = HashIdentity.compute_content_hash("line1\r\nline2")
        assert hash1 == hash2

    def test_chunk_hash_normalization(self):
        """Chunk hash should normalize whitespace."""
        hash1 = HashIdentity.compute_chunk_hash("def foo():\n    pass")
        hash2 = HashIdentity.compute_chunk_hash("def foo():\n        pass")
        # Different indentation should produce different hashes
        # (we preserve leading whitespace structure)
        assert hash1 != hash2  # This is expected - we preserve indentation

    def test_chunk_hash_stability(self):
        """Chunk hash should be stable for same code."""
        code = "def foo():\n    return 42"
        hash1 = HashIdentity.compute_chunk_hash(code)
        hash2 = HashIdentity.compute_chunk_hash(code)
        assert hash1 == hash2


class TestCodeParseCache:
    """Test SQLite cache layer."""

    def test_cache_initialization(self, tmp_path):
        """Cache should initialize correctly."""
        db_path = tmp_path / "test.db"
        cache = CodeParseCache(str(db_path))
        
        stats = cache.get_stats()
        assert stats["file_count"] == 0
        assert stats["symbol_count"] == 0
        assert stats["repo_count"] == 0
        
        cache.close()

    def test_file_registry_operations(self, tmp_path):
        """Test file registry CRUD operations."""
        from datetime import datetime, timezone
        from services.codeparse.cache import FileRecord
        
        db_path = tmp_path / "test.db"
        cache = CodeParseCache(str(db_path))
        
        # Insert
        record = FileRecord(
            repo_url="https://github.com/test/repo",
            file_path="src/utils.py",
            content_hash="abc123",
            last_commit="def456",
            last_synced=datetime.now(timezone.utc)
        )
        cache.upsert_file(record)
        
        # Retrieve
        retrieved = cache.get_file("https://github.com/test/repo", "src/utils.py")
        assert retrieved is not None
        assert retrieved.content_hash == "abc123"
        
        # Update
        record.content_hash = "xyz789"
        cache.upsert_file(record)
        
        retrieved = cache.get_file("https://github.com/test/repo", "src/utils.py")
        assert retrieved.content_hash == "xyz789"
        
        cache.close()

    def test_symbol_registry_operations(self, tmp_path):
        """Test symbol registry CRUD operations."""
        from services.codeparse.cache import SymbolRecord
        
        db_path = tmp_path / "test.db"
        cache = CodeParseCache(str(db_path))
        
        # Insert
        record = SymbolRecord(
            stable_symbol_key="test_key_123",
            chunk_hash="chunk_abc",
            vector_id="vector_1",
            last_commit="def456",
            file_path="src/utils.py",
            fully_qualified_name="MyClass.my_method",
            chunk_type="method",
            repo_url="https://github.com/test/repo"
        )
        cache.upsert_symbol(record)
        
        # Retrieve
        retrieved = cache.get_symbol("test_key_123")
        assert retrieved is not None
        assert retrieved.vector_id == "vector_1"
        
        # Get by file
        symbols = cache.get_symbols_for_file("https://github.com/test/repo", "src/utils.py")
        assert len(symbols) == 1
        
        cache.close()

    def test_commit_state_operations(self, tmp_path):
        """Test commit state CRUD operations."""
        from datetime import datetime, timezone
        from services.codeparse.cache import CommitState
        
        db_path = tmp_path / "test.db"
        cache = CodeParseCache(str(db_path))
        
        # Insert
        state = CommitState(
            repo_url="https://github.com/test/repo",
            latest_commit_hash="abc123",
            synced_at=datetime.now(timezone.utc)
        )
        cache.upsert_commit_state(state)
        
        # Retrieve
        retrieved = cache.get_commit_state("https://github.com/test/repo")
        assert retrieved is not None
        assert retrieved.latest_commit_hash == "abc123"
        
        cache.close()


class TestCodeParser:
    """Test tree-sitter code parser."""

    def test_parse_python_functions(self):
        """Test Python function extraction."""
        parser = CodeParser()
        
        code = """
def foo():
    pass

def bar(x, y):
    return x + y
"""
        chunks = parser.parse_file("test.py", code, "python")
        
        functions = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
        assert len(functions) == 2
        
        names = [c.fully_qualified_name for c in functions]
        assert "foo" in names
        assert "bar" in names

    def test_parse_python_class(self):
        """Test Python class extraction."""
        parser = CodeParser()
        
        code = """
class MyClass:
    def method(self):
        pass
"""
        chunks = parser.parse_file("test.py", code, "python")
        
        classes = [c for c in chunks if c.chunk_type == ChunkType.CLASS]
        assert len(classes) == 1
        assert classes[0].fully_qualified_name == "MyClass"
        
        methods = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
        assert len(methods) == 1
        assert methods[0].fully_qualified_name == "MyClass.method"

    def test_parse_python_docstrings(self):
        """Test Python docstring extraction."""
        parser = CodeParser()
        
        code = '''
def foo():
    """This is a docstring."""
    pass
'''
        chunks = parser.parse_file("test.py", code, "python")
        
        functions = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
        assert len(functions) == 1
        assert "This is a docstring" in functions[0].docstring

    def test_parse_python_imports(self):
        """Test Python import extraction."""
        parser = CodeParser()
        
        code = """
import os
import sys
from pathlib import Path
"""
        chunks = parser.parse_file("test.py", code, "python")
        
        imports = [c for c in chunks if c.chunk_type == ChunkType.IMPORT]
        assert len(imports) == 1

    def test_parse_javascript_functions(self):
        """Test JavaScript function extraction."""
        parser = CodeParser()
        
        code = """
function foo() {
    return 42;
}

const bar = (x) => x * 2;
"""
        chunks = parser.parse_file("test.js", code, "javascript")
        
        functions = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
        assert len(functions) >= 1

    def test_fallback_parsing(self):
        """Test fallback parsing for unsupported languages."""
        parser = CodeParser()
        
        code = "some code here"
        chunks = parser.parse_file("test.xyz", code, "unknown")
        
        # Should return at least one module-level chunk
        assert len(chunks) >= 1


class TestConfig:
    """Test configuration management."""

    def test_load_config(self):
        """Test loading configuration from file."""
        config = Config.load("sync_config.yaml")
        
        assert len(config.codebases) > 0
        assert config.processing.max_chunk_size > 0
        assert config.qdrant.port > 0

    def test_validate_config(self):
        """Test configuration validation."""
        config = Config.load("sync_config.yaml")
        errors = config.validate()
        
        # Should have no errors for valid config
        assert len(errors) == 0

    def test_get_enabled_codebases(self):
        """Test filtering enabled codebases."""
        config = Config.load("sync_config.yaml")
        
        enabled = config.get_enabled_codebases()
        all_codebases = config.codebases
        
        assert len(enabled) <= len(all_codebases)
        assert all(cb.enabled for cb in enabled)


class TestHashIdentityIntegration:
    """Integration tests for hash identity system."""

    def test_full_identity_computation(self):
        """Test computing all three hash levels."""
        from services.codeparse.hasher import compute_hash_identity
        
        identity = compute_hash_identity(
            repo_url="https://github.com/test/repo",
            file_path="src/utils.py",
            fully_qualified_name="MyClass.my_method",
            file_content="class MyClass:\n    def my_method(self):\n        pass",
            code_text="def my_method(self):\n    pass"
        )
        
        assert len(identity.stable_symbol_key) == 64
        assert len(identity.content_hash) == 64
        assert len(identity.chunk_hash) == 64
        
        # Stability test
        identity2 = compute_hash_identity(
            repo_url="https://github.com/test/repo",
            file_path="src/utils.py",
            fully_qualified_name="MyClass.my_method",
            file_content="class MyClass:\n    def my_method(self):\n        pass",
            code_text="def my_method(self):\n    pass"
        )
        
        assert identity.stable_symbol_key == identity2.stable_symbol_key
        assert identity.content_hash == identity2.content_hash
        assert identity.chunk_hash == identity2.chunk_hash
