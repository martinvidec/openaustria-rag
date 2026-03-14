"""Tests for data models (SPEC-01)."""

import uuid

from openaustria_rag.models import (
    ChatMessage,
    Chunk,
    ChunkMetadata,
    CodeElement,
    ContentType,
    Document,
    ElementKind,
    GapItem,
    GapReport,
    GapSummary,
    GapType,
    MessageRole,
    Project,
    ProjectStatus,
    Severity,
    Source,
    SourceStatus,
    SourceType,
)


class TestEnums:
    def test_project_status_values(self):
        assert ProjectStatus.CREATED.value == "created"
        assert ProjectStatus.READY.value == "ready"

    def test_source_type_values(self):
        assert SourceType.GIT.value == "git"
        assert SourceType.ZIP.value == "zip"
        assert SourceType.CONFLUENCE.value == "confluence"

    def test_content_type_values(self):
        assert ContentType.CODE.value == "code"
        assert ContentType.DOCUMENTATION.value == "documentation"

    def test_element_kind_values(self):
        assert ElementKind.CLASS.value == "class"
        assert ElementKind.API_ENDPOINT.value == "api_endpoint"

    def test_gap_type_values(self):
        assert GapType.UNDOCUMENTED.value == "undocumented"
        assert GapType.DIVERGENT.value == "divergent"

    def test_severity_values(self):
        assert Severity.LOW.value == "low"
        assert Severity.CRITICAL.value == "critical"


class TestModelDefaults:
    def test_project_defaults(self):
        p = Project(id="1", name="Test")
        assert p.status == ProjectStatus.CREATED
        assert p.description == ""
        assert p.settings == {}
        assert p.created_at is not None

    def test_source_defaults(self):
        s = Source(id="1", project_id="p1", source_type=SourceType.GIT, name="repo")
        assert s.status == SourceStatus.CONFIGURED
        assert s.last_sync_at is None
        assert s.config == {}

    def test_document_defaults(self):
        d = Document(
            id="1", source_id="s1", content_type=ContentType.CODE,
            file_path="a.py", content_hash="abc"
        )
        assert d.language is None
        assert d.metadata == {}

    def test_chunk_defaults(self):
        c = Chunk(id="1", document_id="d1", content="hello")
        assert c.embedding is None
        assert c.chunk_index == 0
        assert c.token_count == 0
        assert isinstance(c.metadata, ChunkMetadata)

    def test_code_element_defaults(self):
        ce = CodeElement(
            id="1", document_id="d1", kind=ElementKind.CLASS,
            name="MyClass", short_name="MyClass"
        )
        assert ce.annotations == []
        assert ce.implements == []
        assert ce.extends is None

    def test_gap_summary_defaults(self):
        gs = GapSummary()
        assert gs.total_code_elements == 0
        assert gs.documentation_coverage == 0.0

    def test_gap_item_defaults(self):
        gi = GapItem(
            id="1", report_id="r1",
            gap_type=GapType.UNDOCUMENTED, severity=Severity.MEDIUM
        )
        assert gi.is_false_positive is False
        assert gi.similarity_score is None

    def test_chat_message_defaults(self):
        cm = ChatMessage(
            id="1", project_id="p1", session_id="s1",
            role=MessageRole.USER, content="hello"
        )
        assert cm.sources == []
