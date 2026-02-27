"""
Tree-sitter based code parser with hierarchical chunking.

Extracts semantic code chunks (functions, classes, imports, etc.) with rich metadata.
Supports multiple languages with language-specific extraction rules.

Chunking Strategy (hierarchical):
1. Function/method level (primary): Complete function signature + body
2. Class level (secondary): Full class or class-level chunks
3. Module level (tertiary): Imports, constants, module sections

Critical: Chunks always end at natural boundaries, never mid-sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from loguru import logger

try:
    import tree_sitter
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logger.warning("tree-sitter not available, will use fallback parsing")


class ChunkType(str, Enum):
    """Types of code chunks."""
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    IMPORT = "import"
    CONSTANT = "constant"
    MODULE = "module"
    COMMENT = "comment"
    OTHER = "other"


@dataclass
class CodeChunk:
    """
    Represents a parsed code chunk with rich metadata.
    
    Attributes:
        code_text: The actual source code text
        chunk_type: Type of chunk (function, class, import, etc.)
        file_path: Path to the source file
        language: Programming language
        start_line: Starting line number (1-indexed, metadata only)
        end_line: Ending line number (1-indexed)
        fully_qualified_name: Complete symbol path (e.g., MyClass.my_method)
        signature: Function/class signature
        docstring: Extracted docstring if present
        parent_symbols: List of parent symbol names (for nested structures)
        imports: List of imports used by this chunk
        dependencies: List of external dependencies referenced
        complexity_score: Cyclomatic complexity estimate
        repo_url: Source repository URL
        commit_hash: Git commit SHA
    """
    code_text: str
    chunk_type: ChunkType
    file_path: str
    language: str
    start_line: int
    end_line: int
    fully_qualified_name: str = ""
    signature: str = ""
    docstring: str = ""
    parent_symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    complexity_score: int = 0
    repo_url: str = ""
    commit_hash: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "code_text": self.code_text,
            "chunk_type": self.chunk_type.value,
            "file_path": self.file_path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "fully_qualified_name": self.fully_qualified_name,
            "signature": self.signature,
            "docstring": self.docstring,
            "parent_symbols": self.parent_symbols,
            "imports": self.imports,
            "dependencies": self.dependencies,
            "complexity_score": self.complexity_score,
            "repo_url": self.repo_url,
            "commit_hash": self.commit_hash,
        }


class CodeParser:
    """
    Tree-sitter based code parser with hierarchical chunking.
    
    Parses source code and extracts semantic chunks with rich metadata.
    """

    # Language to tree-sitter language name mapping
    LANGUAGES = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "go": "go",
        "rust": "rust",
        "java": "java",
        "ruby": "ruby",
    }

    def __init__(self, max_chunk_size: int = 1000, overlap_tokens: int = 50):
        """
        Initialize parser.
        
        Args:
            max_chunk_size: Maximum tokens per chunk (soft limit).
            overlap_tokens: Tokens to include from parent context.
        """
        self.max_chunk_size = max_chunk_size
        self.overlap_tokens = overlap_tokens
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        
        if TREE_SITTER_AVAILABLE:
            self._init_languages()

    def _init_languages(self) -> None:
        """Initialize tree-sitter languages."""
        # Use individual tree-sitter language packages
        language_modules = {
            "python": "tree_sitter_python",
            "javascript": "tree_sitter_javascript",
            "typescript": "tree_sitter_typescript",
            "go": "tree_sitter_go",
            "rust": "tree_sitter_rust",
            "java": "tree_sitter_java",
            "ruby": "tree_sitter_ruby",
        }
        
        for ts_name, module_name in language_modules.items():
            try:
                module = __import__(module_name, fromlist=["language"])
                lang = tree_sitter.Language(module.language())
                self._languages[ts_name] = lang
                
                parser = tree_sitter.Parser()
                parser.language = lang  # New API uses property assignment
                self._parsers[ts_name] = parser
                
                logger.debug(f"Loaded tree-sitter language: {ts_name}")
            except ImportError:
                logger.debug(f"Tree-sitter module not available: {module_name}")
            except Exception as e:
                logger.debug(f"Could not load tree-sitter language {ts_name}: {e}")

    def parse_file(
        self,
        file_path: str,
        content: str,
        language: str,
        repo_url: str = "",
        commit_hash: str = "",
    ) -> list[CodeChunk]:
        """
        Parse a file and extract code chunks.

        Args:
            file_path: Path to the file.
            content: File content as string.
            language: Programming language.
            repo_url: Source repository URL.
            commit_hash: Git commit SHA.

        Returns:
            List of CodeChunk objects.
        """
        language = language.lower()

        if language not in self.LANGUAGES:
            logger.debug(f"Unsupported language: {language}, using fallback")
            return self._fallback_parse(file_path, content, language, repo_url, commit_hash)

        ts_language = self.LANGUAGES[language]

        if ts_language not in self._parsers:
            logger.debug(f"Parser not available for {language}, using fallback")
            return self._fallback_parse(file_path, content, language, repo_url, commit_hash)

        try:
            parser = self._parsers[ts_language]
            tree = parser.parse(bytes(content, "utf8"))

            chunks = []

            # Extract chunks based on language-specific rules
            if language == "python":
                chunks = self._extract_python_chunks(tree, content, file_path, language, repo_url, commit_hash)
            elif language in ("javascript", "typescript"):
                chunks = self._extract_js_ts_chunks(tree, content, file_path, language, repo_url, commit_hash)
            elif language == "go":
                chunks = self._extract_go_chunks(tree, content, file_path, language, repo_url, commit_hash)
            else:
                chunks = self._extract_generic_chunks(tree, content, file_path, language, repo_url, commit_hash)

                # Extract module-level imports for all chunks
            imports = self._extract_imports(content, language)
            for chunk in chunks:
                chunk.imports = imports
            
            return chunks
            
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            return self._fallback_parse(file_path, content, language, repo_url, commit_hash)

    def _extract_python_chunks(
        self,
        tree: tree_sitter.Tree,
        content: str,
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> list[CodeChunk]:
        """Extract Python-specific chunks."""
        chunks = []
        lines = content.split("\n")
        root = tree.root_node
        
        # Query for Python constructs
        # Functions and methods
        function_query = """
        (function_definition
            name: (identifier) @name
            parameters: (parameters)? @params
            body: (block) @body) @function
        """
        
        # Class definitions
        class_query = """
        (class_definition
            name: (identifier) @name
            body: (block) @body) @class
        """
        
        # Import statements
        import_query = """
        (import_statement) @import
        (import_from_statement) @import
        """

        # Assignment (constants)
        constant_query = """
        (assignment
            left: (identifier) @name
            right: (_) @value) @assignment
        """

        try:
            lang = self._languages["python"]
            
            # Process function definitions
            func_captures = self._run_query(lang, function_query, root)
            
            functions = {}
            for node, tag in func_captures:
                if tag == "function":
                    functions[node.id] = node

            for node_id, node in functions.items():
                chunk = self._python_function_to_chunk(
                    node, content, lines, file_path, language, repo_url, commit_hash
                )
                if chunk:
                    chunks.append(chunk)

            # Process class definitions
            class_captures = self._run_query(lang, class_query, root)
            
            classes = {}
            for node, tag in class_captures:
                if tag == "class":
                    classes[node.id] = node

            for node_id, node in classes.items():
                chunk = self._python_class_to_chunk(
                    node, content, lines, file_path, language, repo_url, commit_hash
                )
                if chunk:
                    chunks.append(chunk)

            # Process imports as a single chunk
            import_captures = self._run_query(lang, import_query, root)
            
            import_nodes = []
            for node, tag in import_captures:
                if tag == "import":
                    import_nodes.append(node)

            if import_nodes:
                chunk = self._python_imports_to_chunk(
                    import_nodes, content, lines, file_path, language, repo_url, commit_hash
                )
                if chunk:
                    chunks.append(chunk)

        except Exception as e:
            logger.debug(f"Error in Python query: {e}")

        return chunks

    def _run_query(
        self,
        language: tree_sitter.Language,
        query_string: str,
        root_node: tree_sitter.Node,
    ) -> list[tuple[tree_sitter.Node, str]]:
        """
        Run a tree-sitter query and return captures.
        
        Handles both old and new tree-sitter API.
        
        Args:
            language: Tree-sitter language.
            query_string: Query string in S-expression format.
            root_node: Root node to query.
        
        Returns:
            List of (node, tag) tuples.
        """
        try:
            from tree_sitter import Query, QueryCursor
            
            query = Query(language, query_string)
            cursor = QueryCursor(query)
            
            captures = []
            for pattern_idx, match_dict in cursor.matches(root_node):
                for tag, nodes in match_dict.items():
                    for node in nodes:
                        captures.append((node, tag))
            
            return captures
            
        except Exception as e:
            logger.debug(f"Query error: {e}")
            return []

    def _python_function_to_chunk(
        self,
        node: tree_sitter.Node,
        content: str,
        lines: list[str],
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> CodeChunk | None:
        """Convert Python function node to CodeChunk."""
        try:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            
            code_text = content[node.start_byte:node.end_byte]
            
            # Extract function name
            name_node = node.child_by_field_name("name")
            func_name = name_node.text.decode("utf8") if name_node else ""
            
            # Extract parameters
            params_node = node.child_by_field_name("parameters")
            params_text = ""
            if params_node:
                params_text = content[params_node.start_byte:params_node.end_byte]
            
            # Build signature
            signature = f"def {func_name}{params_text}"
            
            # Check if it's a method (inside a class)
            parent = node.parent
            parent_symbols = []
            is_method = False
            
            while parent:
                if parent.type == "class_definition":
                    class_name_node = parent.child_by_field_name("name")
                    if class_name_node:
                        class_name = class_name_node.text.decode("utf8")
                        parent_symbols.append(class_name)
                        is_method = True
                        func_name = f"{class_name}.{func_name}"
                    break
                parent = parent.parent
            
            # Extract docstring
            docstring = self._extract_python_docstring(node, content)
            
            # Calculate complexity
            complexity = self._calculate_python_complexity(node)
            
            chunk_type = ChunkType.METHOD if is_method else ChunkType.FUNCTION
            
            return CodeChunk(
                code_text=code_text,
                chunk_type=chunk_type,
                file_path=file_path,
                language=language,
                start_line=start_line,
                end_line=end_line,
                fully_qualified_name=func_name,
                signature=signature,
                docstring=docstring,
                parent_symbols=parent_symbols,
                complexity_score=complexity,
                repo_url=repo_url,
                commit_hash=commit_hash,
            )
        except Exception as e:
            logger.debug(f"Error converting function node: {e}")
            return None

    def _python_class_to_chunk(
        self,
        node: tree_sitter.Node,
        content: str,
        lines: list[str],
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> CodeChunk | None:
        """Convert Python class node to CodeChunk."""
        try:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            
            code_text = content[node.start_byte:node.end_byte]
            
            # Extract class name
            name_node = node.child_by_field_name("name")
            class_name = name_node.text.decode("utf8") if name_node else ""
            
            # Extract base classes
            bases = []
            bases_node = node.child_by_field_name("bases")
            if bases_node:
                bases_text = content[bases_node.start_byte:bases_node.end_byte]
                bases = [b.strip() for b in bases_text.split(",")]
            
            signature = f"class {class_name}"
            if bases:
                signature += f"({', '.join(bases)})"
            
            # Extract docstring
            docstring = self._extract_python_docstring(node, content)
            
            return CodeChunk(
                code_text=code_text,
                chunk_type=ChunkType.CLASS,
                file_path=file_path,
                language=language,
                start_line=start_line,
                end_line=end_line,
                fully_qualified_name=class_name,
                signature=signature,
                docstring=docstring,
                parent_symbols=[],
                complexity_score=1,
                repo_url=repo_url,
                commit_hash=commit_hash,
            )
        except Exception as e:
            logger.debug(f"Error converting class node: {e}")
            return None

    def _python_imports_to_chunk(
        self,
        nodes: list[tree_sitter.Node],
        content: str,
        lines: list[str],
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> CodeChunk | None:
        """Convert Python import statements to a single chunk."""
        if not nodes:
            return None
        
        # Sort by start position
        nodes.sort(key=lambda n: n.start_byte)
        
        start_node = nodes[0]
        end_node = nodes[-1]
        
        start_line = start_node.start_point[0] + 1
        end_line = end_node.end_point[0] + 1
        
        code_text = content[start_node.start_byte:end_node.end_byte]
        
        return CodeChunk(
            code_text=code_text,
            chunk_type=ChunkType.IMPORT,
            file_path=file_path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            fully_qualified_name="imports",
            signature="import statements",
            docstring="",
            parent_symbols=[],
            complexity_score=0,
            repo_url=repo_url,
            commit_hash=commit_hash,
        )

    def _extract_python_docstring(self, node: tree_sitter.Node, content: str) -> str:
        """Extract docstring from a Python function or class."""
        try:
            body = node.child_by_field_name("body")
            if not body:
                return ""
            
            # First child might be an expression statement with a string
            for child in body.children:
                if child.type == "expression_statement":
                    string_child = child.child(0)
                    if string_child and string_child.type in ("string", "string_content"):
                        text = content[string_child.start_byte:string_child.end_byte]
                        # Remove quotes
                        text = text.strip('"\'')
                        return text.strip()
        except Exception:
            pass
        return ""

    def _calculate_python_complexity(self, node: tree_sitter.Node) -> int:
        """Calculate cyclomatic complexity for Python function."""
        complexity = 1  # Base complexity
        
        # Count decision points
        decision_types = {
            "if_statement", "elif_clause", "for_statement",
            "while_statement", "except_clause", "with_statement",
            "assert_statement", "conditional_expression",
            "boolean_operator"
        }
        
        def count_decisions(n: tree_sitter.Node) -> None:
            nonlocal complexity
            if n.type in decision_types:
                complexity += 1
            for child in n.children:
                count_decisions(child)
        
        count_decisions(node)
        return complexity

    def _extract_js_ts_chunks(
        self,
        tree: tree_sitter.Tree,
        content: str,
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> list[CodeChunk]:
        """Extract JavaScript/TypeScript chunks."""
        chunks = []
        lines = content.split("\n")
        root = tree.root_node
        
        # Function declarations
        func_query = """
        (function_declaration
            name: (identifier) @name
            parameters: (formal_parameters) @params
            body: (statement_block) @body) @function
        """

        # Arrow functions assigned to identifiers
        arrow_query = """
        (variable_declarator
            name: (identifier) @name
            value: (arrow_function) @function) @arrow
        """

        # Class definitions
        class_query = """
        (class_declaration
            name: (identifier) @name
            body: (class_body) @body) @class
        """

        try:
            lang_key = "typescript" if language == "typescript" else "javascript"
            if lang_key not in self._languages:
                return chunks

            lang = self._languages[lang_key]
            
            # Extract functions
            func_captures = self._run_query(lang, func_query, root)

            for node, tag in func_captures:
                if tag == "function":
                    chunk = self._js_function_to_chunk(
                        node, content, lines, file_path, language, repo_url, commit_hash
                    )
                    if chunk:
                        chunks.append(chunk)

            # Extract classes
            class_captures = self._run_query(lang, class_query, root)

            for node, tag in class_captures:
                if tag == "class":
                    chunk = self._js_class_to_chunk(
                        node, content, lines, file_path, language, repo_url, commit_hash
                    )
                    if chunk:
                        chunks.append(chunk)

        except Exception as e:
            logger.debug(f"Error in JS/TS query: {e}")

        return chunks

    def _js_function_to_chunk(
        self,
        node: tree_sitter.Node,
        content: str,
        lines: list[str],
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> CodeChunk | None:
        """Convert JS/TS function node to CodeChunk."""
        try:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            
            code_text = content[node.start_byte:node.end_byte]
            
            name_node = node.child_by_field_name("name")
            func_name = name_node.text.decode("utf8") if name_node else ""
            
            params_node = node.child_by_field_name("parameters")
            params_text = ""
            if params_node:
                params_text = content[params_node.start_byte:params_node.end_byte]
            
            signature = f"function {func_name}{params_text}"
            
            return CodeChunk(
                code_text=code_text,
                chunk_type=ChunkType.FUNCTION,
                file_path=file_path,
                language=language,
                start_line=start_line,
                end_line=end_line,
                fully_qualified_name=func_name,
                signature=signature,
                docstring="",
                parent_symbols=[],
                complexity_score=1,
                repo_url=repo_url,
                commit_hash=commit_hash,
            )
        except Exception as e:
            logger.debug(f"Error converting JS function: {e}")
            return None

    def _js_class_to_chunk(
        self,
        node: tree_sitter.Node,
        content: str,
        lines: list[str],
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> CodeChunk | None:
        """Convert JS/TS class node to CodeChunk."""
        try:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            
            code_text = content[node.start_byte:node.end_byte]
            
            name_node = node.child_by_field_name("name")
            class_name = name_node.text.decode("utf8") if name_node else ""
            
            return CodeChunk(
                code_text=code_text,
                chunk_type=ChunkType.CLASS,
                file_path=file_path,
                language=language,
                start_line=start_line,
                end_line=end_line,
                fully_qualified_name=class_name,
                signature=f"class {class_name}",
                docstring="",
                parent_symbols=[],
                complexity_score=1,
                repo_url=repo_url,
                commit_hash=commit_hash,
            )
        except Exception as e:
            logger.debug(f"Error converting JS class: {e}")
            return None

    def _extract_go_chunks(
        self,
        tree: tree_sitter.Tree,
        content: str,
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> list[CodeChunk]:
        """Extract Go chunks."""
        chunks = []
        lines = content.split("\n")
        root = tree.root_node

        # Function declarations
        func_query = """
        (function_declaration
            name: (identifier) @name
            body: (block) @body) @function
        """

        # Method declarations
        method_query = """
        (method_declaration
            receiver: (parameter_list (parameter_declaration name: (identifier)? @receiver_type))?
            name: (identifier) @name
            body: (block) @body) @method
        """

        try:
            if "go" not in self._languages:
                return chunks

            lang = self._languages["go"]
            
            # Extract functions
            func_captures = self._run_query(lang, func_query, root)

            for node, tag in func_captures:
                if tag == "function":
                    chunk = self._go_function_to_chunk(
                        node, content, lines, file_path, language, repo_url, commit_hash
                    )
                    if chunk:
                        chunks.append(chunk)

        except Exception as e:
            logger.debug(f"Error in Go query: {e}")

        return chunks

    def _go_function_to_chunk(
        self,
        node: tree_sitter.Node,
        content: str,
        lines: list[str],
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> CodeChunk | None:
        """Convert Go function node to CodeChunk."""
        try:
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            
            code_text = content[node.start_byte:node.end_byte]
            
            name_node = node.child_by_field_name("name")
            func_name = name_node.text.decode("utf8") if name_node else ""
            
            return CodeChunk(
                code_text=code_text,
                chunk_type=ChunkType.FUNCTION,
                file_path=file_path,
                language=language,
                start_line=start_line,
                end_line=end_line,
                fully_qualified_name=func_name,
                signature=f"func {func_name}",
                docstring="",
                parent_symbols=[],
                complexity_score=1,
                repo_url=repo_url,
                commit_hash=commit_hash,
            )
        except Exception as e:
            logger.debug(f"Error converting Go function: {e}")
            return None

    def _extract_generic_chunks(
        self,
        tree: tree_sitter.Tree,
        content: str,
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> list[CodeChunk]:
        """Extract generic chunks for unsupported languages."""
        # Fallback: create a single module-level chunk
        lines = content.split("\n")
        
        return [
            CodeChunk(
                code_text=content,
                chunk_type=ChunkType.MODULE,
                file_path=file_path,
                language=language,
                start_line=1,
                end_line=len(lines),
                fully_qualified_name=file_path.split("/")[-1].split("\\")[-1],
                signature="module",
                docstring="",
                parent_symbols=[],
                complexity_score=0,
                repo_url=repo_url,
                commit_hash=commit_hash,
            )
        ]

    def _extract_imports(self, content: str, language: str) -> list[str]:
        """Extract import statements from code."""
        imports = []
        
        if language == "python":
            # Match import x, from x import y
            import_pattern = r'^(?:import\s+[\w.]+|from\s+[\w.]+\s+import\s+.+)'
            for line in content.split("\n"):
                line = line.strip()
                if re.match(import_pattern, line):
                    imports.append(line)
        
        elif language in ("javascript", "typescript"):
            # Match import x from 'y', require()
            import_pattern = r'^(?:import\s+.*?from\s+["\'].*?["\']|const\s+\w+\s*=\s*require\()'
            for line in content.split("\n"):
                line = line.strip()
                if re.match(import_pattern, line):
                    imports.append(line)
        
        elif language == "go":
            # Match import "x", import ( ... )
            import_pattern = r'^(?:import\s+["\'].*?["\']|import\s*\()'
            for line in content.split("\n"):
                line = line.strip()
                if re.match(import_pattern, line):
                    imports.append(line)
        
        return imports

    def _fallback_parse(
        self,
        file_path: str,
        content: str,
        language: str,
        repo_url: str,
        commit_hash: str,
    ) -> list[CodeChunk]:
        """Fallback parsing when tree-sitter is unavailable."""
        lines = content.split("\n")
        
        # Try to detect functions using regex
        chunks = []
        
        # Python function pattern
        if language == "python":
            func_pattern = r'^(\s*)def\s+(\w+)\s*\('
            current_func = None
            func_start = 0
            func_indent = 0
            
            for i, line in enumerate(lines):
                match = re.match(func_pattern, line)
                if match:
                    # Save previous function
                    if current_func:
                        chunks.append(self._create_fallback_chunk(
                            lines[func_start:i], func_start + 1, i,
                            current_func, file_path, language, repo_url, commit_hash,
                            ChunkType.FUNCTION
                        ))
                    
                    current_func = match.group(2)
                    func_start = i
                    func_indent = len(match.group(1))
            
            # Don't forget the last function
            if current_func:
                chunks.append(self._create_fallback_chunk(
                    lines[func_start:], func_start + 1, len(lines),
                    current_func, file_path, language, repo_url, commit_hash,
                    ChunkType.FUNCTION
                ))
        
        # If no functions found, create a single module chunk
        if not chunks:
            chunks.append(CodeChunk(
                code_text=content,
                chunk_type=ChunkType.MODULE,
                file_path=file_path,
                language=language,
                start_line=1,
                end_line=len(lines),
                fully_qualified_name=file_path.split("/")[-1],
                signature="module",
                docstring="",
                parent_symbols=[],
                complexity_score=0,
                repo_url=repo_url,
                commit_hash=commit_hash,
            ))
        
        return chunks

    def _create_fallback_chunk(
        self,
        code_lines: list[str],
        start_line: int,
        end_line: int,
        name: str,
        file_path: str,
        language: str,
        repo_url: str,
        commit_hash: str,
        chunk_type: ChunkType,
    ) -> CodeChunk:
        """Create a chunk from fallback parsing."""
        code_text = "\n".join(code_lines)
        
        return CodeChunk(
            code_text=code_text,
            chunk_type=chunk_type,
            file_path=file_path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            fully_qualified_name=name,
            signature=f"def {name}" if chunk_type == ChunkType.FUNCTION else name,
            docstring="",
            parent_symbols=[],
            complexity_score=1,
            repo_url=repo_url,
            commit_hash=commit_hash,
        )
