"""Ollama embedding integration (SPEC-03 Section 5)."""

import logging
import re

import requests

from ..config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingPreprocessor:
    """Preprocessing for Nomic Embed Text model."""

    @staticmethod
    def preprocess_query(text: str) -> str:
        """Add search_query prefix required by Nomic Embed Text."""
        return f"search_query: {text}"

    @staticmethod
    def preprocess_document(text: str) -> str:
        """Add search_document prefix required by Nomic Embed Text."""
        return f"search_document: {text}"

    @staticmethod
    def preprocess_code(text: str) -> str:
        """Clean code text: reduce empty lines, strip trailing whitespace."""
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines)


class EmbeddingService:
    """Generate embeddings via Ollama REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ollama.base_url).rstrip("/")
        self.model = model or settings.embedding.model
        self.timeout = timeout or settings.embedding.timeout_seconds
        self._session = requests.Session()

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string."""
        resp = self._session.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts sequentially."""
        return [self.embed_single(text) for text in texts]

    def get_dimensions(self) -> int:
        """Auto-detect embedding dimensions via a test embedding."""
        test_embedding = self.embed_single("test")
        return len(test_embedding)

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
