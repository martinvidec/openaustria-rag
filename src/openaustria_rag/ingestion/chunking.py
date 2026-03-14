"""Semantic chunking service for code, documentation, and config files (SPEC-03 Section 4)."""

import uuid

from ..connectors.utils import detect_language
from ..models import Chunk, ChunkMetadata, CodeElement, ElementKind


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return len(text) // 4


class ChunkingService:
    """Create semantic chunks from documents."""

    def __init__(
        self,
        code_max_tokens: int = 2048,
        doc_max_tokens: int = 1024,
        doc_min_tokens: int = 64,
        doc_overlap_tokens: int = 128,
        config_max_tokens: int = 2048,
        include_context_header: bool = True,
    ):
        self.code_max_tokens = code_max_tokens
        self.doc_max_tokens = doc_max_tokens
        self.doc_min_tokens = doc_min_tokens
        self.doc_overlap_tokens = doc_overlap_tokens
        self.config_max_tokens = config_max_tokens
        self.include_context_header = include_context_header

    def chunk(
        self,
        content: str,
        content_type: str,
        file_path: str,
        document_id: str = "",
        language: str | None = None,
        code_elements: list[CodeElement] | None = None,
    ) -> list[Chunk]:
        """Route to the appropriate chunking strategy."""
        if content_type == "code" and code_elements:
            return self._chunk_code(content, file_path, document_id, code_elements)
        elif content_type == "documentation":
            return self._chunk_documentation(content, file_path, document_id)
        else:
            return self._chunk_simple(content, file_path, document_id, content_type)

    def _chunk_code(
        self,
        content: str,
        file_path: str,
        document_id: str,
        code_elements: list[CodeElement],
    ) -> list[Chunk]:
        """Chunk along code structure boundaries (tree-sitter-based)."""
        chunks: list[Chunk] = []
        lines = content.split("\n")
        covered_lines: set[int] = set()

        top_level = sorted(
            [e for e in code_elements if e.parent_id is None],
            key=lambda e: e.start_line,
        )

        for element in top_level:
            start = element.start_line - 1  # 0-based
            end = element.end_line
            element_content = "\n".join(lines[start:end])

            if self.include_context_header:
                header = f"# File: {file_path}\n# Element: {element.name} ({element.kind.value})\n\n"
                element_content = header + element_content

            token_count = _estimate_tokens(element_content)

            if token_count <= self.code_max_tokens:
                chunks.append(Chunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    content=element_content,
                    chunk_index=len(chunks),
                    token_count=token_count,
                    metadata=ChunkMetadata(
                        source_type="code",
                        language=detect_language(file_path) or "",
                        file_path=file_path,
                        element_type=element.kind.value,
                        element_name=element.name,
                        start_line=element.start_line,
                        end_line=element.end_line,
                    ),
                ))
            else:
                # Element too large: chunk children individually
                children = [e for e in code_elements if e.parent_id == element.id]
                if children:
                    for child in sorted(children, key=lambda c: c.start_line):
                        child_start = child.start_line - 1
                        child_end = child.end_line
                        child_content = "\n".join(lines[child_start:child_end])

                        if self.include_context_header:
                            header = f"# File: {file_path}\n# Element: {child.name} ({child.kind.value})\n\n"
                            child_content = header + child_content

                        chunks.append(Chunk(
                            id=str(uuid.uuid4()),
                            document_id=document_id,
                            content=child_content,
                            chunk_index=len(chunks),
                            token_count=_estimate_tokens(child_content),
                            metadata=ChunkMetadata(
                                source_type="code",
                                language=detect_language(file_path) or "",
                                file_path=file_path,
                                element_type=child.kind.value,
                                element_name=child.name,
                                parent_element=element.short_name,
                                start_line=child.start_line,
                                end_line=child.end_line,
                            ),
                        ))
                else:
                    # No children: split by token boundary
                    for sub in _split_with_overlap(
                        element_content, self.code_max_tokens, self.doc_overlap_tokens
                    ):
                        chunks.append(Chunk(
                            id=str(uuid.uuid4()),
                            document_id=document_id,
                            content=sub,
                            chunk_index=len(chunks),
                            token_count=_estimate_tokens(sub),
                            metadata=ChunkMetadata(
                                source_type="code",
                                file_path=file_path,
                                element_type=element.kind.value,
                                element_name=element.name,
                            ),
                        ))

            covered_lines.update(range(start, end))

        # Uncovered lines (imports, etc.) as additional chunk
        uncovered = [
            line for i, line in enumerate(lines)
            if i not in covered_lines and line.strip()
        ]
        if uncovered and _estimate_tokens("\n".join(uncovered)) >= 32:
            uncovered_content = "\n".join(uncovered)
            if self.include_context_header:
                uncovered_content = f"# File: {file_path}\n# Element: (file-level declarations)\n\n" + uncovered_content
            chunks.append(Chunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                content=uncovered_content,
                chunk_index=len(chunks),
                token_count=_estimate_tokens(uncovered_content),
                metadata=ChunkMetadata(
                    source_type="code",
                    file_path=file_path,
                    element_type="file_level",
                    element_name=file_path,
                ),
            ))

        return chunks

    def _chunk_documentation(
        self, content: str, file_path: str, document_id: str
    ) -> list[Chunk]:
        """Chunk along Markdown headers."""
        chunks: list[Chunk] = []
        sections = _split_by_headers(content)

        for section in sections:
            token_count = _estimate_tokens(section["content"])

            if token_count < self.doc_min_tokens:
                continue

            if token_count <= self.doc_max_tokens:
                chunks.append(Chunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    content=section["content"],
                    chunk_index=len(chunks),
                    token_count=token_count,
                    metadata=ChunkMetadata(
                        source_type="documentation",
                        language="markdown",
                        file_path=file_path,
                        element_type="section",
                        element_name=section.get("header", file_path),
                    ),
                ))
            else:
                for sub in _split_with_overlap(
                    section["content"], self.doc_max_tokens, self.doc_overlap_tokens
                ):
                    chunks.append(Chunk(
                        id=str(uuid.uuid4()),
                        document_id=document_id,
                        content=sub,
                        chunk_index=len(chunks),
                        token_count=_estimate_tokens(sub),
                        metadata=ChunkMetadata(
                            source_type="documentation",
                            language="markdown",
                            file_path=file_path,
                            element_type="section",
                            element_name=section.get("header", file_path),
                        ),
                    ))

        return chunks

    def _chunk_simple(
        self, content: str, file_path: str, document_id: str, content_type: str
    ) -> list[Chunk]:
        """Simple chunking for config files etc."""
        token_count = _estimate_tokens(content)
        if token_count <= self.config_max_tokens:
            return [Chunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                content=content,
                chunk_index=0,
                token_count=token_count,
                metadata=ChunkMetadata(
                    source_type=content_type,
                    file_path=file_path,
                    element_type="file",
                    element_name=file_path,
                ),
            )]

        result = []
        for sub in _split_with_overlap(
            content, self.config_max_tokens, self.doc_overlap_tokens
        ):
            result.append(Chunk(
                id=str(uuid.uuid4()),
                document_id=document_id,
                content=sub,
                chunk_index=len(result),
                token_count=_estimate_tokens(sub),
                metadata=ChunkMetadata(
                    source_type=content_type,
                    file_path=file_path,
                    element_type="file",
                    element_name=file_path,
                ),
            ))
        return result


def _split_by_headers(content: str) -> list[dict]:
    """Split Markdown content at H1/H2/H3 headers."""
    sections: list[dict] = []
    current_header = ""
    current_lines: list[str] = []

    for line in content.split("\n"):
        if line.startswith(("# ", "## ", "### ")):
            if current_lines:
                sections.append({
                    "header": current_header,
                    "content": "\n".join(current_lines),
                })
            current_header = line.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({
            "header": current_header,
            "content": "\n".join(current_lines),
        })

    return sections


def _split_with_overlap(
    content: str, max_tokens: int, overlap_tokens: int
) -> list[str]:
    """Split text into chunks with overlap between paragraphs."""
    paragraphs = content.split("\n\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)
        if current_tokens + para_tokens > max_tokens and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            # Keep trailing paragraphs for overlap
            overlap_chunk: list[str] = []
            overlap_count = 0
            for p in reversed(current_chunk):
                pt = _estimate_tokens(p)
                if overlap_count + pt > overlap_tokens:
                    break
                overlap_chunk.insert(0, p)
                overlap_count += pt
            current_chunk = overlap_chunk
            current_tokens = overlap_count
        current_chunk.append(para)
        current_tokens += para_tokens

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks
