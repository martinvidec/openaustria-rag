"""Tests for the chunking service (SPEC-03 Section 4)."""

import pytest

from openaustria_rag.ingestion.chunking import (
    ChunkingService,
    _estimate_tokens,
    _split_by_headers,
    _split_with_overlap,
)
from openaustria_rag.models import Chunk, CodeElement, ElementKind


@pytest.fixture
def service():
    return ChunkingService()


def _make_element(
    name, kind=ElementKind.CLASS, start=1, end=10, parent_id=None, doc_id="doc1"
):
    return CodeElement(
        id=f"elem-{name}",
        document_id=doc_id,
        kind=kind,
        name=name,
        short_name=name.split(".")[-1],
        file_path="test.py",
        start_line=start,
        end_line=end,
        parent_id=parent_id,
    )


PYTHON_CODE = """\
import os
import sys

class UserService:
    def get_users(self):
        return []

    def create_user(self, name):
        return {"name": name}

def standalone():
    pass"""


class TestCodeChunking:
    def test_chunks_along_class_boundary(self, service):
        elements = [
            _make_element("UserService", ElementKind.CLASS, 4, 10),
            _make_element("UserService.get_users", ElementKind.FUNCTION, 5, 6, parent_id="elem-UserService"),
            _make_element("UserService.create_user", ElementKind.FUNCTION, 8, 9, parent_id="elem-UserService"),
            _make_element("standalone", ElementKind.FUNCTION, 12, 13),
        ]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "doc1", code_elements=elements)
        assert len(chunks) >= 2  # At least class + standalone

    def test_context_header_present(self, service):
        elements = [_make_element("UserService", ElementKind.CLASS, 4, 10)]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "doc1", code_elements=elements)
        assert chunks[0].content.startswith("# File: service.py")
        assert "# Element: UserService (class)" in chunks[0].content

    def test_context_header_disabled(self):
        service = ChunkingService(include_context_header=False)
        elements = [_make_element("UserService", ElementKind.CLASS, 4, 10)]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "doc1", code_elements=elements)
        assert not chunks[0].content.startswith("# File:")

    def test_metadata_populated(self, service):
        elements = [_make_element("UserService", ElementKind.CLASS, 4, 10)]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "doc1", code_elements=elements)
        meta = chunks[0].metadata
        assert meta.source_type == "code"
        assert meta.file_path == "service.py"
        assert meta.element_type == "class"
        assert meta.element_name == "UserService"
        assert meta.start_line == 4

    def test_uncovered_lines_collected(self, service):
        elements = [_make_element("UserService", ElementKind.CLASS, 4, 10)]
        # Lines 1-3 (imports) and 12-13 (standalone) are uncovered
        code = "import os\nimport sys\nimport json\n\n" + "x = 1\n" * 30 + "\nclass UserService:\n    pass\n"
        elements = [_make_element("UserService", ElementKind.CLASS, 36, 37)]
        chunks = service.chunk(code, "code", "service.py", "doc1", code_elements=elements)
        file_level = [c for c in chunks if c.metadata.element_type == "file_level"]
        assert len(file_level) == 1

    def test_large_element_splits_children(self):
        service = ChunkingService(code_max_tokens=10)  # Very small limit
        elements = [
            _make_element("BigClass", ElementKind.CLASS, 4, 10),
            _make_element("BigClass.method1", ElementKind.FUNCTION, 5, 6, parent_id="elem-BigClass"),
            _make_element("BigClass.method2", ElementKind.FUNCTION, 8, 9, parent_id="elem-BigClass"),
        ]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "doc1", code_elements=elements)
        method_chunks = [c for c in chunks if c.metadata.element_type == "function"]
        assert len(method_chunks) == 2

    def test_document_id_preserved(self, service):
        elements = [_make_element("UserService", ElementKind.CLASS, 4, 10)]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "my-doc", code_elements=elements)
        for c in chunks:
            assert c.document_id == "my-doc"

    def test_chunk_index_sequential(self, service):
        elements = [
            _make_element("UserService", ElementKind.CLASS, 4, 10),
            _make_element("standalone", ElementKind.FUNCTION, 12, 13),
        ]
        chunks = service.chunk(PYTHON_CODE, "code", "service.py", "doc1", code_elements=elements)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i


MARKDOWN_DOC = """\
# Introduction

This is the intro paragraph with enough text to pass the minimum token threshold for chunking purposes. The system is designed to handle large-scale document processing with multiple connectors and a modular pipeline architecture that supports incremental updates and efficient resource usage across different deployment scenarios.

## Architecture

The system uses a layered architecture with multiple components that interact through well-defined interfaces. Each layer is responsible for a specific set of operations and communicates with adjacent layers through typed data contracts. The architecture supports both local and cloud deployment models with configurable backends for storage and compute.

### Components

Each component is responsible for a specific domain function and communicates via message passing. Components can be deployed independently and scaled horizontally to handle increased load patterns.

## Deployment

The application is deployed using Docker containers orchestrated by Kubernetes in production. Configuration is managed through environment variables and YAML files that support per-environment overrides for development, staging, and production environments.
"""


class TestDocumentationChunking:
    def test_splits_at_headers(self, service):
        chunks = service.chunk(MARKDOWN_DOC, "documentation", "README.md", "doc1")
        assert len(chunks) >= 2

    def test_section_metadata(self, service):
        chunks = service.chunk(MARKDOWN_DOC, "documentation", "README.md", "doc1")
        headers = [c.metadata.element_name for c in chunks]
        assert "Introduction" in headers or "Architecture" in headers

    def test_skips_short_sections(self):
        service = ChunkingService(doc_min_tokens=1000)  # High threshold
        chunks = service.chunk(MARKDOWN_DOC, "documentation", "README.md", "doc1")
        assert len(chunks) == 0  # All sections too short

    def test_large_section_splits_with_overlap(self):
        service = ChunkingService(doc_max_tokens=20, doc_overlap_tokens=5)
        long_section = "# Big Section\n\n" + "\n\n".join(
            f"Paragraph {i} with some content to make it longer." for i in range(20)
        )
        chunks = service.chunk(long_section, "documentation", "doc.md", "doc1")
        assert len(chunks) > 1

    def test_source_type_is_documentation(self, service):
        chunks = service.chunk(MARKDOWN_DOC, "documentation", "README.md", "doc1")
        for c in chunks:
            assert c.metadata.source_type == "documentation"


class TestConfigChunking:
    def test_small_config_single_chunk(self, service):
        config = "key: value\nother: data\n"
        chunks = service.chunk(config, "config", "config.yaml", "doc1")
        assert len(chunks) == 1
        assert chunks[0].content == config
        assert chunks[0].metadata.element_type == "file"

    def test_large_config_splits(self):
        service = ChunkingService(config_max_tokens=20)
        config = "\n\n".join(f"key_{i}: value_{i}" for i in range(50))
        chunks = service.chunk(config, "config", "big.yaml", "doc1")
        assert len(chunks) > 1

    def test_code_without_elements_uses_simple(self, service):
        code = "x = 1\ny = 2\n"
        chunks = service.chunk(code, "code", "script.py", "doc1", code_elements=None)
        assert len(chunks) == 1  # Falls back to simple chunking


class TestHelpers:
    def test_estimate_tokens(self):
        assert _estimate_tokens("") == 0
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 100) == 25

    def test_split_by_headers(self):
        md = "# A\nContent A\n## B\nContent B\n"
        sections = _split_by_headers(md)
        assert len(sections) == 2
        assert sections[0]["header"] == "A"
        assert sections[1]["header"] == "B"

    def test_split_by_headers_no_headers(self):
        sections = _split_by_headers("Just plain text\nMore text")
        assert len(sections) == 1
        assert sections[0]["header"] == ""

    def test_split_with_overlap(self):
        text = "\n\n".join(f"Paragraph {i} content." for i in range(10))
        chunks = _split_with_overlap(text, max_tokens=30, overlap_tokens=10)
        assert len(chunks) > 1
        # Check overlap: last paragraph of chunk N should appear in chunk N+1
        if len(chunks) >= 2:
            last_para_of_first = chunks[0].split("\n\n")[-1]
            assert last_para_of_first in chunks[1]

    def test_split_with_overlap_small_content(self):
        chunks = _split_with_overlap("small text", max_tokens=100, overlap_tokens=10)
        assert len(chunks) == 1
        assert chunks[0] == "small text"

    def test_token_count_populated(self, service=ChunkingService()):
        chunks = service.chunk("key: value\n", "config", "c.yaml", "doc1")
        assert chunks[0].token_count > 0
