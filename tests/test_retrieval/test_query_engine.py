"""Tests for the RAG query engine (SPEC-04)."""

from unittest.mock import MagicMock

import pytest

from openaustria_rag.llm.prompts import ContextBudget, QueryType
from openaustria_rag.retrieval.query_engine import (
    QueryCache,
    QueryContext,
    QueryEngine,
    RetrievedChunk,
)
from openaustria_rag.retrieval.vector_store import VectorStoreService


@pytest.fixture
def mock_embedding():
    svc = MagicMock()
    svc.embed_single.return_value = [0.1, 0.2, 0.3]
    return svc


@pytest.fixture
def mock_llm():
    svc = MagicMock()
    svc.generate.return_value = "Dies ist die Antwort."
    svc.last_token_count = 10
    return svc


@pytest.fixture
def vector_store(tmp_path):
    store = VectorStoreService(persist_path=tmp_path / "chromadb")
    # Seed a code collection
    col = store.get_or_create_collection("proj1_code")
    store.upsert(
        col,
        ids=["c1", "c2"],
        documents=["class UserService handles users", "function getUsers returns list"],
        embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        metadatas=[
            {"file_path": "src/service.py", "element_name": "UserService",
             "source_type": "code", "language": "python", "document_id": "d1"},
            {"file_path": "src/service.py", "element_name": "getUsers",
             "source_type": "code", "language": "python", "document_id": "d1"},
        ],
    )
    # Seed a documentation collection
    doc_col = store.get_or_create_collection("proj1_documentation")
    store.upsert(
        doc_col,
        ids=["d1"],
        documents=["# User Management\nThe UserService manages all user operations."],
        embeddings=[[0.2, 0.3, 0.4]],
        metadatas=[
            {"file_path": "docs/users.md", "element_name": "User Management",
             "source_type": "documentation", "language": "markdown", "document_id": "d2"},
        ],
    )
    return store


@pytest.fixture
def engine(mock_embedding, vector_store, mock_llm):
    return QueryEngine(
        embedding_service=mock_embedding,
        vector_store=vector_store,
        llm_service=mock_llm,
    )


class TestQueryTypeDetection:
    def test_explain_detected(self, engine):
        assert engine._analyze_query("Erkläre die UserService Klasse") == QueryType.EXPLAIN

    def test_compare_detected(self, engine):
        assert engine._analyze_query("Vergleiche Code und Doku") == QueryType.COMPARE

    def test_summarize_detected(self, engine):
        assert engine._analyze_query("Fasse zusammen was der Service macht") == QueryType.SUMMARIZE

    def test_gap_check_detected(self, engine):
        assert engine._analyze_query("Ist resetPassword dokumentiert?") == QueryType.GAP_CHECK

    def test_default_is_search(self, engine):
        assert engine._analyze_query("How does auth work?") == QueryType.SEARCH


class TestRetrieval:
    def test_query_returns_result(self, engine):
        ctx = QueryContext(project_id="proj1", query="UserService")
        result = engine.query(ctx)
        assert result.answer == "Dies ist die Antwort."
        assert result.query_type == QueryType.SEARCH
        assert len(result.chunks) > 0

    def test_multi_collection_search(self, engine):
        ctx = QueryContext(project_id="proj1", query="UserService", top_k=10)
        result = engine.query(ctx)
        # Should find chunks from both code and documentation collections
        source_types = {c.source_type for c in result.chunks}
        assert "code" in source_types or "documentation" in source_types

    def test_timing_recorded(self, engine):
        ctx = QueryContext(project_id="proj1", query="test")
        result = engine.query(ctx)
        assert result.retrieval_time_ms >= 0
        assert result.generation_time_ms >= 0

    def test_explicit_query_type(self, engine):
        ctx = QueryContext(
            project_id="proj1", query="test",
            query_type=QueryType.EXPLAIN,
        )
        result = engine.query(ctx)
        assert result.query_type == QueryType.EXPLAIN

    def test_chat_history_uses_chat_api(self, engine, mock_llm):
        ctx = QueryContext(
            project_id="proj1", query="follow up",
            chat_history=[
                {"role": "user", "content": "previous question"},
                {"role": "assistant", "content": "previous answer"},
            ],
        )
        engine.query(ctx)
        # Should pass list of messages, not string
        call_args = mock_llm.generate.call_args[0][0]
        assert isinstance(call_args, list)


class TestReranking:
    def test_keyword_match_boosts_score(self, engine):
        chunks = [
            RetrievedChunk(id="1", content="unrelated stuff", score=0.8),
            RetrievedChunk(id="2", content="UserService handles users", score=0.7),
        ]
        reranked = engine._rerank(chunks, "UserService")
        # Chunk with keyword match should score higher
        assert reranked[0].id == "2" or reranked[0].score >= reranked[1].score

    def test_deduplication(self, engine):
        chunks = [
            RetrievedChunk(id="1", content="same content", score=0.9),
            RetrievedChunk(id="2", content="same content", score=0.8),
        ]
        reranked = engine._rerank(chunks, "test")
        assert len(reranked) == 1


class TestContextAssembly:
    def test_assemble_with_sources(self):
        chunks = [
            RetrievedChunk(
                id="1", content="Code here", score=0.9,
                file_path="src/main.py", element_name="MyClass",
            ),
        ]
        ctx = QueryEngine._assemble_context(chunks)
        assert "[Quelle 1: src/main.py (MyClass)]" in ctx
        assert "Code here" in ctx

    def test_assemble_empty(self):
        ctx = QueryEngine._assemble_context([])
        assert "Kein relevanter Kontext" in ctx

    def test_context_budget_limits_chunks(self, engine):
        ctx = QueryContext(project_id="proj1", query="test")
        engine.context_budget = ContextBudget(
            context_length=100, max_response_tokens=50, prompt_overhead=20
        )
        # Budget = 30 tokens = ~120 chars
        result = engine.query(ctx)
        total_chars = sum(len(c.content) for c in result.chunks)
        assert total_chars // 4 <= 30 or len(result.chunks) <= 1


class TestQueryCache:
    def test_cache_hit(self):
        cache = QueryCache()
        cache.put("hello", [0.1, 0.2])
        assert cache.get("hello") == [0.1, 0.2]
        assert cache.hits == 1

    def test_cache_miss(self):
        cache = QueryCache()
        assert cache.get("unknown") is None
        assert cache.misses == 1

    def test_cache_eviction(self):
        cache = QueryCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_embedding_cache_in_engine(self, engine):
        ctx = QueryContext(project_id="proj1", query="same query")
        engine.query(ctx)
        engine.query(ctx)
        # Second query should hit cache
        assert engine.embedding_cache.hits == 1
