"""Tests for the gap analysis engine (SPEC-05)."""

from unittest.mock import MagicMock

import pytest

from openaustria_rag.analysis.gap_analyzer import (
    FalsePositiveManager,
    GapAnalyzer,
    GapReportExporter,
)
from openaustria_rag.analysis.matching import (
    LLMAnalysisResult,
    element_to_search_text,
    estimate_severity,
    fuzzy_match_in_text,
    generate_search_terms,
    is_boilerplate,
    split_camel_case,
)
from openaustria_rag.db import MetadataDB
from openaustria_rag.models import (
    CodeElement,
    ContentType,
    Document,
    ElementKind,
    GapItem,
    GapReport,
    GapSummary,
    GapType,
    Project,
    Severity,
    Source,
    SourceType,
)
from openaustria_rag.retrieval.vector_store import VectorStoreService


# --- Matching Utilities ---

class TestSplitCamelCase:
    def test_simple(self):
        assert split_camel_case("UserService") == ["user", "service"]

    def test_snake_case(self):
        assert split_camel_case("get_users") == ["get", "users"]

    def test_single_word(self):
        assert split_camel_case("user") == ["user"]

    def test_acronym(self):
        result = split_camel_case("HTTPClient")
        assert "client" in result


class TestFuzzyMatch:
    def test_exact_match(self):
        result = fuzzy_match_in_text("UserService", "The UserService handles users")
        assert result.matched is True
        assert result.score > 0.8

    def test_no_match(self):
        result = fuzzy_match_in_text("DatabasePool", "The cat sat on the mat")
        assert result.matched is False

    def test_partial_match(self):
        result = fuzzy_match_in_text("UserService", "The user service component")
        assert result.score > 0.0


class TestBoilerplate:
    def test_getter(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="getUser", short_name="getUser", file_path="a.java",
        )
        assert is_boilerplate(e) is True

    def test_setter(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="setName", short_name="setName", file_path="a.java",
        )
        assert is_boilerplate(e) is True

    def test_toString(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="toString", short_name="toString", file_path="a.java",
        )
        assert is_boilerplate(e) is True

    def test_init(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="__init__", short_name="__init__", file_path="a.py",
        )
        assert is_boilerplate(e) is True

    def test_not_boilerplate(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="processPayment", short_name="processPayment", file_path="a.java",
        )
        assert is_boilerplate(e) is False


class TestSeverityEstimation:
    def test_api_endpoint_is_high(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="getUsers", short_name="getUsers", file_path="a.java",
            annotations=["@GetMapping(\"/users\")"],
        )
        assert estimate_severity(e) == Severity.HIGH

    def test_interface_is_high(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.INTERFACE,
            name="UserRepo", short_name="UserRepo", file_path="a.java",
        )
        assert estimate_severity(e) == Severity.HIGH

    def test_public_is_medium(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.CLASS,
            name="Helper", short_name="Helper", file_path="a.java",
            visibility="public",
        )
        assert estimate_severity(e) == Severity.MEDIUM

    def test_private_is_low(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.METHOD,
            name="helper", short_name="helper", file_path="a.java",
            visibility="private",
        )
        assert estimate_severity(e) == Severity.LOW


class TestGenerateSearchTerms:
    def test_includes_short_and_full_name(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.CLASS,
            name="UserService", short_name="UserService", file_path="a.java",
        )
        terms = generate_search_terms(e)
        assert "UserService" in terms

    def test_includes_camel_split(self):
        e = CodeElement(
            id="1", document_id="d1", kind=ElementKind.CLASS,
            name="UserService", short_name="UserService", file_path="a.java",
        )
        terms = generate_search_terms(e)
        assert "user service" in terms


# --- LLM Response Parsing ---

class TestLLMResponseParsing:
    def test_parse_consistent(self):
        response = (
            "UEBEREINSTIMMUNG: ja\n"
            "ABWEICHUNGEN: keine\n"
            "SCHWEREGRAD: low\n"
            "EMPFEHLUNG: Keine Aenderungen noetig"
        )
        result = GapAnalyzer._parse_llm_response(response)
        assert result.consistent is True
        assert result.divergences == "keine"
        assert result.severity == "low"

    def test_parse_divergent(self):
        response = (
            "UEBEREINSTIMMUNG: nein\n"
            "ABWEICHUNGEN: Methode hat zusaetzlichen Parameter\n"
            "SCHWEREGRAD: medium\n"
            "EMPFEHLUNG: Doku aktualisieren"
        )
        result = GapAnalyzer._parse_llm_response(response)
        assert result.consistent is False
        assert "Parameter" in result.divergences


# --- Export ---

class TestGapReportExporter:
    def _make_report(self):
        return GapReport(
            id="r1", project_id="p1",
            summary=GapSummary(total_code_elements=5, undocumented=2),
            gaps=[
                GapItem(
                    id="g1", report_id="r1",
                    gap_type=GapType.UNDOCUMENTED, severity=Severity.HIGH,
                    code_element_name="MyClass", file_path="a.java", line=10,
                ),
            ],
        )

    def test_to_json(self):
        report = self._make_report()
        result = GapReportExporter.to_json(report)
        data = __import__("json").loads(result)
        assert data["id"] == "r1"
        assert len(data["gaps"]) == 1
        assert data["gaps"][0]["gap_type"] == "undocumented"

    def test_to_csv(self):
        report = self._make_report()
        result = GapReportExporter.to_csv(report)
        assert "undocumented" in result
        assert "MyClass" in result
        assert "a.java" in result
        lines = result.strip().split("\n")
        assert len(lines) == 2  # header + 1 row


# --- False Positive Management ---

class TestFalsePositiveManager:
    def test_mark_and_get(self, tmp_path):
        db = MetadataDB(db_path=tmp_path / "test.db")
        p = Project(id="p1", name="Test")
        db.save_project(p)
        report = GapReport(id="r1", project_id="p1")
        db.save_gap_report(report)
        item = GapItem(
            id="g1", report_id="r1",
            gap_type=GapType.UNDOCUMENTED, severity=Severity.LOW,
        )
        db.save_gap_items([item])

        mgr = FalsePositiveManager(db)
        mgr.mark_false_positive("g1")

        fps = db.get_false_positives("p1")
        assert len(fps) == 1

        patterns = mgr.get_false_positive_patterns("p1")
        assert patterns[0]["gap_type"] == "undocumented"
        assert patterns[0]["count"] == 1

        mgr.unmark_false_positive("g1")
        assert len(db.get_false_positives("p1")) == 0
        db.close()


# --- Full Analyzer (with mocks) ---

class TestGapAnalyzerIntegration:
    def test_analyze_produces_report(self, tmp_path):
        db = MetadataDB(db_path=tmp_path / "test.db")
        vs = VectorStoreService(persist_path=tmp_path / "chromadb")

        # Setup project with source, document, code elements
        p = Project(id="p1", name="Test")
        db.save_project(p)
        s = Source(id="s1", project_id="p1", source_type=SourceType.GIT, name="repo")
        db.save_source(s)
        d = Document(
            id="d1", source_id="s1", content_type=ContentType.CODE,
            file_path="src/service.py", content_hash="h1",
        )
        db.save_document(d)
        db.save_code_elements([
            CodeElement(
                id="e1", document_id="d1", kind=ElementKind.CLASS,
                name="UserService", short_name="UserService",
                file_path="src/service.py", start_line=1, end_line=20,
                visibility="public",
            ),
            CodeElement(
                id="e2", document_id="d1", kind=ElementKind.METHOD,
                name="UserService.processPayment", short_name="processPayment",
                file_path="src/service.py", start_line=5, end_line=10,
                visibility="public",
            ),
        ])

        # Add doc chunks to ChromaDB
        doc_col = vs.get_or_create_collection("p1_documentation")
        mock_emb = MagicMock()
        mock_emb.embed_single.return_value = [0.1, 0.2, 0.3]

        vs.upsert(
            doc_col,
            ids=["dc1"],
            documents=["The UserService manages all user operations including payment processing."],
            embeddings=[[0.1, 0.2, 0.3]],
            metadatas=[{"file_path": "docs/users.md"}],
        )

        analyzer = GapAnalyzer(
            db=db, vector_store=vs, embedding_service=mock_emb,
            llm_service=None, run_llm_analysis=False,
        )

        report = analyzer.analyze("p1")
        assert isinstance(report, GapReport)
        assert report.summary.total_code_elements == 2
        assert len(report.gaps) == 2
        # UserService should be matched via name
        matched = [g for g in report.gaps if g.gap_type == GapType.CONSISTENT]
        assert len(matched) >= 1

        db.close()
