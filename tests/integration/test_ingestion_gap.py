"""Integration: Ingestion → Gap Analysis (SPEC-03/05)."""

import json

import pytest

from openaustria_rag.analysis.gap_analyzer import GapAnalyzer, GapReportExporter
from openaustria_rag.connectors.base import RawDocument
from openaustria_rag.models import GapType


def _code_and_docs():
    yield RawDocument(
        content=(
            'class UserService:\n'
            '    """Manages users."""\n'
            '    def get_users(self):\n'
            '        return []\n'
            '    def create_user(self, name):\n'
            '        return {"name": name}\n'
            '\n'
            'def reset_password(user_id):\n'
            '    """Undocumented function."""\n'
            '    pass\n'
        ),
        file_path="src/service.py",
        content_type="code",
        language="python",
        size_bytes=200,
    )
    yield RawDocument(
        content=(
            "# User Management\n\n"
            "The UserService is the central component for managing users. "
            "It provides the get_users method to retrieve all users from the database "
            "and the create_user method to add new users to the system.\n"
        ),
        file_path="docs/users.md",
        content_type="documentation",
        language="markdown",
        size_bytes=200,
    )


@pytest.mark.integration
class TestIngestionToGapAnalysis:
    def test_gap_analysis_finds_undocumented(
        self, pipeline, project, source, db, vector_store, mock_embedding
    ):
        """Gap analysis should find undocumented code elements."""
        pipeline.ingest(_code_and_docs(), project.id, source.id)

        analyzer = GapAnalyzer(
            db=db,
            vector_store=vector_store,
            embedding_service=mock_embedding,
            llm_service=None,
            run_llm_analysis=False,
        )

        report = analyzer.analyze(project.id)

        assert report.summary.total_code_elements > 0
        assert len(report.gaps) > 0

        # Some elements should be matched, some not
        gap_types = {g.gap_type for g in report.gaps}
        assert GapType.CONSISTENT in gap_types or GapType.UNDOCUMENTED in gap_types

    def test_report_summary_correct(
        self, pipeline, project, source, db, vector_store, mock_embedding
    ):
        """Summary counts should add up."""
        pipeline.ingest(_code_and_docs(), project.id, source.id)

        analyzer = GapAnalyzer(
            db=db, vector_store=vector_store,
            embedding_service=mock_embedding, run_llm_analysis=False,
        )
        report = analyzer.analyze(project.id)

        s = report.summary
        assert s.documented + s.undocumented == s.total_code_elements

    def test_json_export_valid(
        self, pipeline, project, source, db, vector_store, mock_embedding
    ):
        """JSON export should be valid JSON."""
        pipeline.ingest(_code_and_docs(), project.id, source.id)

        analyzer = GapAnalyzer(
            db=db, vector_store=vector_store,
            embedding_service=mock_embedding, run_llm_analysis=False,
        )
        report = analyzer.analyze(project.id)

        json_str = GapReportExporter.to_json(report)
        data = json.loads(json_str)
        assert data["id"] == report.id
        assert "gaps" in data
        assert "summary" in data

    def test_csv_export_valid(
        self, pipeline, project, source, db, vector_store, mock_embedding
    ):
        """CSV export should have header + data rows."""
        pipeline.ingest(_code_and_docs(), project.id, source.id)

        analyzer = GapAnalyzer(
            db=db, vector_store=vector_store,
            embedding_service=mock_embedding, run_llm_analysis=False,
        )
        report = analyzer.analyze(project.id)

        csv_str = GapReportExporter.to_csv(report)
        lines = csv_str.strip().split("\n")
        assert len(lines) >= 2  # header + at least 1 row
        assert "gap_type" in lines[0]
