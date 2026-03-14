# SPEC-03: Ingestion Pipeline

**Referenz:** MVP_KONZEPT.md (Lokale Variante)
**Version:** 1.0
**Datum:** 2026-03-14

---

## 1. Ueberblick

Die Ingestion Pipeline verarbeitet Roh-Dokumente aus den Konnektoren und ueberfuehrt sie in indexierte, durchsuchbare Chunks in der Vector DB. Diese Spezifikation beschreibt die einzelnen Stufen: Code-Parsing (tree-sitter), Chunking, Metadata-Enrichment und Embedding/Indexierung.

---

## 2. Pipeline-Architektur

```
RawDocument (aus Konnektor)
     |
     v
+---------------------------+
| 1. Format Detection       |  Bestimmt Verarbeitungspfad
+---------------------------+
     |
     +----------+----------+
     |          |          |
     v          v          v
  Code-     Markdown-   Config-
  Pipeline  Pipeline    Pipeline
     |          |          |
     v          v          v
+---------------------------+
| 2. Parsing                |  tree-sitter / MD Parser
+---------------------------+
     |
     v
+---------------------------+
| 3. Chunking               |  Semantisch, kontexterhaltend
+---------------------------+
     |
     v
+---------------------------+
| 4. Metadata Enrichment    |  Anreicherung mit Kontext
+---------------------------+
     |
     v
+---------------------------+
| 5. Embedding              |  Nomic Embed Text via Ollama
+---------------------------+
     |
     v
+---------------------------+
| 6. Indexierung             |  ChromaDB Upsert
+---------------------------+
```

### 2.1 Pipeline-Orchestrator

```python
from dataclasses import dataclass

@dataclass
class IngestionResult:
    documents_processed: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    chunks_created: int = 0
    code_elements_extracted: int = 0
    errors: list[str] = field(default_factory=list)

class IngestionPipeline:
    """Orchestriert die gesamte Ingestion von Roh-Dokumenten."""

    def __init__(
        self,
        code_parser: CodeParser,
        chunker: ChunkingService,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        metadata_db: MetadataDB,
    ):
        self.code_parser = code_parser
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.metadata_db = metadata_db

    def ingest(
        self,
        documents: Generator[RawDocument, None, None],
        project_id: str,
        source_id: str,
    ) -> IngestionResult:
        """Verarbeitet einen Stream von RawDocuments."""
        result = IngestionResult()

        for raw_doc in documents:
            try:
                # Change Detection
                content_hash = hashlib.sha256(
                    raw_doc.content.encode()
                ).hexdigest()
                if self.metadata_db.document_unchanged(source_id, raw_doc.file_path, content_hash):
                    result.documents_skipped += 1
                    continue

                # Dokument verarbeiten
                doc_id = self._process_document(
                    raw_doc, project_id, source_id, content_hash
                )
                result.documents_processed += 1

            except Exception as e:
                result.documents_failed += 1
                result.errors.append(f"{raw_doc.file_path}: {str(e)}")
                logger.error(f"Failed to ingest {raw_doc.file_path}: {e}")

        return result

    def _process_document(
        self,
        raw_doc: RawDocument,
        project_id: str,
        source_id: str,
        content_hash: str,
    ) -> str:
        """Verarbeitet ein einzelnes Dokument durch die gesamte Pipeline."""
        # 1. Dokument-Metadaten in SQLite speichern
        doc_id = str(uuid4())
        self.metadata_db.save_document(
            doc_id=doc_id,
            source_id=source_id,
            content_type=raw_doc.content_type,
            file_path=raw_doc.file_path,
            language=raw_doc.language,
            metadata=raw_doc.metadata,
            content_hash=content_hash,
        )

        # 2. Alte Daten loeschen (falls Re-Indexierung)
        self.vector_store.delete_by_document(doc_id)
        self.metadata_db.delete_code_elements(doc_id)

        # 3. Code-Elemente extrahieren (nur fuer Code-Dateien)
        code_elements = []
        if raw_doc.content_type == "code" and raw_doc.language:
            code_elements = self.code_parser.parse(
                raw_doc.content,
                raw_doc.language,
                raw_doc.file_path,
                doc_id,
            )
            self.metadata_db.save_code_elements(code_elements)

        # 4. Chunking
        chunks = self.chunker.chunk(
            content=raw_doc.content,
            content_type=raw_doc.content_type,
            language=raw_doc.language,
            file_path=raw_doc.file_path,
            code_elements=code_elements,
        )

        # 5. Metadata Enrichment
        for chunk in chunks:
            chunk.metadata.project_id = project_id
            chunk.metadata.source_id = source_id
            chunk.metadata.document_id = doc_id
            chunk.metadata.connector = raw_doc.metadata.get("connector", "")
            chunk.metadata.ingested_at = datetime.utcnow().isoformat()

        # 6. Embedding + Indexierung (in Batches)
        self._embed_and_index(chunks, project_id, raw_doc.content_type)

        return doc_id

    def _embed_and_index(
        self,
        chunks: list[Chunk],
        project_id: str,
        content_type: str,
        batch_size: int = 50,
    ) -> None:
        """Erzeugt Embeddings und indexiert in ChromaDB."""
        collection_name = f"{project_id}_{content_type}"

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c.content for c in batch]

            # Embeddings erzeugen (Ollama Batch-Call)
            embeddings = self.embedding_service.embed_batch(texts)

            # In ChromaDB speichern
            self.vector_store.upsert(
                collection=collection_name,
                ids=[c.id for c in batch],
                documents=texts,
                embeddings=embeddings,
                metadatas=[c.metadata.__dict__ for c in batch],
            )
```

---

## 3. Code-Parsing mit tree-sitter

### 3.1 CodeParser

```python
import tree_sitter_languages

class CodeParser:
    """Extrahiert strukturelle Code-Elemente via tree-sitter."""

    # tree-sitter Queries pro Sprache
    QUERIES: dict[str, dict[str, str]] = {
        "java": {
            "classes": """
                (class_declaration
                    name: (identifier) @class.name
                    interfaces: (super_interfaces)? @class.implements
                    body: (class_body) @class.body
                ) @class.def
            """,
            "methods": """
                (method_declaration
                    (modifiers)? @method.modifiers
                    type: (_) @method.return_type
                    name: (identifier) @method.name
                    parameters: (formal_parameters) @method.params
                    body: (block) @method.body
                ) @method.def
            """,
            "interfaces": """
                (interface_declaration
                    name: (identifier) @interface.name
                    body: (interface_body) @interface.body
                ) @interface.def
            """,
            "annotations": """
                (marker_annotation
                    name: (identifier) @annotation.name
                ) @annotation.def
                (annotation
                    name: (identifier) @annotation.name
                    arguments: (annotation_argument_list) @annotation.args
                ) @annotation.def
            """,
        },
        "python": {
            "classes": """
                (class_definition
                    name: (identifier) @class.name
                    body: (block) @class.body
                ) @class.def
            """,
            "functions": """
                (function_definition
                    name: (identifier) @func.name
                    parameters: (parameters) @func.params
                    body: (block) @func.body
                ) @func.def
            """,
        },
        "typescript": {
            "classes": """
                (class_declaration
                    name: (type_identifier) @class.name
                    body: (class_body) @class.body
                ) @class.def
            """,
            "functions": """
                (function_declaration
                    name: (identifier) @func.name
                    parameters: (formal_parameters) @func.params
                    body: (statement_block) @func.body
                ) @func.def
            """,
            "interfaces": """
                (interface_declaration
                    name: (type_identifier) @interface.name
                    body: (interface_body) @interface.body
                ) @interface.def
            """,
        },
    }

    def parse(
        self,
        content: str,
        language: str,
        file_path: str,
        document_id: str,
    ) -> list[CodeElement]:
        """Parst Source Code und extrahiert strukturelle Elemente."""
        if language not in self.QUERIES:
            logger.warning(f"No tree-sitter queries for language: {language}")
            return []

        parser = tree_sitter_languages.get_parser(language)
        tree = parser.parse(content.encode("utf-8"))
        ts_language = tree_sitter_languages.get_language(language)

        elements = []
        lines = content.split("\n")

        for query_name, query_str in self.QUERIES[language].items():
            query = ts_language.query(query_str)
            captures = query.captures(tree.root_node)

            for node, capture_name in captures:
                if not capture_name.endswith(".def"):
                    continue

                element = self._node_to_element(
                    node=node,
                    capture_name=capture_name,
                    query_name=query_name,
                    lines=lines,
                    file_path=file_path,
                    document_id=document_id,
                    content=content,
                )
                if element:
                    elements.append(element)

        # Parent-Child-Beziehungen aufloesen
        self._resolve_parents(elements)

        return elements

    def _node_to_element(
        self,
        node,
        capture_name: str,
        query_name: str,
        lines: list[str],
        file_path: str,
        document_id: str,
        content: str,
    ) -> CodeElement | None:
        """Konvertiert einen tree-sitter Node in ein CodeElement."""
        start_line = node.start_point[0] + 1  # 1-basiert
        end_line = node.end_point[0] + 1

        # Name extrahieren
        name_node = self._find_child_by_field(node, "name")
        if not name_node:
            return None
        name = content[name_node.start_byte:name_node.end_byte]

        # Element-Typ bestimmen
        kind_map = {
            "classes": ElementKind.CLASS,
            "methods": ElementKind.METHOD,
            "functions": ElementKind.FUNCTION,
            "interfaces": ElementKind.INTERFACE,
        }
        kind = kind_map.get(query_name, ElementKind.FUNCTION)

        # Signatur extrahieren (erste Zeile bis zum Body)
        signature = lines[start_line - 1].strip()

        # Docstring/Kommentar extrahieren
        docstring = self._extract_docstring(node, content, start_line, lines)

        # Annotationen extrahieren (Java)
        annotations = self._extract_annotations(node, content)

        return CodeElement(
            id=str(uuid4()),
            document_id=document_id,
            kind=kind,
            name=f"{file_path}:{name}",       # Fully qualified
            short_name=name,
            signature=signature,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            docstring=docstring,
            annotations=annotations,
        )

    def _extract_docstring(
        self,
        node,
        content: str,
        start_line: int,
        lines: list[str],
    ) -> str | None:
        """Extrahiert Docstring/Kommentar vor dem Element."""
        # Vorhergehende Zeilen nach Kommentar durchsuchen
        comment_lines = []
        for i in range(start_line - 2, max(start_line - 20, -1), -1):
            line = lines[i].strip()
            if line.startswith("//") or line.startswith("*") or line.startswith("/**") or line.startswith("*/"):
                comment_lines.insert(0, line)
            elif line.startswith("#"):  # Python
                comment_lines.insert(0, line)
            elif not line:
                continue  # Leerzeile ueberspringen
            else:
                break

        if comment_lines:
            return "\n".join(comment_lines)

        # Python: Docstring im Body
        if node.children:
            for child in node.children:
                if child.type == "block":
                    for stmt in child.children:
                        if stmt.type == "expression_statement":
                            for expr in stmt.children:
                                if expr.type == "string":
                                    return content[expr.start_byte:expr.end_byte].strip('"""\'\'\'')
        return None

    def _extract_annotations(self, node, content: str) -> list[str]:
        """Extrahiert Annotationen (Java/Kotlin/TypeScript Decorators)."""
        annotations = []
        if node.prev_sibling and node.prev_sibling.type == "modifiers":
            for child in node.prev_sibling.children:
                if child.type in ("marker_annotation", "annotation"):
                    annotations.append(content[child.start_byte:child.end_byte])
        return annotations

    def _find_child_by_field(self, node, field_name: str):
        """Findet ein Child-Node anhand des Feldnamens."""
        return node.child_by_field_name(field_name)

    def _resolve_parents(self, elements: list[CodeElement]) -> None:
        """Setzt parent_id fuer verschachtelte Elemente (Methoden in Klassen)."""
        # Sortiert nach Zeilenbereich: aeussere Elemente zuerst
        sorted_elements = sorted(elements, key=lambda e: (e.start_line, -e.end_line))
        for i, elem in enumerate(sorted_elements):
            for j in range(i - 1, -1, -1):
                parent = sorted_elements[j]
                if (parent.start_line <= elem.start_line
                    and parent.end_line >= elem.end_line
                    and parent.id != elem.id):
                    elem.parent_id = parent.id
                    elem.name = f"{parent.short_name}.{elem.short_name}"
                    break
```

### 3.2 Unterstuetzte Sprachen (MVP)

| Sprache | tree-sitter Grammar | Extrahierte Elemente |
|---|---|---|
| **Java** | `tree-sitter-java` | Klassen, Interfaces, Methoden, Enums, Annotationen |
| **Python** | `tree-sitter-python` | Klassen, Funktionen/Methoden, Decorators |
| **TypeScript** | `tree-sitter-typescript` | Klassen, Interfaces, Funktionen, Types |

### 3.3 Fallback-Parsing

Fuer Sprachen ohne tree-sitter-Queries:

```python
class RegexFallbackParser:
    """Einfacher Regex-basierter Parser als Fallback."""

    PATTERNS = {
        "class": r"(?:public\s+)?(?:abstract\s+)?class\s+(\w+)",
        "function": r"(?:def|function|func)\s+(\w+)\s*\(",
        "interface": r"interface\s+(\w+)",
    }

    def parse(self, content: str, file_path: str, document_id: str) -> list[CodeElement]:
        elements = []
        for line_num, line in enumerate(content.split("\n"), 1):
            for kind_str, pattern in self.PATTERNS.items():
                match = re.search(pattern, line)
                if match:
                    elements.append(CodeElement(
                        id=str(uuid4()),
                        document_id=document_id,
                        kind=ElementKind(kind_str),
                        name=match.group(1),
                        short_name=match.group(1),
                        signature=line.strip(),
                        file_path=file_path,
                        start_line=line_num,
                        end_line=line_num,
                    ))
        return elements
```

---

## 4. Chunking-Service

### 4.1 Strategie-Ueberblick

| Content-Typ | Strategie | Parameter |
|---|---|---|
| Code | tree-sitter-basiert: Klasse/Methode als Chunk | max. 2048 Tokens, mit Kontext |
| Documentation | Header-basiert: H1/H2/H3 Splits | 512-1024 Tokens, Overlap 128 |
| Config | Ganze Datei als ein Chunk | max. 2048 Tokens |

### 4.2 ChunkingService

```python
@dataclass
class ChunkConfig:
    code_max_tokens: int = 2048
    doc_max_tokens: int = 1024
    doc_min_tokens: int = 64
    doc_overlap_tokens: int = 128
    config_max_tokens: int = 2048
    include_context_header: bool = True  # Dateiname + Element-Info als Praefix

class ChunkingService:
    """Erstellt semantische Chunks aus Dokumenten."""

    def __init__(self, config: ChunkConfig = ChunkConfig()):
        self.config = config

    def chunk(
        self,
        content: str,
        content_type: str,
        language: str | None,
        file_path: str,
        code_elements: list[CodeElement] | None = None,
    ) -> list[Chunk]:
        if content_type == "code" and code_elements:
            return self._chunk_code(content, file_path, code_elements)
        elif content_type == "documentation":
            return self._chunk_documentation(content, file_path)
        else:
            return self._chunk_simple(content, file_path, content_type)

    def _chunk_code(
        self,
        content: str,
        file_path: str,
        code_elements: list[CodeElement],
    ) -> list[Chunk]:
        """Chunking entlang Code-Strukturen (tree-sitter-basiert)."""
        chunks = []
        lines = content.split("\n")
        covered_lines = set()

        # Sortiere Elemente: Top-Level zuerst
        top_level = [e for e in code_elements if e.parent_id is None]
        top_level.sort(key=lambda e: e.start_line)

        for element in top_level:
            start = element.start_line - 1  # 0-basiert
            end = element.end_line
            element_content = "\n".join(lines[start:end])

            # Kontext-Header voranstellen
            if self.config.include_context_header:
                header = f"# File: {file_path}\n# Element: {element.name} ({element.kind.value})\n\n"
                element_content = header + element_content

            token_count = self._estimate_tokens(element_content)

            if token_count <= self.config.code_max_tokens:
                # Ganzes Element passt in einen Chunk
                chunks.append(Chunk(
                    id=str(uuid4()),
                    document_id=element.document_id,
                    content=element_content,
                    chunk_index=len(chunks),
                    token_count=token_count,
                    metadata=ChunkMetadata(
                        source_type="code",
                        language=self._detect_language(file_path) or "",
                        file_path=file_path,
                        element_type=element.kind.value,
                        element_name=element.name,
                        start_line=element.start_line,
                        end_line=element.end_line,
                    ),
                ))
            else:
                # Element zu gross: Methoden einzeln chunken
                child_elements = [
                    e for e in code_elements if e.parent_id == element.id
                ]
                if child_elements:
                    for child in child_elements:
                        child_start = child.start_line - 1
                        child_end = child.end_line
                        child_content = "\n".join(lines[child_start:child_end])

                        if self.config.include_context_header:
                            header = f"# File: {file_path}\n# Element: {child.name} ({child.kind.value})\n\n"
                            child_content = header + child_content

                        chunks.append(Chunk(
                            id=str(uuid4()),
                            document_id=child.document_id,
                            content=child_content,
                            chunk_index=len(chunks),
                            token_count=self._estimate_tokens(child_content),
                            metadata=ChunkMetadata(
                                source_type="code",
                                language=self._detect_language(file_path) or "",
                                file_path=file_path,
                                element_type=child.kind.value,
                                element_name=child.name,
                                parent_element=element.short_name,
                                start_line=child.start_line,
                                end_line=child.end_line,
                            ),
                        ))
                else:
                    # Kein Child: nach Token-Grenze splitten
                    chunks.extend(
                        self._split_by_tokens(element_content, file_path, element)
                    )

            covered_lines.update(range(start, end))

        # Nicht abgedeckte Zeilen als zusaetzlichen Chunk (Imports, etc.)
        uncovered = []
        for i, line in enumerate(lines):
            if i not in covered_lines and line.strip():
                uncovered.append(line)
        if uncovered:
            uncovered_content = "\n".join(uncovered)
            if self._estimate_tokens(uncovered_content) >= 32:
                header = f"# File: {file_path}\n# Element: (file-level declarations)\n\n"
                chunks.append(Chunk(
                    id=str(uuid4()),
                    document_id=code_elements[0].document_id if code_elements else "",
                    content=header + uncovered_content,
                    chunk_index=len(chunks),
                    token_count=self._estimate_tokens(uncovered_content),
                    metadata=ChunkMetadata(
                        source_type="code",
                        file_path=file_path,
                        element_type="file_level",
                        element_name=file_path,
                    ),
                ))

        return chunks

    def _chunk_documentation(
        self,
        content: str,
        file_path: str,
    ) -> list[Chunk]:
        """Chunking entlang von Markdown-Headern."""
        chunks = []
        sections = self._split_by_headers(content)

        for section in sections:
            token_count = self._estimate_tokens(section["content"])

            if token_count < self.config.doc_min_tokens:
                # Zu kurz: mit naechstem Abschnitt zusammenfuegen
                continue

            if token_count <= self.config.doc_max_tokens:
                chunks.append(Chunk(
                    id=str(uuid4()),
                    document_id="",  # Wird spaeter gesetzt
                    content=section["content"],
                    chunk_index=len(chunks),
                    token_count=token_count,
                    metadata=ChunkMetadata(
                        source_type="documentation",
                        language="markdown",
                        file_path=file_path,
                        element_type="section",
                        element_name=section.get("header", file_path),
                    ),
                ))
            else:
                # Abschnitt zu gross: nach Absaetzen splitten mit Overlap
                sub_chunks = self._split_with_overlap(
                    section["content"],
                    self.config.doc_max_tokens,
                    self.config.doc_overlap_tokens,
                )
                for sub in sub_chunks:
                    chunks.append(Chunk(
                        id=str(uuid4()),
                        document_id="",
                        content=sub,
                        chunk_index=len(chunks),
                        token_count=self._estimate_tokens(sub),
                        metadata=ChunkMetadata(
                            source_type="documentation",
                            language="markdown",
                            file_path=file_path,
                            element_type="section",
                            element_name=section.get("header", file_path),
                        ),
                    ))

        return chunks

    def _chunk_simple(
        self,
        content: str,
        file_path: str,
        content_type: str,
    ) -> list[Chunk]:
        """Einfaches Chunking fuer Config-Dateien etc."""
        token_count = self._estimate_tokens(content)
        if token_count <= self.config.config_max_tokens:
            return [Chunk(
                id=str(uuid4()),
                document_id="",
                content=content,
                chunk_index=0,
                token_count=token_count,
                metadata=ChunkMetadata(
                    source_type=content_type,
                    file_path=file_path,
                    element_type="file",
                    element_name=file_path,
                ),
            )]
        return self._split_with_overlap(
            content, self.config.config_max_tokens, self.config.doc_overlap_tokens
        )

    def _split_by_headers(self, content: str) -> list[dict]:
        """Splittet Markdown-Inhalt an H1/H2/H3-Headern."""
        sections = []
        current_header = ""
        current_lines = []

        for line in content.split("\n"):
            if line.startswith(("# ", "## ", "### ")):
                if current_lines:
                    sections.append({
                        "header": current_header,
                        "content": "\n".join(current_lines),
                    })
                current_header = line.lstrip("#").strip()
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines:
            sections.append({
                "header": current_header,
                "content": "\n".join(current_lines),
            })

        return sections

    def _split_with_overlap(
        self,
        content: str,
        max_tokens: int,
        overlap_tokens: int,
    ) -> list[str]:
        """Splittet Text in Chunks mit Overlap."""
        paragraphs = content.split("\n\n")
        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self._estimate_tokens(para)
            if current_tokens + para_tokens > max_tokens and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                # Overlap: letzte Absaetze behalten
                overlap_chunk = []
                overlap_count = 0
                for p in reversed(current_chunk):
                    pt = self._estimate_tokens(p)
                    if overlap_count + pt > overlap_tokens:
                        break
                    overlap_chunk.insert(0, p)
                    overlap_count += pt
                current_chunk = overlap_chunk
                current_tokens = overlap_count
            current_chunk.append(para)
            current_tokens += para_tokens

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Grobe Token-Schaetzung: ~4 Zeichen pro Token."""
        return len(text) // 4

    @staticmethod
    def _detect_language(file_path: str) -> str | None:
        return detect_language(file_path)  # Aus SPEC_02 shared utilities
```

---

## 5. Embedding-Service

### 5.1 Ollama Embedding Integration

```python
import requests

class EmbeddingService:
    """Erzeugt Embeddings ueber Ollama REST API."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ):
        self.model = model
        self.base_url = base_url
        self._dimensions: int | None = None

    def embed_single(self, text: str) -> list[float]:
        """Erzeugt Embedding fuer einen einzelnen Text."""
        resp = requests.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Erzeugt Embeddings fuer eine Liste von Texten.
        Ollama unterstuetzt kein natives Batching,
        daher sequenziell mit Connection-Pooling.
        """
        embeddings = []
        session = requests.Session()
        for text in texts:
            resp = session.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["embedding"])
        session.close()
        return embeddings

    def get_dimensions(self) -> int:
        """Ermittelt die Dimensionalitaet des Embedding-Modells."""
        if self._dimensions is None:
            test_embedding = self.embed_single("test")
            self._dimensions = len(test_embedding)
        return self._dimensions

    def health_check(self) -> bool:
        """Prueft ob Ollama laeuft und das Modell verfuegbar ist."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False
```

### 5.2 Embedding-Praeprozessierung

Fuer optimale Embedding-Qualitaet werden Texte vor dem Embedding aufbereitet:

```python
class EmbeddingPreprocessor:
    """Bereitet Texte fuer Embedding auf."""

    @staticmethod
    def preprocess_code(text: str) -> str:
        """Entfernt Rauschen aus Code-Chunks."""
        # Leere Zeilen reduzieren
        lines = text.split("\n")
        cleaned = []
        prev_empty = False
        for line in lines:
            is_empty = not line.strip()
            if is_empty and prev_empty:
                continue
            cleaned.append(line)
            prev_empty = is_empty
        return "\n".join(cleaned)

    @staticmethod
    def preprocess_query(query: str) -> str:
        """Bereitet User-Queries fuer Embedding auf.
        Nomic Embed Text erwartet 'search_query: ' Praefix.
        """
        return f"search_query: {query}"

    @staticmethod
    def preprocess_document(text: str) -> str:
        """Bereitet Dokument-Texte fuer Embedding auf.
        Nomic Embed Text erwartet 'search_document: ' Praefix.
        """
        return f"search_document: {text}"
```

---

## 6. Vector Store Service

### 6.1 ChromaDB Integration

```python
import chromadb

class VectorStoreService:
    """Abstrahiert ChromaDB-Operationen."""

    def __init__(self, persist_path: str = "data/chromadb"):
        self.client = chromadb.PersistentClient(path=persist_path)

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        coll = self.get_or_create_collection(collection)
        coll.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 10,
        where: dict | None = None,
    ) -> dict:
        coll = self.get_or_create_collection(collection)
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        return coll.query(**kwargs)

    def delete_by_document(self, document_id: str) -> None:
        """Loescht alle Chunks eines Dokuments aus allen Collections."""
        for coll in self.client.list_collections():
            try:
                coll.delete(where={"document_id": document_id})
            except Exception:
                pass  # Collection hat evtl. keine passenden Eintraege

    def delete_collection(self, name: str) -> None:
        try:
            self.client.delete_collection(name)
        except ValueError:
            pass  # Collection existiert nicht

    def get_stats(self, collection: str) -> dict:
        coll = self.get_or_create_collection(collection)
        return {
            "name": collection,
            "count": coll.count(),
        }
```

---

## 7. Pipeline-Konfiguration

### 7.1 Default-Konfiguration

```yaml
ingestion:
  embedding:
    model: "nomic-embed-text"
    ollama_url: "http://localhost:11434"

  chunking:
    code_max_tokens: 2048
    doc_max_tokens: 1024
    doc_min_tokens: 64
    doc_overlap_tokens: 128
    config_max_tokens: 2048
    include_context_header: true

  code_parser:
    languages: ["java", "python", "typescript"]
    fallback_regex: true

  vector_store:
    persist_path: "data/chromadb"
    distance_metric: "cosine"

  batch_size: 50
  max_concurrent_documents: 4
```

---

## 8. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| tree-sitter Parse Error | Fallback auf Regex-Parser, Warnung loggen |
| Embedding API Timeout | 3 Retries mit Backoff, dann Dokument ueberspringen |
| ChromaDB Write Error | Retry 1x, dann Exception hochreichen |
| Unbekanntes Encoding | `errors="replace"` in `open()`, Warnung loggen |
| Token-Limit ueberschritten | Chunk wird weiter gesplittet |
| Leere Datei | Ueberspringen, `documents_skipped` erhoehen |

---

## 9. Testbarkeit

### 9.1 Unit Tests

```python
class TestChunkingService:
    def test_code_chunking_respects_class_boundaries(self):
        code = '''
class UserService:
    def create_user(self, name: str):
        return User(name=name)

    def delete_user(self, user_id: int):
        db.delete(user_id)
'''
        elements = [...]  # Mock CodeElements
        chunker = ChunkingService()
        chunks = chunker._chunk_code(code, "service.py", elements)
        # Chunks sollten Klasse/Methoden-Grenzen respektieren
        assert all("class UserService" in c.content or "def " in c.content for c in chunks)

    def test_doc_chunking_splits_at_headers(self):
        md = "# Intro\nText\n## Section 1\nMore text\n## Section 2\nFinal text"
        chunker = ChunkingService()
        chunks = chunker._chunk_documentation(md, "doc.md")
        assert len(chunks) >= 2

    def test_token_estimation(self):
        text = "Hello world"  # ~2.75 tokens
        assert ChunkingService._estimate_tokens(text) >= 2
```

### 9.2 Integration Tests

```python
class TestIngestionPipeline:
    def test_full_pipeline_git_repo(self, tmp_path):
        """Testet die gesamte Pipeline mit einem lokalen Test-Repo."""
        # 1. Test-Repo erstellen
        # 2. Git-Konnektor konfigurieren
        # 3. Pipeline ausfuehren
        # 4. ChromaDB-Inhalte pruefen
        # 5. SQLite-Metadaten pruefen

    def test_idempotent_reindex(self, tmp_path):
        """Zweimaliges Indexieren liefert gleiches Ergebnis."""
        # Chunk-Count nach erstem und zweitem Lauf vergleichen

    def test_incremental_update(self, tmp_path):
        """Nur geaenderte Dateien werden neu indexiert."""
        # 1. Initiale Indexierung
        # 2. Eine Datei aendern
        # 3. Erneut indexieren
        # 4. Nur geaenderte Datei sollte neu verarbeitet worden sein
```
