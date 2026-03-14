"""Tests for the vector store service (SPEC-03 Section 6)."""

import pytest

from openaustria_rag.retrieval.vector_store import VectorStoreService


@pytest.fixture
def store(tmp_path):
    return VectorStoreService(persist_path=tmp_path / "chromadb")


class TestCollectionManagement:
    def test_get_or_create_collection(self, store):
        col = store.get_or_create_collection("test_code")
        assert col.name == "test_code"
        assert col.count() == 0

    def test_get_existing_collection(self, store):
        store.get_or_create_collection("test_code")
        col = store.get_or_create_collection("test_code")
        assert col.name == "test_code"

    def test_collection_name_format(self, store):
        name = store.collection_name("project1", "code")
        assert name == "project1_code"

    def test_delete_collection(self, store):
        store.get_or_create_collection("to_delete")
        store.delete_collection("to_delete")
        assert "to_delete" not in store.list_collections()

    def test_list_collections(self, store):
        store.get_or_create_collection("col_a")
        store.get_or_create_collection("col_b")
        names = store.list_collections()
        assert "col_a" in names
        assert "col_b" in names


class TestUpsertAndQuery:
    def test_upsert_and_count(self, store):
        col = store.get_or_create_collection("test")
        store.upsert(
            col,
            ids=["c1", "c2"],
            documents=["hello world", "foo bar"],
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            metadatas=[{"document_id": "d1"}, {"document_id": "d2"}],
        )
        assert col.count() == 2

    def test_upsert_idempotent(self, store):
        col = store.get_or_create_collection("test")
        store.upsert(col, ids=["c1"], documents=["v1"], embeddings=[[0.1, 0.2, 0.3]])
        store.upsert(col, ids=["c1"], documents=["v2"], embeddings=[[0.4, 0.5, 0.6]])
        assert col.count() == 1  # Upsert, not duplicate

    def test_query_returns_results(self, store):
        col = store.get_or_create_collection("test")
        store.upsert(
            col,
            ids=["c1", "c2", "c3"],
            documents=["python code", "java code", "markdown docs"],
            embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            metadatas=[
                {"document_id": "d1", "language": "python"},
                {"document_id": "d1", "language": "java"},
                {"document_id": "d2", "language": "markdown"},
            ],
        )

        result = store.query(col, query_embedding=[1.0, 0.0, 0.0], top_k=2)
        assert len(result["ids"][0]) == 2
        assert "c1" in result["ids"][0]  # Closest match
        assert "documents" in result
        assert "metadatas" in result
        assert "distances" in result

    def test_query_with_where_filter(self, store):
        col = store.get_or_create_collection("test")
        store.upsert(
            col,
            ids=["c1", "c2"],
            documents=["python", "java"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            metadatas=[{"language": "python"}, {"language": "java"}],
        )

        result = store.query(
            col,
            query_embedding=[1.0, 0.0],
            top_k=10,
            where={"language": "java"},
        )
        assert len(result["ids"][0]) == 1
        assert result["metadatas"][0][0]["language"] == "java"


class TestDeleteByDocument:
    def test_delete_by_document_id(self, store):
        col = store.get_or_create_collection("test")
        store.upsert(
            col,
            ids=["c1", "c2", "c3"],
            documents=["a", "b", "c"],
            embeddings=[[0.1], [0.2], [0.3]],
            metadatas=[
                {"document_id": "d1"},
                {"document_id": "d1"},
                {"document_id": "d2"},
            ],
        )
        store.delete_by_document("d1")
        assert col.count() == 1


class TestStats:
    def test_get_stats(self, store):
        col = store.get_or_create_collection("stats_test")
        store.upsert(
            col,
            ids=["c1", "c2"],
            documents=["a", "b"],
            embeddings=[[0.1], [0.2]],
        )
        stats = store.get_stats(col)
        assert stats["name"] == "stats_test"
        assert stats["count"] == 2
