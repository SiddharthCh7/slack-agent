"""
Hash-based identity system for code chunks.

Three-level hash strategy:
1. stable_symbol_key (SHA256): repo_url + file_path + fully_qualified_name
   - Stable semantic identity across commits
   - NOT including start_line (vulnerable to line insertions)
   - NOT including commit_hash (breaks cross-commit reuse)

2. content_hash (SHA256): hash(entire_file_content)
   - Detects file-level changes
   - If unchanged, skip entire file processing

3. chunk_hash (SHA256): hash(normalized_symbol_source)
   - Detects actual code changes within a symbol
   - Normalized whitespace for stability
   - If unchanged, reuse existing vector (no re-embedding)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class HashIdentity:
    """
    Container for the three-level hash identity system.
    
    Attributes:
        stable_symbol_key: Semantic identity (repo + file + symbol name)
        content_hash: File-level change detection
        chunk_hash: Symbol-level change detection
    """
    stable_symbol_key: str
    content_hash: str
    chunk_hash: str

    @classmethod
    def compute_stable_symbol_key(
        cls,
        repo_url: str,
        file_path: str,
        fully_qualified_name: str,
    ) -> str:
        """
        Compute stable symbol key for semantic identity.
        
        CRITICAL: Does NOT include start_line or commit_hash.
        This ensures stability across:
        - Line insertions/deletions above the symbol
        - Different commits with same symbol content
        
        Args:
            repo_url: Repository URL (e.g., https://github.com/owner/repo)
            file_path: File path within repo (e.g., src/utils.py)
            fully_qualified_name: Complete symbol path (e.g., MyClass.my_method)
        
        Returns:
            SHA256 hex string (64 characters)
        """
        # Normalize inputs
        repo_url = repo_url.rstrip("/").lower()
        file_path = file_path.replace("\\", "/")  # Normalize path separators
        fully_qualified_name = fully_qualified_name.strip()
        
        # Combine for hashing
        identity_string = f"{repo_url}|{file_path}|{fully_qualified_name}"
        
        return cls._sha256(identity_string)

    @classmethod
    def compute_content_hash(cls, file_content: str) -> str:
        """
        Compute hash of entire file content.
        
        Used for fast file-level change detection.
        If content_hash matches cache, skip entire file processing.
        
        Args:
            file_content: Raw file content as string.
        
        Returns:
            SHA256 hex string (64 characters)
        """
        # Normalize line endings for cross-platform consistency
        normalized = file_content.replace("\r\n", "\n").replace("\r", "\n")
        return cls._sha256(normalized)

    @classmethod
    def compute_chunk_hash(cls, code_text: str) -> str:
        """
        Compute hash of normalized symbol source code.
        
        Used for detecting actual code changes within a symbol.
        Normalizes whitespace to avoid false positives from formatting changes.
        
        Args:
            code_text: Source code text for the symbol/chunk.
        
        Returns:
            SHA256 hex string (64 characters)
        """
        normalized = cls._normalize_code(code_text)
        return cls._sha256(normalized)

    @staticmethod
    def _sha256(data: str) -> str:
        """Compute SHA256 hash of a string."""
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_code(code: str) -> str:
        """
        Normalize code text for stable hashing.
        
        Normalizations applied:
        - Strip leading/trailing whitespace
        - Normalize internal whitespace (multiple spaces → single space)
        - Normalize line endings
        - Remove trailing whitespace on lines
        - Preserve significant whitespace (indentation structure)
        
        This ensures formatting-only changes don't trigger re-embedding.
        """
        # Normalize line endings
        code = code.replace("\r\n", "\n").replace("\r", "\n")
        
        # Split into lines
        lines = code.split("\n")
        
        # Process each line
        normalized_lines = []
        for line in lines:
            # Remove trailing whitespace
            line = line.rstrip()
            
            # Normalize internal whitespace (but preserve leading indentation)
            # Find leading whitespace
            leading_match = re.match(r"^(\s*)", line)
            leading = leading_match.group(1) if leading_match else ""
            rest = line[len(leading):]
            
            # Normalize whitespace in the rest of the line
            rest = re.sub(r"\s+", " ", rest)
            
            normalized_lines.append(leading + rest)
        
        # Join and strip trailing newlines
        result = "\n".join(normalized_lines)
        return result.strip()

    @classmethod
    def compute_symbol_version_id(
        cls,
        stable_symbol_key: str,
        commit_hash: str,
    ) -> str:
        """
        Compute version-specific ID for historical tracking.
        
        This is OPTIONAL and used only for tracking symbol versions across commits.
        Never use this for reuse decisions - use stable_symbol_key instead.
        
        Args:
            stable_symbol_key: The stable symbol key.
            commit_hash: Git commit SHA.
        
        Returns:
            SHA256 hex string (64 characters)
        """
        version_string = f"{stable_symbol_key}|{commit_hash}"
        return cls._sha256(version_string)

    @classmethod
    def compute_file_content_hash_for_path(
        cls,
        repo_url: str,
        file_path: str,
        file_content: str,
    ) -> tuple[str, str]:
        """
        Compute both stable_symbol_key (for file-level) and content_hash.
        
        Convenience method for file-level operations.
        
        Args:
            repo_url: Repository URL.
            file_path: File path within repo.
            file_content: Raw file content.
        
        Returns:
            Tuple of (stable_symbol_key, content_hash)
        """
        # For file-level identity, use empty fully_qualified_name
        stable_key = cls.compute_stable_symbol_key(repo_url, file_path, "")
        content_hash = cls.compute_content_hash(file_content)
        return stable_key, content_hash


def compute_hash_identity(
    repo_url: str,
    file_path: str,
    fully_qualified_name: str,
    file_content: str,
    code_text: str,
) -> HashIdentity:
    """
    Compute all three hash levels for a code chunk.
    
    Convenience function that computes the complete HashIdentity.
    
    Args:
        repo_url: Repository URL.
        file_path: File path within repo.
        fully_qualified_name: Complete symbol path.
        file_content: Entire file content.
        code_text: Source code for this specific chunk/symbol.
    
    Returns:
        HashIdentity with all three hash values.
    """
    return HashIdentity(
        stable_symbol_key=HashIdentity.compute_stable_symbol_key(
            repo_url, file_path, fully_qualified_name
        ),
        content_hash=HashIdentity.compute_content_hash(file_content),
        chunk_hash=HashIdentity.compute_chunk_hash(code_text),
    )
