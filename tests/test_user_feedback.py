"""Tests for user feedback improvements: progress callbacks, cancel support."""

from unittest.mock import MagicMock, patch

import pytest

from openaustria_rag.analysis.gap_analyzer import AnalysisCancelledError, GapAnalyzer
from openaustria_rag.connectors.base import RawDocument
from openaustria_rag.ingestion.pipeline import IngestionPipeline, IngestionResult
from openaustria_rag.models import CodeElement, ElementKind


class TestIngestionProgressCallback:
    """Test that IngestionPipeline.ingest() calls progress_callback per document."""

    @pytest.fixture
    def pipeline(self):
        db = MagicMock()
        db.document_unchanged.return_value = False
        db._conn.execute.return_value.fetchone.return_value = None
        code_parser = MagicMock()
        code_parser.parse.return_value = []
        chunking = MagicMock()
        chunking.chunk.return_value = []
        embedding = MagicMock()
        vector_store = MagicMock()
        return IngestionPipeline(
            db=db,
            code_parser=code_parser,
            chunking_service=chunking,
            embedding_service=embedding,
            vector_store=vector_store,
        )

    def test_callback_called_per_document(self, pipeline):
        docs = [
            RawDocument(content="a", file_path="a.py", content_type="code", language="python"),
            RawDocument(content="b", file_path="b.py", content_type="code", language="python"),
        ]
        callback = MagicMock()
        pipeline.ingest(iter(docs), "proj1", "src1", progress_callback=callback)
        assert callback.call_count == 2
        # First call: doc 1
        callback.assert_any_call("ingesting", 1, 0, "a.py")
        # Second call: doc 2
        callback.assert_any_call("ingesting", 2, 0, "b.py")

    def test_no_callback_no_error(self, pipeline):
        docs = [
            RawDocument(content="a", file_path="a.py", content_type="code", language="python"),
        ]
        result = pipeline.ingest(iter(docs), "proj1", "src1")
        assert isinstance(result, IngestionResult)


class TestAnalysisCancelledError:
    """Test that GapAnalyzer respects cancel_check."""

    def test_cancel_raises_error(self):
        element = CodeElement(
            id="e1", document_id="d1", kind=ElementKind.CLASS,
            name="MyService", short_name="MyService",
            file_path="src/MyService.java",
            start_line=1, end_line=10, signature="class MyService",
        )
        db = MagicMock()
        db.get_code_elements_by_project.return_value = [element]
        vector_store = MagicMock()
        vector_store.list_collections.return_value = []
        embedding = MagicMock()

        cancel_check = MagicMock(return_value=True)  # always cancel

        analyzer = GapAnalyzer(
            db=db,
            vector_store=vector_store,
            embedding_service=embedding,
            cancel_check=cancel_check,
        )

        with pytest.raises(AnalysisCancelledError):
            analyzer.analyze("proj1")

    def test_no_cancel_proceeds(self):
        db = MagicMock()
        db.get_code_elements_by_project.return_value = []
        vector_store = MagicMock()
        vector_store.list_collections.return_value = []
        embedding = MagicMock()

        cancel_check = MagicMock(return_value=False)  # never cancel

        analyzer = GapAnalyzer(
            db=db,
            vector_store=vector_store,
            embedding_service=embedding,
            cancel_check=cancel_check,
        )

        report = analyzer.analyze("proj1")
        assert report is not None
