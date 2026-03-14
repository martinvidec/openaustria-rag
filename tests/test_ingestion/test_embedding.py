"""Tests for the embedding service (SPEC-03 Section 5)."""

from unittest.mock import MagicMock, patch

import pytest

from openaustria_rag.ingestion.embedding_service import (
    EmbeddingPreprocessor,
    EmbeddingService,
)


class TestEmbeddingPreprocessor:
    def test_preprocess_query(self):
        result = EmbeddingPreprocessor.preprocess_query("how does auth work?")
        assert result == "search_query: how does auth work?"

    def test_preprocess_document(self):
        result = EmbeddingPreprocessor.preprocess_document("Auth uses JWT tokens")
        assert result == "search_document: Auth uses JWT tokens"

    def test_preprocess_code_reduces_empty_lines(self):
        code = "def foo():\n\n\n\n    pass\n\n\n\nreturn"
        result = EmbeddingPreprocessor.preprocess_code(code)
        assert "\n\n\n" not in result
        assert "def foo():" in result
        assert "pass" in result

    def test_preprocess_code_strips_trailing_whitespace(self):
        code = "def foo():   \n    pass   \n"
        result = EmbeddingPreprocessor.preprocess_code(code)
        assert "   \n" not in result


class TestEmbeddingServiceHealthCheck:
    @patch("openaustria_rag.ingestion.embedding_service.requests.Session")
    def test_health_check_unreachable_returns_false(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        session.get.side_effect = ConnectionError("refused")

        svc = EmbeddingService(base_url="http://localhost:11434", model="nomic-embed-text")
        assert svc.health_check() is False

    @patch("openaustria_rag.ingestion.embedding_service.requests.Session")
    def test_health_check_model_available(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {
            "models": [{"name": "nomic-embed-text:latest"}]
        }
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        svc = EmbeddingService(base_url="http://localhost:11434", model="nomic-embed-text")
        assert svc.health_check() is True

    @patch("openaustria_rag.ingestion.embedding_service.requests.Session")
    def test_health_check_model_not_found(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"models": [{"name": "mistral:latest"}]}
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        svc = EmbeddingService(base_url="http://localhost:11434", model="nomic-embed-text")
        assert svc.health_check() is False


class TestEmbeddingServiceEmbed:
    @patch("openaustria_rag.ingestion.embedding_service.requests.Session")
    def test_embed_single(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        resp.raise_for_status = MagicMock()
        session.post.return_value = resp

        svc = EmbeddingService(base_url="http://localhost:11434", model="nomic-embed-text")
        result = svc.embed_single("hello world")
        assert result == [0.1, 0.2, 0.3]
        session.post.assert_called_once()

    @patch("openaustria_rag.ingestion.embedding_service.requests.Session")
    def test_embed_batch(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"embedding": [0.1, 0.2]}
        resp.raise_for_status = MagicMock()
        session.post.return_value = resp

        svc = EmbeddingService(base_url="http://localhost:11434", model="nomic-embed-text")
        result = svc.embed_batch(["a", "b", "c"])
        assert len(result) == 3
        assert session.post.call_count == 3

    @patch("openaustria_rag.ingestion.embedding_service.requests.Session")
    def test_get_dimensions(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"embedding": [0.0] * 768}
        resp.raise_for_status = MagicMock()
        session.post.return_value = resp

        svc = EmbeddingService(base_url="http://localhost:11434", model="nomic-embed-text")
        assert svc.get_dimensions() == 768
