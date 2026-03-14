"""Code parser using tree-sitter with regex fallback (SPEC-03 Section 3)."""

import logging
import re
import uuid
import warnings
from dataclasses import field

import tree_sitter_languages

from ..models import CodeElement, ElementKind

logger = logging.getLogger(__name__)

# Suppress tree-sitter deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="tree_sitter")

# tree-sitter queries per language
QUERIES: dict[str, dict[str, str]] = {
    "java": {
        "classes": "(class_declaration name: (identifier) @class.name) @class.def",
        "methods": "(method_declaration name: (identifier) @method.name) @method.def",
        "interfaces": "(interface_declaration name: (identifier) @interface.name) @interface.def",
    },
    "python": {
        "classes": "(class_definition name: (identifier) @class.name) @class.def",
        "functions": "(function_definition name: (identifier) @function.name) @function.def",
    },
    "typescript": {
        "classes": "(class_declaration name: (type_identifier) @class.name) @class.def",
        "functions": "(function_declaration name: (identifier) @function.name) @function.def",
        "interfaces": "(interface_declaration name: (type_identifier) @interface.name) @interface.def",
    },
}

KIND_MAP = {
    "classes": ElementKind.CLASS,
    "methods": ElementKind.METHOD,
    "functions": ElementKind.FUNCTION,
    "interfaces": ElementKind.INTERFACE,
}


class CodeParser:
    """Parse source code into CodeElement structures using tree-sitter."""

    def __init__(self):
        self._parsers: dict = {}
        self._languages: dict = {}

    def _get_parser(self, language: str):
        if language not in self._parsers:
            self._parsers[language] = tree_sitter_languages.get_parser(language)
            self._languages[language] = tree_sitter_languages.get_language(language)
        return self._parsers[language], self._languages[language]

    def parse(
        self, content: str, language: str, file_path: str, document_id: str
    ) -> list[CodeElement]:
        """Parse source code and extract code elements.

        Falls back to regex if tree-sitter queries are not available for the language.
        """
        if not content.strip():
            return []

        if language not in QUERIES:
            return RegexFallbackParser.parse(content, language, file_path, document_id)

        try:
            parser, ts_language = self._get_parser(language)
            content_bytes = content.encode("utf-8")
            tree = parser.parse(content_bytes)

            elements = []
            queries = QUERIES[language]

            for query_name, query_str in queries.items():
                kind = KIND_MAP[query_name]
                query = ts_language.query(query_str)
                captures = query.captures(tree.root_node)

                # Group captures by .def and .name
                defs = []
                names = {}
                for node, capture_name in captures:
                    if capture_name.endswith(".def"):
                        defs.append(node)
                    elif capture_name.endswith(".name"):
                        # Associate name with its parent def node
                        names[node.start_byte] = node

                for def_node in defs:
                    element = self._node_to_element(
                        def_node, kind, content_bytes, file_path, document_id, language
                    )
                    if element:
                        elements.append(element)

            self._resolve_parents(elements)
            return elements

        except Exception as e:
            logger.warning(f"tree-sitter parsing failed for {file_path}: {e}, falling back to regex")
            return RegexFallbackParser.parse(content, language, file_path, document_id)

    def _node_to_element(
        self,
        node,
        kind: ElementKind,
        content_bytes: bytes,
        file_path: str,
        document_id: str,
        language: str,
    ) -> CodeElement | None:
        """Convert a tree-sitter node to a CodeElement."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        name = content_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        # Extract first line as signature
        node_text = content_bytes[node.start_byte : node.end_byte].decode("utf-8")
        first_line = node_text.split("\n")[0].strip()

        # Extract visibility
        visibility = self._extract_visibility(node, content_bytes, language)

        # Extract docstring
        docstring = self._extract_docstring(node, content_bytes, language)

        # Extract annotations (Java)
        annotations = self._extract_annotations(node, content_bytes) if language == "java" else []

        return CodeElement(
            id=str(uuid.uuid4()),
            document_id=document_id,
            kind=kind,
            name=name,
            short_name=name,
            signature=first_line,
            visibility=visibility,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            docstring=docstring,
            annotations=annotations,
        )

    def _extract_visibility(self, node, content_bytes: bytes, language: str) -> str | None:
        """Extract visibility modifier from a node."""
        if language == "java":
            # Check modifiers child
            for child in node.children:
                if child.type == "modifiers":
                    mod_text = content_bytes[child.start_byte : child.end_byte].decode("utf-8")
                    for vis in ("public", "private", "protected"):
                        if vis in mod_text:
                            return vis
            return None
        elif language == "python":
            # Python convention: _name is private, __name is strongly private
            name_node = node.child_by_field_name("name")
            if name_node:
                name = content_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
                if name.startswith("__") and not name.endswith("__"):
                    return "private"
                if name.startswith("_"):
                    return "private"
            return "public"
        return None

    def _extract_docstring(self, node, content_bytes: bytes, language: str) -> str | None:
        """Extract docstring/comment preceding the element."""
        if language == "python":
            # Check for docstring as first expression in body
            body = node.child_by_field_name("body")
            if body and body.child_count > 0:
                first_stmt = body.children[0]
                if first_stmt.type == "expression_statement" and first_stmt.child_count > 0:
                    expr = first_stmt.children[0]
                    if expr.type == "string":
                        ds = content_bytes[expr.start_byte : expr.end_byte].decode("utf-8")
                        # Strip quotes
                        for quote in ('"""', "'''", '"', "'"):
                            if ds.startswith(quote) and ds.endswith(quote):
                                return ds[len(quote) : -len(quote)].strip()
                        return ds
            return self._extract_preceding_comments(node, content_bytes, "#")

        if language == "java":
            return self._extract_preceding_comments(node, content_bytes, "//", "/*", "/**", "*", "*/")

        if language == "typescript":
            return self._extract_preceding_comments(node, content_bytes, "//", "/*", "/**", "*", "*/")

        return None

    def _extract_preceding_comments(
        self, node, content_bytes: bytes, *prefixes: str
    ) -> str | None:
        """Search backward from the node for comment lines."""
        lines = content_bytes[: node.start_byte].decode("utf-8", errors="replace").split("\n")
        comment_lines = []
        # Search up to 20 lines back
        for line in reversed(lines[-20:]):
            stripped = line.strip()
            if not stripped:
                if comment_lines:
                    break
                continue
            if any(stripped.startswith(p) for p in prefixes):
                comment_lines.append(stripped)
            else:
                break

        if comment_lines:
            comment_lines.reverse()
            return "\n".join(comment_lines)
        return None

    def _extract_annotations(self, node, content_bytes: bytes) -> list[str]:
        """Extract Java annotations from modifiers."""
        annotations = []
        # Check preceding siblings and modifiers children
        for child in node.children:
            if child.type == "modifiers":
                for mod_child in child.children:
                    if mod_child.type in ("marker_annotation", "annotation"):
                        ann_text = content_bytes[
                            mod_child.start_byte : mod_child.end_byte
                        ].decode("utf-8")
                        annotations.append(ann_text)
        return annotations

    def _resolve_parents(self, elements: list[CodeElement]) -> None:
        """Establish parent-child relationships based on line ranges."""
        # Sort by start_line to process outer elements first
        elements.sort(key=lambda e: (e.start_line, -e.end_line))

        for i, child in enumerate(elements):
            if child.kind in (ElementKind.METHOD, ElementKind.FUNCTION):
                # Find the innermost containing class/interface
                for j in range(i - 1, -1, -1):
                    parent = elements[j]
                    if (
                        parent.kind in (ElementKind.CLASS, ElementKind.INTERFACE)
                        and parent.start_line <= child.start_line
                        and parent.end_line >= child.end_line
                    ):
                        child.parent_id = parent.id
                        child.name = f"{parent.name}.{child.short_name}"
                        break


class RegexFallbackParser:
    """Simple regex-based parser for languages without tree-sitter queries."""

    PATTERNS = {
        "class": (r"(?:public\s+)?(?:abstract\s+)?class\s+(\w+)", ElementKind.CLASS),
        "function": (r"(?:def|function|func)\s+(\w+)\s*\(", ElementKind.FUNCTION),
        "interface": (r"interface\s+(\w+)", ElementKind.INTERFACE),
    }

    @staticmethod
    def parse(
        content: str, language: str, file_path: str, document_id: str
    ) -> list[CodeElement]:
        """Parse code using regex patterns."""
        elements = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            for pattern_name, (pattern, kind) in RegexFallbackParser.PATTERNS.items():
                match = re.search(pattern, line)
                if match:
                    name = match.group(1)
                    elements.append(
                        CodeElement(
                            id=str(uuid.uuid4()),
                            document_id=document_id,
                            kind=kind,
                            name=name,
                            short_name=name,
                            signature=line.strip(),
                            file_path=file_path,
                            start_line=line_num,
                            end_line=line_num,
                        )
                    )
        return elements
