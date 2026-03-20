"""Ingestion pipeline orchestrator (SPEC-03 Sections 2, 7, 8)."""

import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Generator

from ..connectors.base import ConnectorRegistry, ConnectorError, RawDocument
from ..connectors.utils import detect_language
from ..db import MetadataDB
from ..ingestion.chunking import ChunkingService
from ..ingestion.code_parser import CodeParser
from ..ingestion.embedding_service import EmbeddingPreprocessor, EmbeddingService
from ..models import (
    ContentType,
    Document,
    Project,
    ProjectStatus,
    Source,
    SourceStatus,
)
from ..retrieval.vector_store import VectorStoreService

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    documents_processed: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    chunks_created: int = 0
    code_elements_extracted: int = 0
    errors: list[str] = field(default_factory=list)


class IngestionPipeline:
    """Orchestrates: RawDocument → Parse → Chunk → Embed → Index."""

    def __init__(
        self,
        db: MetadataDB,
        code_parser: CodeParser,
        chunking_service: ChunkingService,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        batch_size: int = 50,
    ):
        self.db = db
        self.code_parser = code_parser
        self.chunking = chunking_service
        self.embedding = embedding_service
        self.vector_store = vector_store
        self.batch_size = batch_size

    def ingest(
        self,
        documents: Generator[RawDocument, None, None],
        project_id: str,
        source_id: str,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> IngestionResult:
        """Process a stream of RawDocuments through the full pipeline."""
        result = IngestionResult()
        doc_num = 0

        for raw_doc in documents:
            doc_num += 1
            if progress_callback:
                progress_callback("ingesting", doc_num, 0, raw_doc.file_path)
            try:
                content_hash = hashlib.sha256(
                    raw_doc.content.encode("utf-8")
                ).hexdigest()

                # Check for existing document by file path + source
                existing = self._find_existing_document(source_id, raw_doc.file_path)

                if existing and self.db.document_unchanged(existing.id, content_hash):
                    result.documents_skipped += 1
                    continue

                doc_id = existing.id if existing else str(uuid.uuid4())
                stats = self._process_document(
                    raw_doc, project_id, source_id, doc_id, content_hash
                )
                result.documents_processed += 1
                result.chunks_created += stats["chunks"]
                result.code_elements_extracted += stats["elements"]
            except Exception as e:
                result.documents_failed += 1
                result.errors.append(f"{raw_doc.file_path}: {e}")
                logger.warning(f"Failed to process {raw_doc.file_path}: {e}")

        return result

    def _process_document(
        self,
        raw_doc: RawDocument,
        project_id: str,
        source_id: str,
        doc_id: str,
        content_hash: str,
    ) -> dict:
        """Process a single document through the pipeline."""
        # 1. Delete old data if re-indexing
        self.db.delete_code_elements(doc_id)
        self.vector_store.delete_by_document(doc_id)

        # 2. Save document metadata
        content_type = self._map_content_type(raw_doc.content_type)
        doc = Document(
            id=doc_id,
            source_id=source_id,
            content_type=content_type,
            file_path=raw_doc.file_path,
            content_hash=content_hash,
            language=raw_doc.language,
            metadata={
                "size_bytes": raw_doc.size_bytes,
                "encoding": raw_doc.encoding,
                **(raw_doc.metadata or {}),
            },
        )
        self.db.save_document(doc)

        # 3. Extract code elements (code files only)
        code_elements = []
        if raw_doc.content_type == "code" and raw_doc.language:
            code_elements = self.code_parser.parse(
                raw_doc.content, raw_doc.language, raw_doc.file_path, doc_id
            )
            if code_elements:
                self.db.save_code_elements(code_elements)

        # 4. Chunk
        chunks = self.chunking.chunk(
            content=raw_doc.content,
            content_type=raw_doc.content_type,
            file_path=raw_doc.file_path,
            document_id=doc_id,
            language=raw_doc.language,
            code_elements=code_elements or None,
        )

        # 5. Enrich metadata
        now = datetime.now(UTC).isoformat()
        for chunk in chunks:
            chunk.metadata.project_id = project_id
            chunk.metadata.source_id = source_id
            chunk.metadata.document_id = doc_id
            chunk.metadata.ingested_at = now

        # 6. Embed and index
        if chunks:
            self._embed_and_index(chunks, project_id, raw_doc.content_type)

        return {"chunks": len(chunks), "elements": len(code_elements)}

    def _embed_and_index(
        self, chunks, project_id: str, content_type: str
    ) -> None:
        """Embed chunks and store in ChromaDB in batches."""
        collection_name = self.vector_store.collection_name(project_id, content_type)
        collection = self.vector_store.get_or_create_collection(collection_name)

        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]

            texts = [
                EmbeddingPreprocessor.preprocess_document(c.content)
                for c in batch
            ]
            embeddings = self.embedding.embed_batch(texts)

            self.vector_store.upsert(
                collection,
                ids=[c.id for c in batch],
                documents=[c.content for c in batch],
                embeddings=embeddings,
                metadatas=[
                    {
                        "project_id": c.metadata.project_id,
                        "source_id": c.metadata.source_id,
                        "document_id": c.metadata.document_id,
                        "file_path": c.metadata.file_path,
                        "element_type": c.metadata.element_type,
                        "element_name": c.metadata.element_name,
                        "language": c.metadata.language,
                        "source_type": c.metadata.source_type,
                        "ingested_at": c.metadata.ingested_at,
                    }
                    for c in batch
                ],
            )

    def _find_existing_document(self, source_id: str, file_path: str) -> Document | None:
        """Find an existing document by source and file path."""
        # Query all documents for this source and check file_path
        rows = self.db._conn.execute(
            "SELECT id FROM documents WHERE source_id = ? AND file_path = ?",
            (source_id, file_path),
        ).fetchone()
        if rows:
            return self.db.get_document(rows["id"])
        return None

    @staticmethod
    def _map_content_type(raw_type: str) -> ContentType:
        mapping = {
            "code": ContentType.CODE,
            "documentation": ContentType.DOCUMENTATION,
            "specification": ContentType.SPECIFICATION,
            "config": ContentType.CONFIG,
            "model": ContentType.MODEL,
        }
        return mapping.get(raw_type, ContentType.CODE)


def run_sync(
    source: Source,
    project: Project,
    db: MetadataDB,
    pipeline: IngestionPipeline,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> IngestionResult:
    """Orchestrate a full source sync: connect → fetch → ingest → update status."""
    def _report(stage: str, current: int = 0, total: int = 0, detail: str = ""):
        if progress_callback:
            progress_callback(stage, current, total, detail)

    # Update source status
    source.status = SourceStatus.SYNCING
    db.save_source(source)
    project.status = ProjectStatus.INDEXING
    db.save_project(project)

    try:
        _report("connecting", 0, 0, "Verbinde...")
        connector = ConnectorRegistry.create(
            source.source_type.value, source.id, source.config
        )
        connector.connect()

        _report("fetching", 0, 0, "Lade Dokumente...")
        result = pipeline.ingest(
            connector.fetch_documents(), project.id, source.id,
            progress_callback=progress_callback,
        )

        _report("disconnecting", 0, 0, "Trenne Verbindung...")
        connector.disconnect()

        # Update status
        _report("done", result.documents_processed, result.documents_processed, "Fertig")
        source.status = SourceStatus.SYNCED
        source.last_sync_at = datetime.now(UTC)
        if result.documents_failed > 0:
            source.error_message = f"{result.documents_failed} documents failed"
        else:
            source.error_message = None
        db.save_source(source)

        project.status = ProjectStatus.READY
        project.updated_at = datetime.now(UTC)
        db.save_project(project)

        return result

    except Exception as e:
        _report("error", 0, 0, str(e))
        source.status = SourceStatus.ERROR
        source.error_message = str(e)
        db.save_source(source)
        project.status = ProjectStatus.ERROR
        project.updated_at = datetime.now(UTC)
        db.save_project(project)
        raise
