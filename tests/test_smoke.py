"""Smoke tests: verify all modules import and basic infrastructure works."""

import pytest


class TestImports:
    def test_import_package(self):
        import openaustria_rag
        assert openaustria_rag.__version__ == "0.1.0"

    def test_import_models(self):
        from openaustria_rag.models import (
            Project, Source, Document, Chunk, CodeElement,
            GapReport, GapItem, ChatMessage,
        )

    def test_import_config(self):
        from openaustria_rag.config import Settings, get_settings

    def test_import_db(self):
        from openaustria_rag.db import MetadataDB

    def test_import_connectors(self):
        from openaustria_rag.connectors.base import BaseConnector, ConnectorRegistry
        from openaustria_rag.connectors.git_connector import GitConnector
        from openaustria_rag.connectors.zip_connector import ZipConnector
        from openaustria_rag.connectors.confluence_connector import ConfluenceConnector

    def test_import_ingestion(self):
        from openaustria_rag.ingestion.code_parser import CodeParser
        from openaustria_rag.ingestion.chunking import ChunkingService
        from openaustria_rag.ingestion.embedding_service import EmbeddingService
        from openaustria_rag.ingestion.pipeline import IngestionPipeline

    def test_import_retrieval(self):
        from openaustria_rag.retrieval.vector_store import VectorStoreService
        from openaustria_rag.retrieval.query_engine import QueryEngine

    def test_import_llm(self):
        from openaustria_rag.llm.ollama_client import LLMService
        from openaustria_rag.llm.prompts import PromptManager, QueryType, ContextBudget

    def test_import_analysis(self):
        from openaustria_rag.analysis.gap_analyzer import GapAnalyzer, GapReportExporter
        from openaustria_rag.analysis.matching import split_camel_case, fuzzy_match_in_text

    def test_import_frontend(self):
        from openaustria_rag.frontend.schemas import ProjectCreate, QueryRequest
        from openaustria_rag.frontend.api_client import APIClient


class TestInfrastructure:
    def test_config_loads_defaults(self):
        from openaustria_rag.config import Settings
        s = Settings()
        assert s.ollama.base_url == "http://localhost:11434"
        assert s.embedding.model == "nomic-embed-text"

    def test_sqlite_schema_creates(self, tmp_path):
        from openaustria_rag.db import MetadataDB
        db = MetadataDB(db_path=tmp_path / "smoke.db")
        tables = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "projects" in table_names
        assert "sources" in table_names
        assert "documents" in table_names
        assert "code_elements" in table_names
        assert "gap_reports" in table_names
        assert "chat_messages" in table_names
        db.close()

    def test_chromadb_client_initializes(self, tmp_path):
        from openaustria_rag.retrieval.vector_store import VectorStoreService
        vs = VectorStoreService(persist_path=tmp_path / "chroma")
        col = vs.get_or_create_collection("smoke_test")
        assert col.count() == 0
