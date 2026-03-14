"""ChromaDB vector store abstraction (SPEC-03 Section 6)."""

import logging
from pathlib import Path

import chromadb

from ..config import get_settings, PROJECT_ROOT

logger = logging.getLogger(__name__)


class VectorStoreService:
    """ChromaDB-backed vector store for chunk storage and retrieval."""

    def __init__(self, persist_path: str | Path | None = None):
        if persist_path is None:
            settings = get_settings()
            persist_path = PROJECT_ROOT / settings.vector_store.persist_path
        self._persist_path = Path(persist_path)
        self._persist_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_path))

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        """Get or create a collection with cosine distance metric."""
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def collection_name(self, project_id: str, content_type: str) -> str:
        """Generate collection name: {project_id}_{content_type}."""
        return f"{project_id}_{content_type}"

    def upsert(
        self,
        collection: chromadb.Collection,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Insert or update chunks in a collection."""
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        collection: chromadb.Collection,
        query_embedding: list[float],
        top_k: int = 10,
        where: dict | None = None,
    ) -> dict:
        """Query a collection by embedding vector."""
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        return collection.query(**kwargs)

    def delete_by_document(self, document_id: str) -> None:
        """Delete all chunks of a document across all collections."""
        for col in self._client.list_collections():
            name = col if isinstance(col, str) else col.name
            try:
                collection = self._client.get_collection(name)
                collection.delete(where={"document_id": document_id})
            except Exception:
                pass

    def delete_collection(self, name: str) -> None:
        """Delete an entire collection."""
        self._client.delete_collection(name)

    def get_stats(self, collection: chromadb.Collection) -> dict:
        """Return collection name and chunk count."""
        return {
            "name": collection.name,
            "count": collection.count(),
        }

    def list_collections(self) -> list[str]:
        """List all collection names."""
        collections = self._client.list_collections()
        return [c if isinstance(c, str) else c.name for c in collections]
