"""Tests for the SQLite persistence layer (SPEC-01)."""

import uuid

import pytest

from openaustria_rag.db import MetadataDB
from openaustria_rag.models import (
    ChatMessage,
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


@pytest.fixture
def db(tmp_path):
    d = MetadataDB(db_path=tmp_path / "test.db")
    yield d
    d.close()


def _uid():
    return str(uuid.uuid4())


def _make_project(**kwargs):
    defaults = dict(id=_uid(), name="Test Project")
    defaults.update(kwargs)
    return Project(**defaults)


def _make_source(project_id, **kwargs):
    defaults = dict(
        id=_uid(), project_id=project_id,
        source_type=SourceType.GIT, name="repo",
        config={"url": "https://example.com/repo.git"},
    )
    defaults.update(kwargs)
    return Source(**defaults)


def _make_document(source_id, **kwargs):
    defaults = dict(
        id=_uid(), source_id=source_id,
        content_type=ContentType.CODE, file_path="src/main.py",
        content_hash="abc123",
    )
    defaults.update(kwargs)
    return Document(**defaults)


class TestProjectCRUD:
    def test_save_and_get(self, db):
        p = _make_project()
        db.save_project(p)
        result = db.get_project(p.id)
        assert result is not None
        assert result.name == p.name
        assert result.status == ProjectStatus.CREATED

    def test_get_nonexistent(self, db):
        assert db.get_project("nonexistent") is None

    def test_get_all_projects(self, db):
        db.save_project(_make_project(name="A"))
        db.save_project(_make_project(name="B"))
        assert len(db.get_all_projects()) == 2

    def test_delete_project(self, db):
        p = _make_project()
        db.save_project(p)
        db.delete_project(p.id)
        assert db.get_project(p.id) is None

    def test_update_project(self, db):
        p = _make_project()
        db.save_project(p)
        p.status = ProjectStatus.READY
        db.save_project(p)
        result = db.get_project(p.id)
        assert result.status == ProjectStatus.READY

    def test_settings_json_roundtrip(self, db):
        p = _make_project(settings={"chunk_size": 512, "languages": ["java"]})
        db.save_project(p)
        result = db.get_project(p.id)
        assert result.settings == {"chunk_size": 512, "languages": ["java"]}


class TestSourceCRUD:
    def test_save_and_get(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        result = db.get_source(s.id)
        assert result is not None
        assert result.source_type == SourceType.GIT

    def test_get_sources_by_project(self, db):
        p = _make_project()
        db.save_project(p)
        db.save_source(_make_source(p.id, name="repo1"))
        db.save_source(_make_source(p.id, name="repo2"))
        sources = db.get_sources_by_project(p.id)
        assert len(sources) == 2

    def test_delete_source(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        db.delete_source(s.id)
        assert db.get_source(s.id) is None


class TestDocumentCRUD:
    def test_save_and_get(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id)
        db.save_document(d)
        result = db.get_document(d.id)
        assert result is not None
        assert result.content_hash == "abc123"

    def test_document_unchanged(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id, content_hash="hash1")
        db.save_document(d)
        assert db.document_unchanged(d.id, "hash1") is True
        assert db.document_unchanged(d.id, "hash2") is False

    def test_document_unchanged_nonexistent(self, db):
        assert db.document_unchanged("nonexistent", "hash") is False

    def test_delete_documents_by_source(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id)
        db.save_document(d)
        db.delete_documents_by_source(s.id)
        assert db.get_document(d.id) is None


class TestCodeElementsCRUD:
    def test_save_and_get_by_project(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id)
        db.save_document(d)
        elements = [
            CodeElement(
                id=_uid(), document_id=d.id, kind=ElementKind.CLASS,
                name="MyClass", short_name="MyClass", file_path="a.py",
                start_line=1, end_line=50,
                annotations=["@Entity"], implements=["Serializable"],
            ),
            CodeElement(
                id=_uid(), document_id=d.id, kind=ElementKind.METHOD,
                name="MyClass.doStuff", short_name="doStuff", file_path="a.py",
                start_line=10, end_line=20, visibility="public",
            ),
        ]
        db.save_code_elements(elements)
        result = db.get_code_elements_by_project(p.id)
        assert len(result) == 2
        cls = [e for e in result if e.kind == ElementKind.CLASS][0]
        assert cls.annotations == ["@Entity"]
        assert cls.implements == ["Serializable"]

    def test_delete_code_elements(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id)
        db.save_document(d)
        db.save_code_elements([
            CodeElement(
                id=_uid(), document_id=d.id, kind=ElementKind.FUNCTION,
                name="func", short_name="func", file_path="b.py",
                start_line=1, end_line=5,
            )
        ])
        db.delete_code_elements(d.id)
        assert db.get_code_elements_by_project(p.id) == []


class TestGapReportCRUD:
    def test_save_and_get_latest(self, db):
        p = _make_project()
        db.save_project(p)
        report = GapReport(
            id=_uid(), project_id=p.id,
            summary=GapSummary(total_code_elements=10, undocumented=3),
        )
        db.save_gap_report(report)
        items = [
            GapItem(
                id=_uid(), report_id=report.id,
                gap_type=GapType.UNDOCUMENTED, severity=Severity.HIGH,
                code_element_name="MyClass", file_path="a.py",
            )
        ]
        db.save_gap_items(items)
        result = db.get_latest_gap_report(p.id)
        assert result is not None
        assert result.summary.total_code_elements == 10
        assert len(result.gaps) == 1
        assert result.gaps[0].gap_type == GapType.UNDOCUMENTED

    def test_false_positives(self, db):
        p = _make_project()
        db.save_project(p)
        report = GapReport(id=_uid(), project_id=p.id)
        db.save_gap_report(report)
        item = GapItem(
            id=_uid(), report_id=report.id,
            gap_type=GapType.UNDOCUMENTED, severity=Severity.LOW,
        )
        db.save_gap_items([item])
        db.update_gap_item(item.id, is_false_positive=True)
        fps = db.get_false_positives(p.id)
        assert len(fps) == 1
        assert fps[0].is_false_positive is True


class TestChatMessageCRUD:
    def test_save_and_get_history(self, db):
        p = _make_project()
        db.save_project(p)
        session = _uid()
        db.save_chat_message(ChatMessage(
            id=_uid(), project_id=p.id, session_id=session,
            role=MessageRole.USER, content="Hello",
            sources=["chunk1", "chunk2"],
        ))
        db.save_chat_message(ChatMessage(
            id=_uid(), project_id=p.id, session_id=session,
            role=MessageRole.ASSISTANT, content="Hi there",
        ))
        history = db.get_chat_history(session)
        assert len(history) == 2
        assert history[0].role == MessageRole.USER
        assert history[0].sources == ["chunk1", "chunk2"]
        assert history[1].role == MessageRole.ASSISTANT


class TestCascadeDeletes:
    def test_delete_project_cascades_to_sources(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        db.delete_project(p.id)
        assert db.get_source(s.id) is None

    def test_delete_source_cascades_to_documents(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id)
        db.save_document(d)
        db.delete_source(s.id)
        assert db.get_document(d.id) is None

    def test_delete_document_cascades_to_code_elements(self, db):
        p = _make_project()
        db.save_project(p)
        s = _make_source(p.id)
        db.save_source(s)
        d = _make_document(s.id)
        db.save_document(d)
        db.save_code_elements([
            CodeElement(
                id=_uid(), document_id=d.id, kind=ElementKind.CLASS,
                name="X", short_name="X", file_path="x.py",
                start_line=1, end_line=10,
            )
        ])
        db.delete_documents_by_source(s.id)
        assert db.get_code_elements_by_project(p.id) == []

    def test_delete_project_cascades_to_gap_reports(self, db):
        p = _make_project()
        db.save_project(p)
        report = GapReport(id=_uid(), project_id=p.id)
        db.save_gap_report(report)
        db.save_gap_items([
            GapItem(
                id=_uid(), report_id=report.id,
                gap_type=GapType.CONSISTENT, severity=Severity.LOW,
            )
        ])
        db.delete_project(p.id)
        assert db.get_latest_gap_report(p.id) is None

    def test_delete_project_cascades_to_chat(self, db):
        p = _make_project()
        db.save_project(p)
        session = _uid()
        db.save_chat_message(ChatMessage(
            id=_uid(), project_id=p.id, session_id=session,
            role=MessageRole.USER, content="test",
        ))
        db.delete_project(p.id)
        assert db.get_chat_history(session) == []
