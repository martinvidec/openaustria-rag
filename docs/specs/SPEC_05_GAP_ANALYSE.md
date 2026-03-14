# SPEC-05: Gap-Analyse Engine

**Referenz:** MVP_KONZEPT.md (Lokale Variante)
**Version:** 1.0
**Datum:** 2026-03-14

---

## 1. Ueberblick

Die Gap-Analyse ist das Kernfeature der Plattform. Sie identifiziert systematisch Abweichungen zwischen Code-Implementierung und Dokumentation. Diese Spezifikation beschreibt den dreistufigen Analyse-Algorithmus, die Datenflüsse und die Konfigurationsmoeglichkeiten.

---

## 2. Analyse-Architektur

```
Gap-Analyse Ausloesung (User klickt "Analyse starten")
     |
     v
+------------------------------------------+
| Stufe 1: Strukturelle Extraktion         |
|  - Code-Elemente laden (SQLite)          |
|  - Dokumentations-Chunks laden (ChromaDB)|
+------------------------------------------+
     |
     v
+------------------------------------------+
| Stufe 2: Matching                        |
|  - Namensbasiertes Matching              |
|  - Embedding-basiertes Matching          |
|  - Kategorisierung                       |
+------------------------------------------+
     |
     v
+------------------------------------------+
| Stufe 3: LLM-Analyse (Divergenzen)      |
|  - Nur fuer "Divergent"-Kandidaten       |
|  - Schweregrad-Bewertung                 |
|  - Empfehlungen generieren               |
+------------------------------------------+
     |
     v
+------------------------------------------+
| Report-Generierung                       |
|  - GapReport + GapItems speichern        |
|  - Summary berechnen                     |
+------------------------------------------+
```

---

## 3. GapAnalyzer Klasse

```python
from dataclasses import dataclass

@dataclass
class GapAnalysisConfig:
    # Matching
    name_similarity_threshold: float = 0.6    # Levenshtein-Schwelle
    embedding_similarity_threshold: float = 0.7  # Cosine-Schwelle
    max_embedding_candidates: int = 5         # Top-K pro Code-Element

    # LLM-Analyse
    run_llm_analysis: bool = True
    max_llm_analyses: int = 50               # Max Divergenz-Pruefungen pro Run
    llm_temperature: float = 0.1

    # Filter
    min_element_kind: list[str] = field(
        default_factory=lambda: ["class", "interface", "method", "function"]
    )
    exclude_test_files: bool = True
    exclude_patterns: list[str] = field(
        default_factory=lambda: ["**/test/**", "**/*Test.java", "**/*_test.py"]
    )

class GapAnalyzer:
    """Fuehrt die dreistufige Gap-Analyse durch."""

    def __init__(
        self,
        metadata_db: MetadataDB,
        vector_store: VectorStoreService,
        embedding_service: EmbeddingService,
        llm_service: LLMService,
        config: GapAnalysisConfig = GapAnalysisConfig(),
    ):
        self.db = metadata_db
        self.vector_store = vector_store
        self.embedding = embedding_service
        self.llm = llm_service
        self.config = config

    def analyze(self, project_id: str) -> GapReport:
        """Fuehrt eine vollstaendige Gap-Analyse fuer ein Projekt durch."""
        report_id = str(uuid4())

        # Stufe 1: Daten laden
        code_elements = self._load_code_elements(project_id)
        doc_chunks = self._load_doc_chunks(project_id)

        # Stufe 2: Matching
        matches = self._match_elements(code_elements, doc_chunks, project_id)

        # Stufe 3: LLM-Analyse fuer Divergenzen
        if self.config.run_llm_analysis:
            matches = self._analyze_divergences(matches)

        # Report erstellen
        gap_items = self._create_gap_items(matches, report_id)
        summary = self._compute_summary(code_elements, gap_items, doc_chunks)

        report = GapReport(
            id=report_id,
            project_id=project_id,
            summary=summary,
            gaps=[item for item in gap_items if item.gap_type != GapType.CONSISTENT],
        )

        # Persistieren
        self.db.save_gap_report(report)
        self.db.save_gap_items(gap_items)

        return report
```

---

## 4. Stufe 1: Strukturelle Extraktion

### 4.1 Code-Elemente laden

```python
    def _load_code_elements(self, project_id: str) -> list[CodeElement]:
        """Laedt alle relevanten Code-Elemente aus SQLite."""
        elements = self.db.get_code_elements_by_project(project_id)

        # Filtern
        filtered = []
        for elem in elements:
            # Nur relevante Element-Typen
            if elem.kind.value not in self.config.min_element_kind:
                continue

            # Test-Dateien ausschliessen
            if self.config.exclude_test_files:
                if any(fnmatch(elem.file_path, pat) for pat in self.config.exclude_patterns):
                    continue

            # Getter/Setter/toString etc. ausschliessen
            if self._is_boilerplate(elem):
                continue

            filtered.append(elem)

        return filtered

    def _is_boilerplate(self, element: CodeElement) -> bool:
        """Erkennt triviale Methoden die fuer Gap-Analyse irrelevant sind."""
        trivial_names = {
            "getters": lambda n: n.startswith("get") and len(n) > 3,
            "setters": lambda n: n.startswith("set") and len(n) > 3,
            "toString": lambda n: n in ("toString", "__str__", "__repr__"),
            "hashCode": lambda n: n in ("hashCode", "__hash__"),
            "equals": lambda n: n in ("equals", "__eq__"),
            "constructor": lambda n: n in ("__init__", "<init>"),
        }
        name = element.short_name
        return any(check(name) for check in trivial_names.values())
```

### 4.2 Dokumentations-Chunks laden

```python
    def _load_doc_chunks(self, project_id: str) -> list[RetrievedChunk]:
        """Laedt alle Dokumentations-Chunks aus ChromaDB."""
        collection_name = f"{project_id}_documentation"
        try:
            coll = self.vector_store.get_or_create_collection(collection_name)
            results = coll.get(include=["documents", "metadatas", "embeddings"])

            chunks = []
            for i in range(len(results["ids"])):
                chunks.append(RetrievedChunk(
                    chunk_id=results["ids"][i],
                    content=results["documents"][i],
                    metadata=results["metadatas"][i],
                    similarity_score=0.0,  # Wird spaeter gesetzt
                ))
            return chunks
        except Exception as e:
            logger.warning(f"Error loading doc chunks: {e}")
            return []
```

---

## 5. Stufe 2: Matching-Algorithmus

### 5.1 Matching-Prozess

```python
@dataclass
class MatchResult:
    code_element: CodeElement
    matched_doc_chunk: RetrievedChunk | None = None
    match_type: str = ""                  # "name" | "embedding" | "none"
    similarity_score: float = 0.0
    gap_type: GapType = GapType.UNDOCUMENTED
    # Wird in Stufe 3 weiter angereichert:
    llm_analysis: str | None = None
    severity: Severity = Severity.MEDIUM
    divergence_description: str = ""
    recommendation: str = ""
```

```python
    def _match_elements(
        self,
        code_elements: list[CodeElement],
        doc_chunks: list[RetrievedChunk],
        project_id: str,
    ) -> list[MatchResult]:
        """Matcht Code-Elemente mit Dokumentations-Chunks."""
        results = []

        for element in code_elements:
            # Schritt 1: Namensbasiertes Matching
            name_match = self._name_match(element, doc_chunks)
            if name_match and name_match.similarity_score >= self.config.name_similarity_threshold:
                results.append(MatchResult(
                    code_element=element,
                    matched_doc_chunk=name_match.chunk,
                    match_type="name",
                    similarity_score=name_match.similarity_score,
                    gap_type=GapType.DIVERGENT,  # Vorlaeufig, wird in Stufe 3 geprueft
                ))
                continue

            # Schritt 2: Embedding-basiertes Matching
            embedding_match = self._embedding_match(element, project_id)
            if embedding_match and embedding_match.similarity_score >= self.config.embedding_similarity_threshold:
                results.append(MatchResult(
                    code_element=element,
                    matched_doc_chunk=embedding_match,
                    match_type="embedding",
                    similarity_score=embedding_match.similarity_score,
                    gap_type=GapType.DIVERGENT,  # Vorlaeufig
                ))
                continue

            # Kein Match gefunden
            results.append(MatchResult(
                code_element=element,
                match_type="none",
                gap_type=GapType.UNDOCUMENTED,
                severity=self._estimate_severity(element),
            ))

        # Unimplemented pruefen: Doku-Chunks ohne Code-Match
        unimplemented = self._find_unimplemented(doc_chunks, results)
        results.extend(unimplemented)

        return results
```

### 5.2 Namensbasiertes Matching

```python
@dataclass
class NameMatchResult:
    chunk: RetrievedChunk
    similarity_score: float
    matched_term: str

    def _name_match(
        self,
        element: CodeElement,
        doc_chunks: list[RetrievedChunk],
    ) -> NameMatchResult | None:
        """Sucht Code-Element-Namen in Dokumentations-Chunks."""
        # Verschiedene Namensformen generieren
        search_terms = self._generate_search_terms(element)

        best_match = None
        best_score = 0.0

        for chunk in doc_chunks:
            content_lower = chunk.content.lower()
            for term in search_terms:
                if term.lower() in content_lower:
                    # Exakter Treffer
                    score = 1.0
                else:
                    # Fuzzy Matching auf Woerter im Chunk
                    score = self._fuzzy_match_in_text(term, chunk.content)

                if score > best_score:
                    best_score = score
                    best_match = NameMatchResult(
                        chunk=chunk,
                        similarity_score=score,
                        matched_term=term,
                    )

        return best_match

    def _generate_search_terms(self, element: CodeElement) -> list[str]:
        """Generiert verschiedene Suchformen fuer einen Element-Namen."""
        name = element.short_name
        terms = [name]

        # CamelCase aufloesen: "createUser" → "create user", "create_user"
        words = self._split_camel_case(name)
        if len(words) > 1:
            terms.append(" ".join(words))
            terms.append("_".join(words))
            terms.append("-".join(words))

        # Vollqualifizierter Name
        if "." in element.name:
            terms.append(element.name)

        return terms

    @staticmethod
    def _split_camel_case(name: str) -> list[str]:
        """Splittet CamelCase in Woerter."""
        import re
        words = re.sub(r'([A-Z])', r' \1', name).split()
        return [w.lower() for w in words if w]

    def _fuzzy_match_in_text(self, term: str, text: str) -> float:
        """Fuzzy-Matching eines Terms gegen Woerter im Text."""
        from difflib import SequenceMatcher
        term_lower = term.lower()
        words = text.lower().split()

        best_ratio = 0.0
        for word in words:
            ratio = SequenceMatcher(None, term_lower, word).ratio()
            best_ratio = max(best_ratio, ratio)

        # Auch gegen Zwei-Wort-Kombinationen pruefen
        for i in range(len(words) - 1):
            two_words = f"{words[i]} {words[i+1]}"
            ratio = SequenceMatcher(None, term_lower, two_words).ratio()
            best_ratio = max(best_ratio, ratio)

        return best_ratio
```

### 5.3 Embedding-basiertes Matching

```python
    def _embedding_match(
        self,
        element: CodeElement,
        project_id: str,
    ) -> RetrievedChunk | None:
        """Sucht semantisch aehnliche Dokumentations-Chunks per Embedding."""
        # Beschreibung des Code-Elements fuer Embedding zusammenbauen
        description = self._element_to_search_text(element)

        # Embedding erzeugen
        query_text = EmbeddingPreprocessor.preprocess_query(description)
        embedding = self.embedding.embed_single(query_text)

        # In Doku-Collection suchen
        results = self.vector_store.query(
            collection=f"{project_id}_documentation",
            query_embedding=embedding,
            top_k=self.config.max_embedding_candidates,
        )

        if not results["ids"][0]:
            return None

        # Besten Treffer zurueckgeben
        best_idx = 0
        best_similarity = 1 - results["distances"][0][0]  # Distance → Similarity

        if best_similarity >= self.config.embedding_similarity_threshold:
            return RetrievedChunk(
                chunk_id=results["ids"][0][best_idx],
                content=results["documents"][0][best_idx],
                metadata=results["metadatas"][0][best_idx],
                similarity_score=best_similarity,
            )

        return None

    def _element_to_search_text(self, element: CodeElement) -> str:
        """Erstellt einen suchbaren Text aus einem Code-Element."""
        parts = []
        parts.append(f"{element.kind.value}: {element.short_name}")
        if element.signature:
            parts.append(f"Signatur: {element.signature}")
        if element.docstring:
            parts.append(f"Beschreibung: {element.docstring}")
        if element.annotations:
            parts.append(f"Annotationen: {', '.join(element.annotations)}")
        if element.implements:
            parts.append(f"Implementiert: {', '.join(element.implements)}")
        return "\n".join(parts)
```

### 5.4 Unimplemented-Erkennung

```python
    def _find_unimplemented(
        self,
        doc_chunks: list[RetrievedChunk],
        existing_matches: list[MatchResult],
    ) -> list[MatchResult]:
        """Findet Dokumentations-Chunks die keinem Code-Element zugeordnet sind.
        Diese koennten auf fehlende Implementierung hindeuten.
        """
        # Bereits gematchte Doc-Chunk-IDs sammeln
        matched_chunk_ids = {
            m.matched_doc_chunk.chunk_id
            for m in existing_matches
            if m.matched_doc_chunk
        }

        unimplemented = []
        for chunk in doc_chunks:
            if chunk.chunk_id in matched_chunk_ids:
                continue

            # Pruefen ob der Chunk technische Konzepte beschreibt
            # (nicht nur allgemeine Prosa)
            if self._describes_implementation(chunk.content):
                unimplemented.append(MatchResult(
                    code_element=None,  # Kein Code-Element
                    matched_doc_chunk=chunk,
                    match_type="none",
                    gap_type=GapType.UNIMPLEMENTED,
                    severity=Severity.LOW,  # Niedrig, da oft False Positive
                    divergence_description=(
                        f"Dokumentation beschreibt Funktionalitaet, "
                        f"aber kein entsprechendes Code-Element gefunden."
                    ),
                ))

        return unimplemented

    def _describes_implementation(self, text: str) -> bool:
        """Heuristik: Enthaelt der Text technische Beschreibungen?"""
        tech_indicators = [
            "implementiert", "implemented", "methode", "method",
            "klasse", "class", "schnittstelle", "interface",
            "api", "endpoint", "service", "controller",
            "datenbank", "database", "tabelle", "table",
        ]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in tech_indicators)
```

---

## 6. Stufe 3: LLM-basierte Divergenz-Analyse

### 6.1 Divergenz-Pruefung

```python
    def _analyze_divergences(self, matches: list[MatchResult]) -> list[MatchResult]:
        """Nutzt das LLM um gematchte Paare auf Divergenzen zu pruefen."""
        divergent_candidates = [
            m for m in matches
            if m.gap_type == GapType.DIVERGENT and m.matched_doc_chunk
        ]

        # Auf max_llm_analyses begrenzen (die mit hoechster Similarity zuerst)
        divergent_candidates.sort(key=lambda m: m.similarity_score, reverse=True)
        to_analyze = divergent_candidates[:self.config.max_llm_analyses]

        for match in to_analyze:
            try:
                analysis = self._llm_analyze_pair(
                    code_element=match.code_element,
                    doc_chunk=match.matched_doc_chunk,
                )
                match.llm_analysis = analysis.raw_response
                match.gap_type = analysis.gap_type
                match.severity = analysis.severity
                match.divergence_description = analysis.divergence
                match.recommendation = analysis.recommendation
            except Exception as e:
                logger.warning(f"LLM analysis failed for {match.code_element.name}: {e}")
                # Fallback: als DIVERGENT mit MEDIUM belassen

        return matches
```

### 6.2 LLM Prompt fuer Divergenz-Analyse

```python
@dataclass
class LLMAnalysisResult:
    gap_type: GapType
    severity: Severity
    divergence: str
    recommendation: str
    raw_response: str

    def _llm_analyze_pair(
        self,
        code_element: CodeElement,
        doc_chunk: RetrievedChunk,
    ) -> LLMAnalysisResult:
        """Analysiert ein Code-Doku-Paar mittels LLM."""

        # Code-Kontext aufbereiten
        code_context = f"""Element: {code_element.name} ({code_element.kind.value})
Datei: {code_element.file_path}, Zeile {code_element.start_line}-{code_element.end_line}
Signatur: {code_element.signature or 'N/A'}
Annotationen: {', '.join(code_element.annotations) if code_element.annotations else 'keine'}
Docstring: {code_element.docstring or 'keiner'}"""

        # Dokumentations-Kontext
        doc_context = doc_chunk.content

        prompt = f"""Analysiere die folgende Code-Implementierung und die zugehoerige Dokumentation.
Identifiziere ob die Dokumentation mit dem Code uebereinstimmt.

CODE-ELEMENT:
{code_context}

DOKUMENTATION:
{doc_context}

Antworte EXAKT im folgenden Format (eine Zeile pro Feld):
UEBEREINSTIMMUNG: [Ja|Teilweise|Nein]
ABWEICHUNGEN: [Beschreibung der Abweichungen oder "keine"]
SCHWEREGRAD: [Niedrig|Mittel|Hoch|Kritisch]
EMPFEHLUNG: [Konkrete Empfehlung zur Behebung]"""

        response = self.llm.generate(prompt)
        return self._parse_llm_response(response)

    def _parse_llm_response(self, response: str) -> LLMAnalysisResult:
        """Parst die strukturierte LLM-Antwort."""
        lines = response.strip().split("\n")
        result = {
            "uebereinstimmung": "Teilweise",
            "abweichungen": "",
            "schweregrad": "Mittel",
            "empfehlung": "",
        }

        for line in lines:
            line = line.strip()
            if line.startswith("UEBEREINSTIMMUNG:"):
                result["uebereinstimmung"] = line.split(":", 1)[1].strip()
            elif line.startswith("ABWEICHUNGEN:"):
                result["abweichungen"] = line.split(":", 1)[1].strip()
            elif line.startswith("SCHWEREGRAD:"):
                result["schweregrad"] = line.split(":", 1)[1].strip()
            elif line.startswith("EMPFEHLUNG:"):
                result["empfehlung"] = line.split(":", 1)[1].strip()

        # Mapping
        gap_type_map = {
            "Ja": GapType.CONSISTENT,
            "Teilweise": GapType.DIVERGENT,
            "Nein": GapType.DIVERGENT,
        }
        severity_map = {
            "Niedrig": Severity.LOW,
            "Mittel": Severity.MEDIUM,
            "Hoch": Severity.HIGH,
            "Kritisch": Severity.CRITICAL,
        }

        return LLMAnalysisResult(
            gap_type=gap_type_map.get(result["uebereinstimmung"], GapType.DIVERGENT),
            severity=severity_map.get(result["schweregrad"], Severity.MEDIUM),
            divergence=result["abweichungen"],
            recommendation=result["empfehlung"],
            raw_response=response,
        )
```

---

## 7. Schweregrad-Heuristik

```python
    def _estimate_severity(self, element: CodeElement) -> Severity:
        """Schaetzt den Schweregrad einer fehlenden Dokumentation."""

        # Kritisch: Oeffentliche API-Endpunkte
        if any("Mapping" in a or "route" in a.lower() for a in element.annotations):
            return Severity.HIGH

        # Hoch: Oeffentliche Interfaces und abstrakte Klassen
        if element.kind == ElementKind.INTERFACE:
            return Severity.HIGH
        if element.visibility == "public" and element.kind == ElementKind.CLASS:
            return Severity.MEDIUM

        # Mittel: Oeffentliche Methoden
        if element.visibility == "public" and element.kind in (ElementKind.METHOD, ElementKind.FUNCTION):
            return Severity.MEDIUM

        # Niedrig: Private/Protected Elemente
        if element.visibility in ("private", "protected"):
            return Severity.LOW

        return Severity.MEDIUM
```

---

## 8. Report-Generierung

### 8.1 Summary berechnen

```python
    def _compute_summary(
        self,
        code_elements: list[CodeElement],
        gap_items: list[GapItem],
        doc_chunks: list[RetrievedChunk],
    ) -> GapSummary:
        total = len(code_elements)
        consistent = sum(1 for g in gap_items if g.gap_type == GapType.CONSISTENT)
        undocumented = sum(1 for g in gap_items if g.gap_type == GapType.UNDOCUMENTED)
        unimplemented = sum(1 for g in gap_items if g.gap_type == GapType.UNIMPLEMENTED)
        divergent = sum(1 for g in gap_items if g.gap_type == GapType.DIVERGENT)

        coverage = consistent / total if total > 0 else 0.0

        return GapSummary(
            total_code_elements=total,
            documented=consistent,
            undocumented=undocumented,
            unimplemented=unimplemented,
            divergent=divergent,
            documentation_coverage=round(coverage, 3),
        )
```

### 8.2 Export-Formate

```python
class GapReportExporter:
    """Exportiert Gap-Reports in verschiedene Formate."""

    @staticmethod
    def to_json(report: GapReport) -> str:
        """Exportiert als JSON."""
        return json.dumps({
            "project": report.project_id,
            "analysis_date": report.created_at.isoformat(),
            "summary": {
                "total_code_elements": report.summary.total_code_elements,
                "documented": report.summary.documented,
                "undocumented": report.summary.undocumented,
                "unimplemented": report.summary.unimplemented,
                "divergent": report.summary.divergent,
                "documentation_coverage": f"{report.summary.documentation_coverage:.1%}",
            },
            "gaps": [
                {
                    "type": g.gap_type.value,
                    "severity": g.severity.value,
                    "code_element": g.code_element_name,
                    "file": g.file_path,
                    "line": g.line,
                    "doc_reference": g.doc_reference,
                    "description": g.divergence_description,
                    "recommendation": g.recommendation,
                }
                for g in report.gaps
            ],
        }, indent=2, ensure_ascii=False)

    @staticmethod
    def to_csv(report: GapReport) -> str:
        """Exportiert als CSV."""
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow([
            "Typ", "Schweregrad", "Code-Element", "Datei",
            "Zeile", "Doku-Referenz", "Beschreibung", "Empfehlung"
        ])
        for g in report.gaps:
            writer.writerow([
                g.gap_type.value, g.severity.value,
                g.code_element_name, g.file_path,
                g.line or "", g.doc_reference or "",
                g.divergence_description, g.recommendation,
            ])
        return output.getvalue()
```

---

## 9. False-Positive-Management

### 9.1 User-Feedback

```python
class FalsePositiveManager:
    """Verwaltet User-Feedback zu Gap-Analyse-Ergebnissen."""

    def __init__(self, metadata_db: MetadataDB):
        self.db = metadata_db

    def mark_false_positive(self, gap_item_id: str) -> None:
        """Markiert einen Gap-Eintrag als False Positive."""
        self.db.update_gap_item(gap_item_id, {"is_false_positive": True})

    def unmark_false_positive(self, gap_item_id: str) -> None:
        self.db.update_gap_item(gap_item_id, {"is_false_positive": False})

    def get_false_positive_patterns(self, project_id: str) -> list[dict]:
        """Extrahiert Muster aus False Positives fuer zukuenftige Analysen.
        Z.B.: Alle Methoden mit Namen 'init*' sind FP → zukuenftig ausschliessen.
        """
        fps = self.db.get_false_positives(project_id)
        patterns = {}
        for fp in fps:
            name = fp.code_element_name
            # Praefix-Muster erkennen
            prefix = name.split(".")[- 1][:4] if "." in name else name[:4]
            patterns[prefix] = patterns.get(prefix, 0) + 1

        # Nur Muster die >= 3 mal auftreten
        return [
            {"pattern": p, "count": c}
            for p, c in patterns.items()
            if c >= 3
        ]
```

---

## 10. Konfiguration

```yaml
gap_analysis:
  matching:
    name_similarity_threshold: 0.6
    embedding_similarity_threshold: 0.7
    max_embedding_candidates: 5

  llm:
    enabled: true
    max_analyses_per_run: 50
    temperature: 0.1
    timeout_seconds: 60

  filters:
    element_kinds: ["class", "interface", "method", "function"]
    exclude_test_files: true
    exclude_patterns:
      - "**/test/**"
      - "**/*Test.java"
      - "**/*_test.py"
      - "**/*Spec.scala"

  severity_rules:
    api_endpoints: "high"        # @GetMapping etc.
    public_interfaces: "high"
    public_classes: "medium"
    public_methods: "medium"
    private_elements: "low"
```

---

## 11. Performance-Ueberlegungen

| Operation | Geschwindigkeit | Engpass |
|---|---|---|
| Code-Elemente laden (SQLite) | ~10ms fuer 1000 Elemente | Kein |
| Namensbasiertes Matching | ~50ms fuer 100 Elemente × 500 Chunks | CPU (Fuzzy Matching) |
| Embedding-Matching (1 Element) | ~200-500ms (Ollama + ChromaDB) | Ollama Inference |
| Embedding-Matching (100 Elemente) | ~20-50s | Ollama Inference |
| LLM-Analyse (1 Paar) | ~15-30s (Mistral 7B, CPU) | Ollama Inference |
| LLM-Analyse (50 Paare) | ~12-25 Min | Ollama Inference |
| Gesamte Analyse (500 Elemente) | ~15-30 Min | Ollama Inference |

**Optimierungen:**
- Embedding-Matching wird vor LLM-Analyse ausgefuehrt (guenstiger)
- LLM-Analyse nur fuer Divergenz-Kandidaten (typisch 5-15% der Elemente)
- `max_llm_analyses` begrenzt die Anzahl teurer LLM-Aufrufe
- Caching von Embeddings fuer wiederholte Analysen

---

## 12. Testbarkeit

```python
class TestGapAnalyzer:
    def test_boilerplate_excluded(self):
        analyzer = GapAnalyzer(...)
        getter = CodeElement(id="1", document_id="d1", kind=ElementKind.METHOD,
                            name="getUser", short_name="getUser", file_path="User.java",
                            start_line=1, end_line=3)
        assert analyzer._is_boilerplate(getter) is True

    def test_name_matching_camelcase(self):
        analyzer = GapAnalyzer(...)
        element = CodeElement(id="1", document_id="d1", kind=ElementKind.METHOD,
                             name="createUser", short_name="createUser", file_path="f.java",
                             start_line=1, end_line=5)
        doc = RetrievedChunk("c1", "The system can create a user via API", {}, 0.0)
        result = analyzer._name_match(element, [doc])
        assert result is not None
        assert result.similarity_score > 0.5

    def test_severity_api_endpoint_is_high(self):
        analyzer = GapAnalyzer(...)
        element = CodeElement(id="1", document_id="d1", kind=ElementKind.METHOD,
                             name="createUser", short_name="createUser", file_path="f.java",
                             start_line=1, end_line=5,
                             annotations=["@PostMapping(\"/users\")"])
        assert analyzer._estimate_severity(element) == Severity.HIGH

    def test_llm_response_parsing(self):
        analyzer = GapAnalyzer(...)
        response = """UEBEREINSTIMMUNG: Nein
ABWEICHUNGEN: Code validiert lokal, Doku beschreibt externen Service
SCHWEREGRAD: Hoch
EMPFEHLUNG: Dokumentation aktualisieren"""
        result = analyzer._parse_llm_response(response)
        assert result.gap_type == GapType.DIVERGENT
        assert result.severity == Severity.HIGH

    def test_full_analysis_e2e(self):
        """End-to-End Test mit Testdaten."""
        # 1. Test-Code-Elemente und -Doku erstellen
        # 2. Analyse ausfuehren
        # 3. Report pruefen: Coverage, Gap-Typen, etc.
```
