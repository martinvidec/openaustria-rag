"""Integration: Ingestion → Query Engine (SPEC-03/04)."""

import pytest

from openaustria_rag.connectors.base import RawDocument
from openaustria_rag.retrieval.query_engine import QueryContext, QueryEngine


def _sample_docs():
    yield RawDocument(
        content='class UserService:\n    """Manages users."""\n    def get_users(self):\n        return []\n',
        file_path="src/service.py",
        content_type="code",
        language="python",
        size_bytes=80,
    )
    yield RawDocument(
        content="# User Management\n\nThe UserService manages all user operations including creation and retrieval of user records from the database.\n",
        file_path="docs/users.md",
        content_type="documentation",
        language="markdown",
        size_bytes=130,
    )


@pytest.mark.integration
class TestIngestionToQuery:
    def test_query_finds_indexed_content(
        self, pipeline, project, source, vector_store, mock_embedding, mock_llm
    ):
        """Index documents, then query and get relevant results."""
        pipeline.ingest(_sample_docs(), project.id, source.id)

        engine = QueryEngine(
            embedding_service=mock_embedding,
            vector_store=vector_store,
            llm_service=mock_llm,
        )

        ctx = QueryContext(project_id=project.id, query="UserService")
        result = engine.query(ctx)

        assert result.answer  # LLM produced an answer
        assert len(result.chunks) > 0  # Found relevant chunks

    def test_query_returns_sources(
        self, pipeline, project, source, vector_store, mock_embedding, mock_llm
    ):
        """Query result should include source file paths."""
        pipeline.ingest(_sample_docs(), project.id, source.id)

        engine = QueryEngine(
            embedding_service=mock_embedding,
            vector_store=vector_store,
            llm_service=mock_llm,
        )

        ctx = QueryContext(project_id=project.id, query="users")
        result = engine.query(ctx)

        file_paths = {c.file_path for c in result.chunks}
        assert len(file_paths) > 0

    def test_query_empty_project(
        self, project, vector_store, mock_embedding, mock_llm
    ):
        """Query on empty project should still return an answer."""
        engine = QueryEngine(
            embedding_service=mock_embedding,
            vector_store=vector_store,
            llm_service=mock_llm,
        )

        ctx = QueryContext(project_id=project.id, query="anything")
        result = engine.query(ctx)
        assert result.answer  # LLM still generates
        assert len(result.chunks) == 0
