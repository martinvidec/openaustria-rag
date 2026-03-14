"""Tests for the ingestion pipeline orchestrator (SPEC-03)."""

from unittest.mock import MagicMock

import pytest

from openaustria_rag.connectors.base import RawDocument
from openaustria_rag.db import MetadataDB
from openaustria_rag.ingestion.chunking import ChunkingService
from openaustria_rag.ingestion.code_parser import CodeParser
from openaustria_rag.ingestion.pipeline import IngestionPipeline, IngestionResult
from openaustria_rag.models import (
    ContentType,
    Project,
    ProjectStatus,
    Source,
    SourceStatus,
    SourceType,
)
from openaustria_rag.retrieval.vector_store import VectorStoreService


@pytest.fixture
def db(tmp_path):
    d = MetadataDB(db_path=tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def vector_store(tmp_path):
    return VectorStoreService(persist_path=tmp_path / "chromadb")


@pytest.fixture
def mock_embedding():
    svc = MagicMock()
    svc.embed_batch.return_value = [[0.1, 0.2, 0.3]]
    svc.embed_single.return_value = [0.1, 0.2, 0.3]

    def batch_side_effect(texts):
        return [[0.1, 0.2, 0.3]] * len(texts)

    svc.embed_batch.side_effect = batch_side_effect
    return svc


@pytest.fixture
def pipeline(db, vector_store, mock_embedding):
    return IngestionPipeline(
        db=db,
        code_parser=CodeParser(),
        chunking_service=ChunkingService(),
        embedding_service=mock_embedding,
        vector_store=vector_store,
    )


@pytest.fixture
def project(db):
    p = Project(id="proj1", name="Test Project")
    db.save_project(p)
    return p


@pytest.fixture
def source(db, project):
    s = Source(
        id="src1",
        project_id=project.id,
        source_type=SourceType.GIT,
        name="test-repo",
        config={"url": "https://example.com/repo.git"},
    )
    db.save_source(s)
    return s


def _raw_docs():
    """Generate test RawDocuments."""
    yield RawDocument(
        content="class UserService:\n    def get_users(self):\n        return []\n",
        file_path="src/service.py",
        content_type="code",
        language="python",
        size_bytes=60,
    )
    yield RawDocument(
        content="# README\n\nThis is the project documentation with enough content to pass the minimum token threshold for the chunking service.\n",
        file_path="README.md",
        content_type="documentation",
        language="markdown",
        size_bytes=120,
    )
    yield RawDocument(
        content="key: value\nother: data\n",
        file_path="config.yaml",
        content_type="config",
        language="yaml",
        size_bytes=22,
    )


class TestIngestionPipeline:
    def test_processes_all_documents(self, pipeline, project, source):
        result = pipeline.ingest(_raw_docs(), project.id, source.id)
        assert result.documents_processed == 3
        assert result.documents_skipped == 0
        assert result.documents_failed == 0
        assert result.chunks_created > 0

    def test_creates_document_records(self, pipeline, project, source, db):
        pipeline.ingest(_raw_docs(), project.id, source.id)
        # Check documents were saved
        doc = db._conn.execute(
            "SELECT * FROM documents WHERE source_id = ?", (source.id,)
        ).fetchall()
        assert len(doc) == 3

    def test_extracts_code_elements(self, pipeline, project, source, db):
        pipeline.ingest(_raw_docs(), project.id, source.id)
        elements = db.get_code_elements_by_project(project.id)
        assert len(elements) > 0
        names = {e.short_name for e in elements}
        assert "UserService" in names

    def test_chunks_in_chromadb(self, pipeline, project, source, vector_store):
        pipeline.ingest(_raw_docs(), project.id, source.id)
        # Check code collection
        code_col = vector_store.get_or_create_collection(
            vector_store.collection_name(project.id, "code")
        )
        assert code_col.count() > 0

    def test_embedding_called(self, pipeline, project, source, mock_embedding):
        pipeline.ingest(_raw_docs(), project.id, source.id)
        assert mock_embedding.embed_batch.call_count > 0

    def test_result_dataclass(self):
        r = IngestionResult()
        assert r.documents_processed == 0
        assert r.errors == []


class TestChangeDetection:
    def test_skips_unchanged_documents(self, pipeline, project, source):
        # First ingest
        result1 = pipeline.ingest(_raw_docs(), project.id, source.id)
        assert result1.documents_processed == 3

        # Second ingest with same content
        result2 = pipeline.ingest(_raw_docs(), project.id, source.id)
        assert result2.documents_skipped == 3
        assert result2.documents_processed == 0

    def test_reindexes_changed_documents(self, pipeline, project, source):
        # First ingest
        pipeline.ingest(_raw_docs(), project.id, source.id)

        # Changed document
        def changed_docs():
            yield RawDocument(
                content="class UserService:\n    def get_users(self):\n        return ['updated']\n",
                file_path="src/service.py",  # Same path, different content
                content_type="code",
                language="python",
                size_bytes=70,
            )

        result = pipeline.ingest(changed_docs(), project.id, source.id)
        assert result.documents_processed == 1
        assert result.documents_skipped == 0


class TestErrorHandling:
    def test_single_failure_does_not_stop_pipeline(self, pipeline, project, source):
        def docs_with_bad():
            yield RawDocument(
                content="good content for config file\n",
                file_path="good.yaml",
                content_type="config",
                language="yaml",
                size_bytes=30,
            )
            yield RawDocument(
                content=None,  # This will cause an error
                file_path="bad.py",
                content_type="code",
                language="python",
                size_bytes=0,
            )
            yield RawDocument(
                content="another good config\n",
                file_path="good2.yaml",
                content_type="config",
                language="yaml",
                size_bytes=20,
            )

        result = pipeline.ingest(docs_with_bad(), project.id, source.id)
        assert result.documents_processed == 2
        assert result.documents_failed == 1
        assert len(result.errors) == 1

    def test_errors_list_contains_file_path(self, pipeline, project, source):
        def bad_doc():
            yield RawDocument(
                content=None,
                file_path="broken.py",
                content_type="code",
                language="python",
                size_bytes=0,
            )

        result = pipeline.ingest(bad_doc(), project.id, source.id)
        assert "broken.py" in result.errors[0]
