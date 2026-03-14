"""Three-stage gap analysis engine (SPEC-05)."""

import csv
import io
import json
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from ..db import MetadataDB
from ..ingestion.embedding_service import EmbeddingPreprocessor, EmbeddingService
from ..llm.ollama_client import LLMService
from ..models import (
    CodeElement,
    ElementKind,
    GapItem,
    GapReport,
    GapSummary,
    GapType,
    Severity,
)
from ..retrieval.vector_store import VectorStoreService
from .matching import (
    LLMAnalysisResult,
    MatchResult,
    element_to_search_text,
    estimate_severity,
    fuzzy_match_in_text,
    generate_search_terms,
    is_boilerplate,
)

logger = logging.getLogger(__name__)

GAP_CHECK_PROMPT = """Du bist ein Software-Qualitaetsanalyst.
Vergleiche den folgenden Code mit der zugehoerigen Dokumentation.
Antworte in genau diesem Format:

UEBEREINSTIMMUNG: [ja/nein]
ABWEICHUNGEN: [Beschreibung der Abweichungen oder "keine"]
SCHWEREGRAD: [low/medium/high/critical]
EMPFEHLUNG: [Empfehlung zur Behebung]

CODE-ELEMENT:
{code_text}

DOKUMENTATION:
{doc_text}

ANALYSE:"""


class GapAnalyzer:
    """Three-stage gap analysis: extraction → matching → LLM analysis."""

    def __init__(
        self,
        db: MetadataDB,
        vector_store: VectorStoreService,
        embedding_service: EmbeddingService,
        llm_service: LLMService | None = None,
        element_kinds: list[str] | None = None,
        exclude_test_files: bool = True,
        exclude_patterns: list[str] | None = None,
        name_similarity_threshold: float = 0.6,
        embedding_similarity_threshold: float = 0.7,
        max_embedding_candidates: int = 5,
        run_llm_analysis: bool = True,
        max_llm_analyses: int = 50,
    ):
        self.db = db
        self.vector_store = vector_store
        self.embedding = embedding_service
        self.llm = llm_service
        self.element_kinds = element_kinds or ["class", "interface", "method", "function"]
        self.exclude_test_files = exclude_test_files
        self.exclude_patterns = exclude_patterns or [
            "**/test/**", "**/*Test.java", "**/*_test.py",
        ]
        self.name_threshold = name_similarity_threshold
        self.embedding_threshold = embedding_similarity_threshold
        self.max_embedding_candidates = max_embedding_candidates
        self.run_llm_analysis = run_llm_analysis
        self.max_llm_analyses = max_llm_analyses

    def analyze(self, project_id: str) -> GapReport:
        """Run the full three-stage gap analysis."""
        # Stage 1: Load and filter
        code_elements = self._load_code_elements(project_id)
        doc_chunks = self._load_doc_chunks(project_id)

        # Stage 2: Matching
        matches = self._match_elements(code_elements, doc_chunks, project_id)

        # Stage 3: LLM divergence analysis (optional)
        if self.run_llm_analysis and self.llm:
            self._analyze_divergences(matches)

        # Build report
        report = GapReport(
            id=str(uuid.uuid4()),
            project_id=project_id,
        )
        gap_items = self._create_gap_items(matches, report.id)
        report.gaps = gap_items
        report.summary = self._compute_summary(code_elements, gap_items, doc_chunks)

        # Persist
        self.db.save_gap_report(report)
        if gap_items:
            self.db.save_gap_items(gap_items)

        return report

    # --- Stage 1: Structural Extraction ---

    def _load_code_elements(self, project_id: str) -> list[CodeElement]:
        elements = self.db.get_code_elements_by_project(project_id)
        return [
            e for e in elements
            if e.kind.value in self.element_kinds
            and not is_boilerplate(e)
            and not self._is_test_file(e.file_path)
        ]

    def _is_test_file(self, file_path: str) -> bool:
        if not self.exclude_test_files:
            return False
        fp_lower = file_path.lower()
        return any(
            p.replace("**", "").replace("/", "").replace("*", "") in fp_lower
            for p in self.exclude_patterns
        )

    def _load_doc_chunks(self, project_id: str) -> list[dict]:
        """Load all documentation chunks from ChromaDB."""
        col_name = self.vector_store.collection_name(project_id, "documentation")
        if col_name not in self.vector_store.list_collections():
            return []

        col = self.vector_store.get_or_create_collection(col_name)
        if col.count() == 0:
            return []

        result = col.get(include=["documents", "metadatas"])
        chunks = []
        for i, chunk_id in enumerate(result["ids"]):
            chunks.append({
                "id": chunk_id,
                "content": result["documents"][i],
                "metadata": result["metadatas"][i] if result["metadatas"] else {},
            })
        return chunks

    # --- Stage 2: Matching ---

    def _match_elements(
        self, code_elements: list[CodeElement], doc_chunks: list[dict], project_id: str
    ) -> list[MatchResult]:
        matches = []

        # Pre-lowercase all chunk contents for fast substring matching
        chunk_contents_lower = [c["content"].lower() for c in doc_chunks]

        for element in code_elements:
            match = MatchResult(code_element=element)

            # Name-based matching: fast exact substring first, then fuzzy fallback
            best_name_score = 0.0
            best_name_chunk = None
            search_terms = generate_search_terms(element)

            # Phase 1: Fast exact substring match
            for term in search_terms:
                term_lower = term.lower()
                if len(term_lower) < 3:
                    continue
                for i, content_lower in enumerate(chunk_contents_lower):
                    if term_lower in content_lower:
                        score = min(1.0, 0.8 + len(term_lower) / 100)
                        if score > best_name_score:
                            best_name_score = score
                            best_name_chunk = doc_chunks[i]
                        break
                if best_name_chunk:
                    break

            # Phase 2: Fuzzy fallback (only if no exact match, limit to first 20 chunks)
            if not best_name_chunk:
                for chunk in doc_chunks[:20]:
                    for term in search_terms:
                        result = fuzzy_match_in_text(
                            term, chunk["content"], threshold=self.name_threshold
                        )
                        if result.matched and result.score > best_name_score:
                            best_name_score = result.score
                            best_name_chunk = chunk

            if best_name_chunk:
                match.name_score = best_name_score
                match.doc_chunk_id = best_name_chunk["id"]
                match.doc_chunk_content = best_name_chunk["content"]
                match.doc_reference = best_name_chunk.get("metadata", {}).get("file_path", "")
                match.gap_type = GapType.CONSISTENT

            # Embedding-based matching (if name match failed)
            if not best_name_chunk:
                emb_match = self._embedding_match(element, project_id)
                if emb_match:
                    match.embedding_score = emb_match["score"]
                    match.doc_chunk_id = emb_match["id"]
                    match.doc_chunk_content = emb_match["content"]
                    match.doc_reference = emb_match.get("file_path", "")
                    match.gap_type = GapType.CONSISTENT

            matches.append(match)

        return matches

    def _embedding_match(self, element: CodeElement, project_id: str) -> dict | None:
        """Find documentation match via embedding similarity."""
        col_name = self.vector_store.collection_name(project_id, "documentation")
        if col_name not in self.vector_store.list_collections():
            return None

        col = self.vector_store.get_or_create_collection(col_name)
        if col.count() == 0:
            return None

        search_text = element_to_search_text(element)
        preprocessed = EmbeddingPreprocessor.preprocess_query(search_text)
        query_embedding = self.embedding.embed_single(preprocessed)

        result = self.vector_store.query(
            col, query_embedding, top_k=self.max_embedding_candidates
        )

        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        dists = result.get("distances", [[]])[0]
        metas = result.get("metadatas", [[]])[0]

        if ids:
            score = 1.0 - (dists[0] / 2.0)
            if score >= self.embedding_threshold:
                return {
                    "id": ids[0],
                    "content": docs[0],
                    "score": score,
                    "file_path": metas[0].get("file_path", "") if metas else "",
                }
        return None

    # --- Stage 3: LLM Divergence Analysis ---

    def _analyze_divergences(self, matches: list[MatchResult]) -> None:
        consistent = [m for m in matches if m.gap_type == GapType.CONSISTENT]
        analyzed = 0

        for match in consistent:
            if analyzed >= self.max_llm_analyses:
                break
            if not match.doc_chunk_content:
                continue

            result = self._llm_analyze_pair(
                match.code_element, match.doc_chunk_content
            )
            match.llm_analysis = result

            if not result.consistent:
                match.gap_type = GapType.DIVERGENT

            analyzed += 1

    def _llm_analyze_pair(
        self, element: CodeElement, doc_text: str
    ) -> LLMAnalysisResult:
        code_text = element_to_search_text(element)
        prompt = GAP_CHECK_PROMPT.format(code_text=code_text, doc_text=doc_text)

        try:
            response = self.llm.generate(prompt)
            return self._parse_llm_response(response)
        except Exception as e:
            logger.warning(f"LLM analysis failed for {element.name}: {e}")
            return LLMAnalysisResult(consistent=True, raw_response=str(e))

    @staticmethod
    def _parse_llm_response(response: str) -> LLMAnalysisResult:
        result = LLMAnalysisResult(raw_response=response)
        lines = response.strip().split("\n")

        for line in lines:
            line_lower = line.strip().lower()
            if line_lower.startswith("uebereinstimmung:"):
                value = line.split(":", 1)[1].strip().lower()
                result.consistent = value in ("ja", "yes", "true")
            elif line_lower.startswith("abweichungen:"):
                result.divergences = line.split(":", 1)[1].strip()
            elif line_lower.startswith("schweregrad:"):
                result.severity = line.split(":", 1)[1].strip()
            elif line_lower.startswith("empfehlung:"):
                result.recommendation = line.split(":", 1)[1].strip()

        return result

    # --- Report Building ---

    def _create_gap_items(
        self, matches: list[MatchResult], report_id: str
    ) -> list[GapItem]:
        items = []
        for match in matches:
            severity = estimate_severity(match.code_element)
            item = GapItem(
                id=str(uuid.uuid4()),
                report_id=report_id,
                gap_type=match.gap_type,
                severity=severity,
                code_element_id=match.code_element.id,
                code_element_name=match.code_element.name,
                file_path=match.code_element.file_path,
                line=match.code_element.start_line,
                doc_reference=match.doc_reference,
                doc_chunk_id=match.doc_chunk_id,
                similarity_score=max(match.name_score, match.embedding_score) or None,
                divergence_description=(
                    match.llm_analysis.divergences if match.llm_analysis else ""
                ),
                recommendation=(
                    match.llm_analysis.recommendation if match.llm_analysis else ""
                ),
                llm_analysis=(
                    match.llm_analysis.raw_response if match.llm_analysis else None
                ),
            )
            items.append(item)
        return items

    @staticmethod
    def _compute_summary(
        code_elements: list[CodeElement],
        gap_items: list[GapItem],
        doc_chunks: list[dict],
    ) -> GapSummary:
        total = len(code_elements)
        undocumented = sum(1 for i in gap_items if i.gap_type == GapType.UNDOCUMENTED)
        divergent = sum(1 for i in gap_items if i.gap_type == GapType.DIVERGENT)
        consistent = sum(1 for i in gap_items if i.gap_type == GapType.CONSISTENT)
        documented = consistent + divergent

        return GapSummary(
            total_code_elements=total,
            documented=documented,
            undocumented=undocumented,
            unimplemented=0,
            divergent=divergent,
            documentation_coverage=documented / total if total > 0 else 0.0,
        )


# --- Export ---

class GapReportExporter:

    @staticmethod
    def to_json(report: GapReport) -> str:
        data = {
            "id": report.id,
            "project_id": report.project_id,
            "created_at": report.created_at.isoformat(),
            "summary": asdict(report.summary),
            "gaps": [
                {
                    "id": g.id,
                    "gap_type": g.gap_type.value,
                    "severity": g.severity.value,
                    "code_element_name": g.code_element_name,
                    "file_path": g.file_path,
                    "line": g.line,
                    "doc_reference": g.doc_reference,
                    "similarity_score": g.similarity_score,
                    "divergence_description": g.divergence_description,
                    "recommendation": g.recommendation,
                    "is_false_positive": g.is_false_positive,
                }
                for g in report.gaps
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def to_csv(report: GapReport) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "gap_type", "severity", "code_element", "file_path", "line",
            "doc_reference", "similarity_score", "divergence", "recommendation",
        ])
        for g in report.gaps:
            writer.writerow([
                g.gap_type.value, g.severity.value, g.code_element_name,
                g.file_path, g.line, g.doc_reference or "",
                f"{g.similarity_score:.2f}" if g.similarity_score else "",
                g.divergence_description, g.recommendation,
            ])
        return output.getvalue()


# --- False Positive Management ---

class FalsePositiveManager:

    def __init__(self, db: MetadataDB):
        self.db = db

    def mark_false_positive(self, gap_item_id: str) -> None:
        self.db.update_gap_item(gap_item_id, is_false_positive=True)

    def unmark_false_positive(self, gap_item_id: str) -> None:
        self.db.update_gap_item(gap_item_id, is_false_positive=False)

    def get_false_positive_patterns(self, project_id: str) -> list[dict]:
        fps = self.db.get_false_positives(project_id)
        patterns: dict[str, int] = {}
        for fp in fps:
            key = fp.gap_type.value
            patterns[key] = patterns.get(key, 0) + 1
        return [{"gap_type": k, "count": v} for k, v in patterns.items()]
