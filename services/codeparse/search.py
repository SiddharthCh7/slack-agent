"""
Retrieval and search functionality for code documentation.

Supports:
- Semantic search with metadata filters
- Multi-query search for better coverage
- Parent context retrieval using parent_symbols references
- File context retrieval for sibling symbols
- Import dependency resolution
- Reverse dependency lookup (find callers/importers)
- Code neighbor expansion (before/after lines)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

from .config import Config
from .qdrant_client import QdrantCodeStore, CodePoint


@dataclass
class SearchResult:
    """A search result with chunk data and score."""
    stable_symbol_key: str
    code_text: str
    chunk_type: str
    file_path: str
    language: str
    fully_qualified_name: str
    signature: str
    docstring: str
    start_line: int
    end_line: int
    repo_url: str
    commit_hash: str
    score: float
    parent_context: Optional[str] = None
    siblings_context: Optional[str] = None
    context_header: Optional[str] = None
    imports_context: Optional[list[str]] = None
    neighbors_context: Optional[dict[str, str]] = None


class CodeSearcher:
    """
    Semantic search engine for code documentation.
    
    Provides search capabilities with metadata filtering and context retrieval.
    """

    def __init__(
        self,
        config: Config,
        embed_query_fn: callable,
    ):
        """
        Initialize searcher.
        
        Args:
            config: Configuration object.
            embed_query_fn: Function to embed query strings.
        """
        self.config = config
        self.embed_query_fn = embed_query_fn
        
        self.qdrant = QdrantCodeStore(
            host=config.qdrant.host,
            port=config.qdrant.port,
            grpc_port=config.qdrant.grpc_port,
            vector_size=config.qdrant.vector_size,
            distance=config.qdrant.distance,
        )
        
        logger.info("CodeSearcher initialized")

    def close(self) -> None:
        """Close connections."""
        self.qdrant.close()

    def __enter__(self) -> "CodeSearcher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # =========================================================================
    # Search Methods
    # =========================================================================

    def search_code(
        self,
        query: str,
        collection_name: str,
        top_k: int = 10,
        language: Optional[str] = None,
        file_path: Optional[str] = None,
        chunk_type: Optional[str] = None,
        score_threshold: float = 0.5,
    ) -> list[SearchResult]:
        """
        Semantic search over code with optional filters.
        
        Args:
            query: Search query string.
            collection_name: Qdrant collection to search.
            top_k: Number of results to return.
            language: Filter by programming language.
            file_path: Filter by file path (supports prefix matching).
            chunk_type: Filter by chunk type (function, class, import, etc.).
            score_threshold: Minimum similarity score.
        
        Returns:
            List of SearchResult objects.
        """
        # Build filter conditions
        filter_conditions = {}
        
        if language:
            filter_conditions["language"] = language
        
        if chunk_type:
            filter_conditions["chunk_type"] = chunk_type
        
        if file_path:
            filter_conditions["file_path"] = file_path
        
        # Embed query
        try:
            query_embedding = self.embed_query_fn(query)
        except Exception as e:
            logger.error(f"Error embedding query: {e}")
            return []
        
        # Search Qdrant
        results = self.qdrant.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            filter_conditions=filter_conditions if filter_conditions else None,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        # Convert to SearchResult
        search_results = []
        for point, score in results:
            payload = point.payload

            result = SearchResult(
                stable_symbol_key=payload.get("stable_symbol_key", point.id),
                code_text=payload.get("code_text", ""),
                chunk_type=payload.get("chunk_type", ""),
                file_path=payload.get("file_path", ""),
                language=payload.get("language", ""),
                fully_qualified_name=payload.get("fully_qualified_name", ""),
                signature=payload.get("signature", ""),
                docstring=payload.get("docstring", ""),
                start_line=payload.get("start_line", 0),
                end_line=payload.get("end_line", 0),
                repo_url=payload.get("repo_url", ""),
                commit_hash=payload.get("commit_hash", ""),
                score=score,
            )

            search_results.append(result)

        # Expand results with parent context, sibling methods, and file headers
        search_results = self.expand_search_results(
            search_results,
            collection_name,
            expand_methods=True,
            expand_headers=True,
        )

        return search_results

    def search_code_multi_query(
        self,
        queries: list[str],
        collection_name: str,
        top_k: int = 10,
        language: Optional[str] = None,
        chunk_type: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        Search with multiple query variations for better coverage.
        
        Args:
            queries: List of query strings.
            collection_name: Qdrant collection to search.
            top_k: Number of results to return.
            language: Filter by programming language.
            chunk_type: Filter by chunk type.
        
        Returns:
            List of SearchResult objects (deduplicated).
        """
        # Build filter conditions
        filter_conditions = {}
        
        if language:
            filter_conditions["language"] = language
        
        if chunk_type:
            filter_conditions["chunk_type"] = chunk_type
        
        # Embed all queries
        try:
            query_embeddings = [self.embed_query_fn(q) for q in queries]
        except Exception as e:
            logger.error(f"Error embedding queries: {e}")
            return []
        
        # Search Qdrant with multiple vectors
        results = self.qdrant.search_with_multiple_vectors(
            collection_name=collection_name,
            query_vectors=query_embeddings,
            filter_conditions=filter_conditions if filter_conditions else None,
            top_k=top_k,
        )
        
        # Convert to SearchResult
        search_results = []
        seen_keys = set()
        
        for point, score in results:
            payload = point.payload
            stable_key = payload.get("stable_symbol_key", point.id)
            
            if stable_key in seen_keys:
                continue
            seen_keys.add(stable_key)
            
            result = SearchResult(
                stable_symbol_key=stable_key,
                code_text=payload.get("code_text", ""),
                chunk_type=payload.get("chunk_type", ""),
                file_path=payload.get("file_path", ""),
                language=payload.get("language", ""),
                fully_qualified_name=payload.get("fully_qualified_name", ""),
                signature=payload.get("signature", ""),
                docstring=payload.get("docstring", ""),
                start_line=payload.get("start_line", 0),
                end_line=payload.get("end_line", 0),
                repo_url=payload.get("repo_url", ""),
                commit_hash=payload.get("commit_hash", ""),
                score=score,
            )
            
            search_results.append(result)
        
        return search_results

    def search_by_symbol_name(
        self,
        symbol_name: str,
        collection_name: str,
        exact: bool = False,
    ) -> list[SearchResult]:
        """
        Search by symbol name (fully qualified or partial).
        
        Args:
            symbol_name: Symbol name to search for.
            collection_name: Qdrant collection to search.
            exact: If True, match exactly; if False, use substring match.
        
        Returns:
            List of SearchResult objects.
        """
        if exact:
            # Exact match using filter
            points = self.qdrant.get_points_by_filter(
                collection_name,
                {"fully_qualified_name": symbol_name},
                limit=100,
                with_vectors=False,
            )
        else:
            # Substring match - get all and filter
            points = self.qdrant.get_points_by_filter(
                collection_name,
                {},
                limit=1000,
                with_vectors=False,
            )
            
            # Filter by substring match
            symbol_name_lower = symbol_name.lower()
            points = [
                p for p in points
                if symbol_name_lower in p.payload.get("fully_qualified_name", "").lower()
                or symbol_name_lower in p.payload.get("signature", "").lower()
            ]
        
        results = []
        for point in points:
            payload = point.payload
            
            result = SearchResult(
                stable_symbol_key=payload.get("stable_symbol_key", point.id),
                code_text=payload.get("code_text", ""),
                chunk_type=payload.get("chunk_type", ""),
                file_path=payload.get("file_path", ""),
                language=payload.get("language", ""),
                fully_qualified_name=payload.get("fully_qualified_name", ""),
                signature=payload.get("signature", ""),
                docstring=payload.get("docstring", ""),
                start_line=payload.get("start_line", 0),
                end_line=payload.get("end_line", 0),
                repo_url=payload.get("repo_url", ""),
                commit_hash=payload.get("commit_hash", ""),
                score=1.0,  # Exact/partial match
            )
            
            results.append(result)
        
        return results

    def search_by_file_path(
        self,
        file_path: str,
        collection_name: str,
        prefix_match: bool = True,
    ) -> list[SearchResult]:
        """
        Search by file path.
        
        Args:
            file_path: File path to search for.
            collection_name: Qdrant collection to search.
            prefix_match: If True, match files starting with this path.
        
        Returns:
            List of SearchResult objects.
        """
        if prefix_match:
            # Get all points and filter by prefix
            points = self.qdrant.get_points_by_filter(
                collection_name,
                {},
                limit=1000,
                with_vectors=False,
            )
            
            points = [
                p for p in points
                if p.payload.get("file_path", "").startswith(file_path)
            ]
        else:
            # Exact match
            points = self.qdrant.get_points_by_filter(
                collection_name,
                {"file_path": file_path},
                limit=100,
                with_vectors=False,
            )
        
        results = []
        for point in points:
            payload = point.payload
            
            result = SearchResult(
                stable_symbol_key=payload.get("stable_symbol_key", point.id),
                code_text=payload.get("code_text", ""),
                chunk_type=payload.get("chunk_type", ""),
                file_path=payload.get("file_path", ""),
                language=payload.get("language", ""),
                fully_qualified_name=payload.get("fully_qualified_name", ""),
                signature=payload.get("signature", ""),
                docstring=payload.get("docstring", ""),
                start_line=payload.get("start_line", 0),
                end_line=payload.get("end_line", 0),
                repo_url=payload.get("repo_url", ""),
                commit_hash=payload.get("commit_hash", ""),
                score=1.0,
            )
            
            results.append(result)
        
        return results

    def get_chunk_by_id(
        self,
        stable_symbol_key: str,
        collection_name: str,
    ) -> Optional[SearchResult]:
        """
        Get a single chunk by its stable symbol key.
        
        Args:
            stable_symbol_key: The stable symbol key.
            collection_name: Qdrant collection.
        
        Returns:
            SearchResult or None if not found.
        """
        point = self.qdrant.get_point(collection_name, stable_symbol_key)
        
        if point is None:
            return None
        
        payload = point.payload
        
        return SearchResult(
            stable_symbol_key=payload.get("stable_symbol_key", point.id),
            code_text=payload.get("code_text", ""),
            chunk_type=payload.get("chunk_type", ""),
            file_path=payload.get("file_path", ""),
            language=payload.get("language", ""),
            fully_qualified_name=payload.get("fully_qualified_name", ""),
            signature=payload.get("signature", ""),
            docstring=payload.get("docstring", ""),
            start_line=payload.get("start_line", 0),
            end_line=payload.get("end_line", 0),
            repo_url=payload.get("repo_url", ""),
            commit_hash=payload.get("commit_hash", ""),
            score=1.0,
        )

    # =========================================================================
    # Context Retrieval
    # =========================================================================

    def _get_parent_context(
        self,
        collection_name: str,
        parent_symbols: list[str],
        file_path: str,
    ) -> Optional[str]:
        """
        Retrieve parent class context for a method.

        Args:
            collection_name: Qdrant collection.
            parent_symbols: List of parent symbol names.
            file_path: File path for additional filtering.

        Returns:
            Parent class code text or None.
        """
        if not parent_symbols:
            return None

        # Try to find the parent class
        for parent_name in parent_symbols:
            points = self.qdrant.get_points_by_filter(
                collection_name,
                {
                    "fully_qualified_name": parent_name,
                    "file_path": file_path,
                    "chunk_type": "class",
                },
                limit=1,
                with_vectors=False,
            )

            if points:
                payload = points[0].payload
                return payload.get("code_text", "")

        return None

    def get_class_methods(
        self,
        class_name: str,
        collection_name: str,
        file_path: Optional[str] = None,
        include_full_code: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get all methods belonging to a class.

        Args:
            class_name: Fully qualified class name (e.g., "MyClass").
            collection_name: Qdrant collection.
            file_path: Optional file path to filter by.
            include_full_code: If True, fetch full code text for each method.

        Returns:
            List of method info dictionaries.
        """
        # Build filter for methods in this class
        filter_conditions = {
            "chunk_type": "method",
        }

        # Search for methods with class name prefix in fully_qualified_name
        all_methods = self.qdrant.get_points_by_filter(
            collection_name,
            filter_conditions,
            limit=500,
            with_vectors=include_full_code,
        )

        # Filter to methods of this class
        class_methods = []
        class_name_prefix = f"{class_name}."

        for point in all_methods:
            payload = point.payload
            fq_name = payload.get("fully_qualified_name", "")

            # Check if this method belongs to the class
            if fq_name.startswith(class_name_prefix) or fq_name == class_name:
                method_info = {
                    "stable_symbol_key": payload.get("stable_symbol_key", point.id),
                    "fully_qualified_name": fq_name,
                    "signature": payload.get("signature", ""),
                    "docstring": payload.get("docstring", ""),
                    "start_line": payload.get("start_line", 0),
                    "end_line": payload.get("end_line", 0),
                }

                if include_full_code:
                    method_info["code_text"] = payload.get("code_text", "")

                class_methods.append(method_info)

        # Sort by line number
        class_methods.sort(key=lambda m: m.get("start_line", 0))

        return class_methods

    def get_file_header(
        self,
        file_path: str,
        collection_name: str,
        include_imports: bool = True,
        include_constants: bool = True,
        include_docstring: bool = True,
    ) -> dict[str, Any]:
        """
        Get the file header (module-level context).

        Args:
            file_path: File path.
            collection_name: Qdrant collection.
            include_imports: Include import block.
            include_constants: Include constant definitions.
            include_docstring: Include module docstring.

        Returns:
            Dict with header components.
        """
        header = {
            "file_path": file_path,
            "imports": "",
            "constants": "",
            "docstring": "",
            "full_header": "",
        }

        # Get all chunks from the file
        file_symbols = self.get_file_symbols(file_path, collection_name)

        imports_lines = []
        constants_lines = []

        for sym in file_symbols:
            point = self.qdrant.get_point(collection_name, sym["stable_symbol_key"])
            if not point:
                continue

            payload = point.payload
            chunk_type = payload.get("chunk_type", "")
            code_text = payload.get("code_text", "")

            # Collect imports
            if include_imports and chunk_type == "import":
                imports_lines.append(code_text)

            # Collect module docstring
            if include_docstring and not header["docstring"]:
                docstring = payload.get("docstring", "")
                if docstring:
                    header["docstring"] = docstring

            # Collect top-level constants (assignments at module level)
            if include_constants and chunk_type == "constant":
                constants_lines.append(code_text)

        # Build full header
        header_parts = []

        if header["docstring"]:
            header_parts.append(f'"""{header["docstring"]}"""')

        if imports_lines:
            header_parts.append("\n".join(imports_lines))

        if constants_lines:
            header_parts.append("\n".join(constants_lines))

        header["full_header"] = "\n\n".join(header_parts)
        header["imports"] = "\n".join(imports_lines) if imports_lines else ""
        header["constants"] = "\n".join(constants_lines) if constants_lines else ""

        return header

    def get_file_context(
        self,
        file_path: str,
        collection_name: str,
        include_header: bool = True,
        include_all_symbols: bool = False,
    ) -> dict[str, Any]:
        """
        Get complete file context including header and all symbols.

        Args:
            file_path: File path.
            collection_name: Qdrant collection.
            include_header: Include file header (imports, constants, docstring).
            include_all_symbols: Include full code for all symbols.

        Returns:
            Dict with complete file context.
        """
        context = {
            "file_path": file_path,
            "header": None,
            "symbols": [],
            "full_code": "",
        }

        # Get file header
        if include_header:
            context["header"] = self.get_file_header(file_path, collection_name)

        # Get all symbols
        symbols = self.get_file_symbols(file_path, collection_name)

        if include_all_symbols:
            for sym in symbols:
                point = self.qdrant.get_point(collection_name, sym["stable_symbol_key"])
                if point:
                    sym["code_text"] = point.payload.get("code_text", "")

        context["symbols"] = symbols

        # Build full code representation
        code_parts = []
        if include_header and context["header"]:
            if context["header"]["full_header"]:
                code_parts.append(context["header"]["full_header"])

        if include_all_symbols:
            for sym in symbols:
                if "code_text" in sym:
                    code_parts.append(sym["code_text"])

        context["full_code"] = "\n\n".join(code_parts)

        return context

    def expand_search_results(
        self,
        results: list[SearchResult],
        collection_name: str,
        expand_methods: bool = True,
        expand_headers: bool = True,
    ) -> list[SearchResult]:
        """
        Expand search results with parent context, class methods, and file headers.

        This implements the full expansion workflow:
        - For methods: attach parent class + sibling methods
        - For classes: attach all methods
        - For import blocks: attach file header

        Args:
            results: List of search results to expand.
            collection_name: Qdrant collection.
            expand_methods: If True, get methods for classes.
            expand_headers: If True, get file headers for import chunks.

        Returns:
            List of expanded SearchResult objects.
        """
        for result in results:
            # Get full payload for this result
            point = self.qdrant.get_point(collection_name, result.stable_symbol_key)
            if not point:
                continue

            payload = point.payload

            # 1. For methods: attach parent class + sibling methods
            if result.chunk_type == "method":
                parent_symbols = payload.get("parent_symbols", [])
                if parent_symbols:
                    # Get parent class
                    result.parent_context = self._get_parent_context(
                        collection_name,
                        parent_symbols,
                        result.file_path,
                    )
                    
                    # Get sibling methods
                    class_name = parent_symbols[0]
                    class_methods = self.get_class_methods(
                        class_name,
                        collection_name,
                        result.file_path,
                        include_full_code=False,
                    )
                    if class_methods:
                        method_list = "\n".join([
                            f"  - {m['fully_qualified_name']}: {m['signature']}"
                            for m in class_methods
                        ])
                        result.siblings_context = f"Class methods:\n{method_list}"

            # 2. For classes: attach all methods
            if result.chunk_type == "class" and expand_methods:
                class_methods = self.get_class_methods(
                    result.fully_qualified_name,
                    collection_name,
                    result.file_path,
                    include_full_code=False,
                )
                if class_methods:
                    method_list = "\n".join([
                        f"  - {m['fully_qualified_name']}: {m['signature']}"
                        for m in class_methods
                    ])
                    result.siblings_context = f"Class methods:\n{method_list}"

            # 3. For import blocks: attach file header
            if result.chunk_type == "import" and expand_headers:
                file_header = self.get_file_header(
                    result.file_path,
                    collection_name,
                    include_imports=True,
                    include_constants=True,
                    include_docstring=True,
                )
                if file_header["full_header"]:
                    result.context_header = file_header["full_header"]

        return results

    def get_file_symbols(
        self,
        file_path: str,
        collection_name: str,
    ) -> list[dict[str, Any]]:
        """
        Get all symbols for a file.
        
        Args:
            file_path: File path.
            collection_name: Qdrant collection.
        
        Returns:
            List of symbol info dictionaries.
        """
        points = self.qdrant.get_points_by_filter(
            collection_name,
            {"file_path": file_path},
            limit=500,
            with_vectors=False,
        )
        
        symbols = []
        for point in points:
            payload = point.payload
            symbols.append({
                "stable_symbol_key": payload.get("stable_symbol_key", point.id),
                "fully_qualified_name": payload.get("fully_qualified_name", ""),
                "chunk_type": payload.get("chunk_type", ""),
                "signature": payload.get("signature", ""),
                "start_line": payload.get("start_line", 0),
                "end_line": payload.get("end_line", 0),
            })
        
        # Sort by line number
        symbols.sort(key=lambda s: s.get("start_line", 0))
        
        return symbols

    def get_codebase_stats(self, collection_name: str) -> dict[str, Any]:
        """
        Get statistics for a codebase collection.
        
        Args:
            collection_name: Qdrant collection.
        
        Returns:
            Statistics dictionary.
        """
        info = self.qdrant.get_collection_info(collection_name)
        
        if not info:
            return {"error": "Collection not found"}
        
        # Get chunk type distribution
        chunk_types = {}
        languages = {}
        
        # Sample points to get distribution
        points = self.qdrant.get_points_by_filter(
            collection_name,
            {},
            limit=1000,
            with_vectors=False,
        )
        
        for point in points:
            payload = point.payload
            
            chunk_type = payload.get("chunk_type", "unknown")
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1

            language = payload.get("language", "unknown")
            languages[language] = languages.get(language, 0) + 1

        return {
            "total_chunks": info.get("points_count", 0),
            "chunk_types": chunk_types,
            "languages": languages,
        }

    # =========================================================================
    # Context Expansion Methods
    # =========================================================================

    def get_import_context(
        self,
        chunk: SearchResult,
        collection_name: str,
        max_depth: int = 1,
    ) -> list[SearchResult]:
        """
        Retrieve chunks that this chunk imports/depends on.

        Args:
            chunk: The source chunk to find imports for.
            collection_name: Qdrant collection.
            max_depth: How many levels of imports to resolve.

        Returns:
            List of imported chunks (resolved dependencies).
        """
        # Get imports from chunk payload
        point = self.qdrant.get_point(collection_name, chunk.stable_symbol_key)
        if not point:
            return []

        payload = point.payload
        imports = payload.get("imports", [])

        if not imports:
            return []

        resolved = []
        seen = set()

        # Parse import statements and try to find matching symbols
        for import_stmt in imports:
            # Extract module names from import statements
            # e.g., "from .utils import clean" → "utils.clean"
            # e.g., "import pandas as pd" → "pandas"
            module_names = self._parse_import_statement(import_stmt)

            for module_name in module_names:
                if module_name in seen:
                    continue
                seen.add(module_name)

                # Search for matching symbols
                matches = self.search_by_symbol_name(
                    module_name,
                    collection_name,
                    exact=False,
                )

                resolved.extend(matches[:3])  # Limit per import

        return resolved[:max_depth * 3]

    def _parse_import_statement(self, import_stmt: str) -> list[str]:
        """
        Parse import statement to extract module names.

        Args:
            import_stmt: Import statement string.

        Returns:
            List of module/symbol names.
        """
        names = []

        # Handle "from X import Y" format
        if import_stmt.startswith("from "):
            parts = import_stmt.split(" import ")
            if len(parts) == 2:
                module = parts[0].replace("from ", "").strip()
                imports = parts[1].strip()

                # Handle "from .module import symbol"
                if module.startswith("."):
                    module = module.lstrip(".")

                # Parse imported names
                for item in imports.split(","):
                    item = item.strip()
                    # Handle "Y as Z" → just use Y
                    if " as " in item:
                        item = item.split(" as ")[0].strip()
                    if item and item != "*":
                        names.append(f"{module}.{item}" if module else item)

        # Handle "import X" format
        elif import_stmt.startswith("import "):
            imports = import_stmt.replace("import ", "").strip()
            for item in imports.split(","):
                item = item.strip()
                # Handle "X as Y" → just use X
                if " as " in item:
                    item = item.split(" as ")[0].strip()
                if item:
                    names.append(item)

        return names

    def get_reverse_dependencies(
        self,
        stable_symbol_key: str,
        collection_name: str,
        limit: int = 20,
    ) -> list[SearchResult]:
        """
        Find chunks that depend on this symbol (callers, importers).

        Args:
            stable_symbol_key: The symbol to find dependents for.
            collection_name: Qdrant collection.
            limit: Maximum number of dependents to return.

        Returns:
            List of chunks that depend on this symbol.
        """
        # Get the symbol's fully qualified name
        point = self.qdrant.get_point(collection_name, stable_symbol_key)
        if not point:
            return []

        payload = point.payload
        fq_name = payload.get("fully_qualified_name", "")

        if not fq_name:
            return []

        # Search for chunks that might import or call this symbol
        # Strategy 1: Search by symbol name
        all_points = self.qdrant.get_points_by_filter(
            collection_name,
            {},
            limit=500,  # Search a reasonable sample
            with_vectors=False,
        )

        dependents = []
        fq_name_lower = fq_name.lower()
        symbol_name = fq_name.split(".")[-1].lower()

        for p in all_points:
            p_payload = p.payload

            # Check imports
            imports = p_payload.get("imports", [])
            for imp in imports:
                if fq_name_lower in imp.lower() or symbol_name in imp.lower():
                    dependents.append(self._point_to_search_result(p, 1.0))
                    break

            # Check code text for function calls (simple heuristic)
            code_text = p_payload.get("code_text", "")
            if f"{symbol_name}(" in code_text:
                if p not in dependents:
                    dependents.append(self._point_to_search_result(p, 0.8))

            if len(dependents) >= limit:
                break

        return dependents

    def get_neighbors(
        self,
        chunk: SearchResult,
        collection_name: str,
        lines_before: int = 10,
        lines_after: int = 10,
    ) -> dict[str, str]:
        """
        Get code context before and after the chunk.

        Args:
            chunk: The source chunk.
            collection_name: Qdrant collection.
            lines_before: Number of lines before to retrieve.
            lines_after: Number of lines after to retrieve.

        Returns:
            Dict with 'before' and 'after' code text.
        """
        # Get all chunks from the same file
        file_symbols = self.get_file_symbols(chunk.file_path, collection_name)

        before_lines = []
        after_lines = []

        # Sort by line number
        file_symbols.sort(key=lambda s: s.get("start_line", 0))

        for sym in file_symbols:
            if sym["stable_symbol_key"] == chunk.stable_symbol_key:
                continue

            # Check if this symbol is before or after
            if sym["end_line"] < chunk.start_line:
                # Before - keep only if within range
                if sym["end_line"] >= chunk.start_line - lines_before:
                    before_lines.append(sym)
            elif sym["start_line"] > chunk.end_line:
                # After - keep only if within range
                if sym["start_line"] <= chunk.end_line + lines_after:
                    after_lines.append(sym)
                    if sym["end_line"] > chunk.end_line + lines_after:
                        break

        # Get full code text for neighbors
        neighbors = {}

        if before_lines:
            before_texts = []
            for sym in before_lines[-3:]:  # Last 3 symbols before
                point = self.qdrant.get_point(collection_name, sym["stable_symbol_key"])
                if point:
                    before_texts.append(point.payload.get("code_text", ""))
            neighbors["before"] = "\n\n".join(before_texts)

        if after_lines:
            after_texts = []
            for sym in after_lines[:3]:  # First 3 symbols after
                point = self.qdrant.get_point(collection_name, sym["stable_symbol_key"])
                if point:
                    after_texts.append(point.payload.get("code_text", ""))
            neighbors["after"] = "\n\n".join(after_texts)

        return neighbors

    def expand_result_context(
        self,
        result: SearchResult,
        collection_name: str,
        expand_parent: bool = True,
        expand_imports: bool = False,
        expand_neighbors: bool = False,
        expand_dependents: bool = False,
    ) -> SearchResult:
        """
        Expand a search result with additional context.

        Args:
            result: The search result to expand.
            collection_name: Qdrant collection.
            expand_parent: Fetch parent class context.
            expand_imports: Fetch import dependencies.
            expand_neighbors: Fetch code neighbors.
            expand_dependents: Fetch reverse dependencies.

        Returns:
            SearchResult with expanded context.
        """
        # Parent context (already done automatically in search, but can be called manually)
        if expand_parent and not result.parent_context:
            point = self.qdrant.get_point(collection_name, result.stable_symbol_key)
            if point:
                parent_symbols = point.payload.get("parent_symbols", [])
                if parent_symbols:
                    result.parent_context = self._get_parent_context(
                        collection_name,
                        parent_symbols,
                        result.file_path,
                    )

        # Import context
        if expand_imports:
            result.imports_context = self.get_import_context(
                result,
                collection_name,
                max_depth=1,
            )

        # Neighbors context
        if expand_neighbors:
            result.neighbors_context = self.get_neighbors(
                result,
                collection_name,
                lines_before=10,
                lines_after=10,
            )

        return result

    def _point_to_search_result(
        self,
        point: CodePoint,
        score: float,
    ) -> SearchResult:
        """Convert a CodePoint to SearchResult."""
        payload = point.payload
        return SearchResult(
            stable_symbol_key=payload.get("stable_symbol_key", point.id),
            code_text=payload.get("code_text", ""),
            chunk_type=payload.get("chunk_type", ""),
            file_path=payload.get("file_path", ""),
            language=payload.get("language", ""),
            fully_qualified_name=payload.get("fully_qualified_name", ""),
            signature=payload.get("signature", ""),
            docstring=payload.get("docstring", ""),
            start_line=payload.get("start_line", 0),
            end_line=payload.get("end_line", 0),
            repo_url=payload.get("repo_url", ""),
            commit_hash=payload.get("commit_hash", ""),
            score=score,
        )
