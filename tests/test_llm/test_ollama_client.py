"""Tests for the Ollama LLM client (SPEC-04 Section 4)."""

from unittest.mock import MagicMock, patch

import pytest

from openaustria_rag.llm.ollama_client import LLMService


class TestLLMServiceHealthCheck:
    @patch("openaustria_rag.llm.ollama_client.requests.Session")
    def test_health_check_unreachable(self, mock_cls):
        session = MagicMock()
        mock_cls.return_value = session
        session.get.side_effect = ConnectionError("refused")
        svc = LLMService(base_url="http://localhost:11434", model="mistral")
        assert svc.health_check() is False

    @patch("openaustria_rag.llm.ollama_client.requests.Session")
    def test_health_check_model_found(self, mock_cls):
        session = MagicMock()
        mock_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"models": [{"name": "mistral:latest"}]}
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp
        svc = LLMService(base_url="http://localhost:11434", model="mistral")
        assert svc.health_check() is True


class TestLLMServiceGenerate:
    @patch("openaustria_rag.llm.ollama_client.requests.Session")
    def test_generate_completion(self, mock_cls):
        session = MagicMock()
        mock_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"response": "Hello!", "eval_count": 5}
        resp.raise_for_status = MagicMock()
        session.post.return_value = resp

        svc = LLMService(base_url="http://localhost:11434", model="mistral")
        result = svc.generate("Say hello")
        assert result == "Hello!"
        assert svc.last_token_count == 5

    @patch("openaustria_rag.llm.ollama_client.requests.Session")
    def test_generate_chat(self, mock_cls):
        session = MagicMock()
        mock_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {
            "message": {"content": "Hi there!"},
            "eval_count": 3,
        }
        resp.raise_for_status = MagicMock()
        session.post.return_value = resp

        svc = LLMService(base_url="http://localhost:11434", model="mistral")
        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
        ]
        result = svc.generate(messages)
        assert result == "Hi there!"
        assert svc.last_token_count == 3

    @patch("openaustria_rag.llm.ollama_client.requests.Session")
    def test_generate_sends_options(self, mock_cls):
        session = MagicMock()
        mock_cls.return_value = session
        resp = MagicMock()
        resp.json.return_value = {"response": "ok", "eval_count": 1}
        resp.raise_for_status = MagicMock()
        session.post.return_value = resp

        svc = LLMService(
            base_url="http://localhost:11434", model="mistral",
            temperature=0.5, max_tokens=1024, context_length=4096,
        )
        svc.generate("test")

        call_kwargs = session.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["options"]["temperature"] == 0.5
        assert body["options"]["num_predict"] == 1024
        assert body["options"]["num_ctx"] == 4096
