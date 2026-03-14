"""Ollama LLM integration (SPEC-04 Section 4)."""

import json
import logging
from typing import Generator

import requests

from ..config import get_settings

logger = logging.getLogger(__name__)


class LLMService:
    """Generate text via Ollama REST API (generate + chat)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 2048,
        context_length: int = 8192,
        timeout: int | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama.base_url).rstrip("/")
        self.model = model or settings.ollama.model
        self.temperature = temperature if temperature is not None else settings.ollama.temperature
        self.max_tokens = max_tokens
        self.context_length = context_length
        self.timeout = timeout or settings.ollama.timeout_seconds
        self.last_token_count: int = 0
        self._session = requests.Session()

    def generate(self, prompt: str | list[dict]) -> str:
        """Generate text. String → /api/generate, list → /api/chat."""
        if isinstance(prompt, list):
            return self._generate_chat(prompt)
        return self._generate_completion(prompt)

    def _generate_completion(self, prompt: str) -> str:
        """Non-streaming completion via /api/generate."""
        resp = self._session.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.context_length,
                },
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self.last_token_count = data.get("eval_count", 0)
        return data.get("response", "")

    def _generate_chat(self, messages: list[dict]) -> str:
        """Non-streaming chat via /api/chat."""
        resp = self._session.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.context_length,
                },
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self.last_token_count = data.get("eval_count", 0)
        return data.get("message", {}).get("content", "")

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        """Streaming completion via /api/generate, yields token chunks."""
        resp = self._session.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.context_length,
                },
            },
            timeout=self.timeout,
            stream=True,
        )
        resp.raise_for_status()

        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done"):
                    self.last_token_count = data.get("eval_count", 0)
                    break

    def health_check(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            resp = self._session.get(
                f"{self.base_url}/api/tags", timeout=5
            )
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return any(
                m.get("name", "").startswith(self.model) for m in models
            )
        except Exception:
            return False
