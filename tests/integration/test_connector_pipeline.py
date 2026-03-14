"""Integration: Connector → Ingestion Pipeline (SPEC-02/03)."""

import os

import pytest
from git import Repo

from openaustria_rag.connectors.git_connector import GitConnector


@pytest.mark.integration
class TestConnectorToPipeline:
    def test_git_to_pipeline_full_flow(
        self, local_git_repo, pipeline, project, source, db, vector_store, tmp_path, monkeypatch
    ):
        """GitConnector → IngestionPipeline → SQLite + ChromaDB."""
        # Use a separate workdir so clone doesn't collide
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        connector = GitConnector(source.id, {"url": str(local_git_repo), "depth": None})
        connector.connect()

        result = pipeline.ingest(connector.fetch_documents(), project.id, source.id)
        connector.disconnect()

        assert result.documents_processed >= 3  # .py, .md, .yaml
        assert result.chunks_created > 0
        assert result.documents_failed == 0

        # Check SQLite
        docs = db._conn.execute(
            "SELECT * FROM documents WHERE source_id = ?", (source.id,)
        ).fetchall()
        assert len(docs) >= 3

        # Check code elements extracted
        elements = db.get_code_elements_by_project(project.id)
        assert len(elements) > 0
        names = {e.short_name for e in elements}
        assert "UserService" in names

        # Check ChromaDB
        code_col = vector_store.collection_name(project.id, "code")
        if code_col in vector_store.list_collections():
            col = vector_store.get_or_create_collection(code_col)
            assert col.count() > 0

    def test_idempotent_reindexing(
        self, local_git_repo, pipeline, project, source, db, tmp_path, monkeypatch
    ):
        """Second ingest with same content should skip all documents."""
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        # First run
        connector = GitConnector(source.id, {"url": str(local_git_repo), "depth": None})
        connector.connect()
        result1 = pipeline.ingest(connector.fetch_documents(), project.id, source.id)
        connector.disconnect()

        # Second run - reconnect pulls existing clone
        connector2 = GitConnector(source.id, {"url": str(local_git_repo), "depth": None})
        connector2.connect()
        result2 = pipeline.ingest(connector2.fetch_documents(), project.id, source.id)
        connector2.disconnect()

        assert result2.documents_skipped == result1.documents_processed
        assert result2.documents_processed == 0
