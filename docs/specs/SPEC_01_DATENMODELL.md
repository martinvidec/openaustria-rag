# SPEC-01: Datenmodell & Persistenz

**Referenz:** MVP_KONZEPT.md (Lokale Variante)
**Version:** 1.0
**Datum:** 2026-03-14

---

## 1. Ueberblick

Dieses Dokument spezifiziert alle Datenmodelle, Schemas und Persistenzschichten der OpenAustria RAG Plattform. Es definiert die Struktur der Daten vom Eingang (Konnektoren) bis zur Speicherung (Vector DB, SQLite).

---

## 2. Kern-Datenmodelle

### 2.1 Project

Repraesentiert ein vom User angelegtes Analyseprojekt.

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class ProjectStatus(Enum):
    CREATED = "created"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"

@dataclass
class Project:
    id: str                              # UUID4
    name: str                            # Anzeigename, unique
    description: str = ""
    status: ProjectStatus = ProjectStatus.CREATED
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    settings: dict = field(default_factory=dict)
    # settings enthaelt:
    #   chunk_size: int (default 1024)
    #   chunk_overlap: int (default 128)
    #   similarity_threshold: float (default 0.7)
    #   languages: list[str] (default ["java", "python", "typescript"])
```

**SQLite-Tabelle:**

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settings TEXT DEFAULT '{}'  -- JSON
);
```

### 2.2 Source

Repraesentiert eine konfigurierte Datenquelle innerhalb eines Projekts.

```python
class SourceType(Enum):
    GIT = "git"
    ZIP = "zip"
    CONFLUENCE = "confluence"

class SourceStatus(Enum):
    CONFIGURED = "configured"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"

@dataclass
class Source:
    id: str                              # UUID4
    project_id: str                      # FK -> Project.id
    source_type: SourceType
    name: str                            # Anzeigename
    config: dict                         # Typ-spezifische Konfiguration
    status: SourceStatus = SourceStatus.CONFIGURED
    last_sync_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
```

**Config-Schema pro Source-Typ:**

```python
# Git
git_config = {
    "url": "https://github.com/org/repo.git",
    "branch": "main",                   # Optional, default: default branch
    "include_patterns": ["*.java", "*.py", "*.md"],  # Optional
    "exclude_patterns": ["**/test/**", "**/node_modules/**"],
    "auth": {                            # Optional
        "type": "token",                 # "token" | "ssh_key"
        "token": "ghp_..."
    }
}

# ZIP
zip_config = {
    "filename": "project-v1.0.zip",
    "upload_path": "/data/uploads/abc123.zip",
    "include_patterns": ["*.java", "*.py", "*.md"],
    "exclude_patterns": ["**/test/**"]
}

# Confluence
confluence_config = {
    "base_url": "https://company.atlassian.net",
    "space_key": "PROJ",
    "email": "user@company.com",
    "api_token": "...",                  # Verschluesselt gespeichert
    "page_filter": {                     # Optional
        "labels": ["architecture", "spec"],
        "exclude_titles": ["Meeting Notes*"]
    }
}
```

**SQLite-Tabelle:**

```sql
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    config TEXT NOT NULL,               -- JSON, Tokens verschluesselt
    status TEXT NOT NULL DEFAULT 'configured',
    last_sync_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
```

### 2.3 Document

Repraesentiert ein einzelnes Quelldokument (eine Datei, eine Confluence-Seite, etc.).

```python
class ContentType(Enum):
    CODE = "code"
    DOCUMENTATION = "documentation"
    SPECIFICATION = "specification"
    MODEL = "model"
    CONFIG = "config"

@dataclass
class Document:
    id: str                              # UUID4
    source_id: str                       # FK -> Source.id
    content: str                         # Roher Inhalt
    content_type: ContentType
    file_path: str                       # Relativer Pfad oder Confluence-URL
    language: str | None = None          # "java", "python", "markdown", etc.
    metadata: dict = field(default_factory=dict)
    # metadata enthaelt:
    #   size_bytes: int
    #   encoding: str
    #   last_modified: str (ISO 8601)
    #   git_commit: str (optional)
    #   git_author: str (optional)
    #   confluence_page_id: str (optional)
    #   confluence_version: int (optional)
    created_at: datetime = field(default_factory=datetime.utcnow)
```

**SQLite-Tabelle:**

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    language TEXT,
    metadata TEXT DEFAULT '{}',         -- JSON
    content_hash TEXT NOT NULL,         -- SHA-256 fuer Change Detection
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE INDEX idx_documents_source ON documents(source_id);
CREATE INDEX idx_documents_content_hash ON documents(content_hash);
```

**Hinweis:** Der `content`-Text wird NICHT in SQLite gespeichert (zu gross). Er wird nur waehrend der Ingestion im Speicher gehalten und dann als Chunks in die Vector DB geschrieben.

### 2.4 Chunk

Repraesentiert ein Teilstueck eines Dokuments, das in die Vector DB indexiert wird.

```python
@dataclass
class Chunk:
    id: str                              # UUID4
    document_id: str                     # FK -> Document.id
    content: str                         # Chunk-Text
    embedding: list[float] | None = None # 768-dim Vektor (Nomic Embed)
    chunk_index: int = 0                 # Position im Dokument
    token_count: int = 0
    metadata: ChunkMetadata = field(default_factory=lambda: ChunkMetadata())

@dataclass
class ChunkMetadata:
    source_type: str = ""                # "code" | "documentation" | ...
    connector: str = ""                  # "git" | "confluence" | "zip"
    language: str = ""                   # "java" | "python" | ...
    file_path: str = ""
    element_type: str = ""               # "class" | "method" | "page" | ...
    element_name: str = ""               # "UserService.createUser"
    project_id: str = ""
    source_id: str = ""
    document_id: str = ""
    start_line: int | None = None
    end_line: int | None = None
    parent_element: str | None = None    # z.B. Klasse fuer eine Methode
    ingested_at: str = ""                # ISO 8601
```

**ChromaDB-Speicherung:**

```python
# Collection-Naming: "{project_id}_{source_type}"
# z.B. "proj123_code", "proj123_documentation"

collection.add(
    ids=["chunk_uuid_1", "chunk_uuid_2"],
    documents=["chunk text 1", "chunk text 2"],
    embeddings=[[0.1, 0.2, ...], [0.3, 0.4, ...]],
    metadatas=[
        {
            "source_type": "code",
            "connector": "git",
            "language": "java",
            "file_path": "src/main/java/UserService.java",
            "element_type": "method",
            "element_name": "UserService.createUser",
            "project_id": "proj123",
            "source_id": "src456",
            "document_id": "doc789",
            "start_line": 45,
            "end_line": 72,
            "parent_element": "UserService",
            "ingested_at": "2026-03-14T10:00:00Z"
        },
        # ...
    ]
)
```

### 2.5 CodeElement

Repraesentiert ein strukturelles Code-Element, das von tree-sitter extrahiert wurde. Wird fuer die Gap-Analyse benoetigt.

```python
class ElementKind(Enum):
    CLASS = "class"
    INTERFACE = "interface"
    METHOD = "method"
    FUNCTION = "function"
    ENUM = "enum"
    CONSTANT = "constant"
    API_ENDPOINT = "api_endpoint"
    ENTITY = "entity"

@dataclass
class CodeElement:
    id: str                              # UUID4
    document_id: str                     # FK -> Document.id
    kind: ElementKind
    name: str                            # Vollqualifizierter Name
    short_name: str                      # Einfacher Name
    signature: str | None = None         # Methodensignatur
    visibility: str | None = None        # "public" | "private" | "protected"
    parent_id: str | None = None         # FK -> CodeElement.id (z.B. Klasse)
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    docstring: str | None = None         # Extrahierter Kommentar/Javadoc
    annotations: list[str] = field(default_factory=list)
    # z.B. ["@GetMapping(\"/users\")", "@Transactional"]
    implements: list[str] = field(default_factory=list)
    # z.B. ["Serializable", "UserRepository"]
    extends: str | None = None
```

**SQLite-Tabelle:**

```sql
CREATE TABLE code_elements (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    signature TEXT,
    visibility TEXT,
    parent_id TEXT,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    docstring TEXT,
    annotations TEXT DEFAULT '[]',      -- JSON array
    implements TEXT DEFAULT '[]',        -- JSON array
    extends TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES code_elements(id)
);

CREATE INDEX idx_code_elements_document ON code_elements(document_id);
CREATE INDEX idx_code_elements_kind ON code_elements(kind);
CREATE INDEX idx_code_elements_name ON code_elements(name);
```

### 2.6 GapReport

Repraesentiert das Ergebnis einer Gap-Analyse.

```python
class GapType(Enum):
    UNDOCUMENTED = "undocumented"         # Code ohne Doku
    UNIMPLEMENTED = "unimplemented"       # Doku ohne Code
    DIVERGENT = "divergent"               # Beides existiert, widerspricht sich
    CONSISTENT = "consistent"             # Uebereinstimmend

class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class GapReport:
    id: str                              # UUID4
    project_id: str                      # FK -> Project.id
    created_at: datetime = field(default_factory=datetime.utcnow)
    summary: GapSummary = field(default_factory=lambda: GapSummary())
    gaps: list[GapItem] = field(default_factory=list)

@dataclass
class GapSummary:
    total_code_elements: int = 0
    documented: int = 0
    undocumented: int = 0
    unimplemented: int = 0
    divergent: int = 0
    documentation_coverage: float = 0.0  # 0.0 - 1.0

@dataclass
class GapItem:
    id: str                              # UUID4
    report_id: str                       # FK -> GapReport.id
    gap_type: GapType
    severity: Severity
    code_element_id: str | None = None   # FK -> CodeElement.id
    code_element_name: str = ""
    file_path: str = ""
    line: int | None = None
    doc_reference: str | None = None     # Confluence-URL oder Markdown-Pfad
    doc_chunk_id: str | None = None      # FK -> Chunk.id
    similarity_score: float | None = None
    divergence_description: str = ""
    recommendation: str = ""
    llm_analysis: str | None = None      # Rohe LLM-Antwort fuer Divergenz
    is_false_positive: bool = False      # User-Feedback
```

**SQLite-Tabellen:**

```sql
CREATE TABLE gap_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL,              -- JSON (GapSummary)
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE gap_items (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    gap_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    code_element_id TEXT,
    code_element_name TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    line INTEGER,
    doc_reference TEXT,
    doc_chunk_id TEXT,
    similarity_score REAL,
    divergence_description TEXT DEFAULT '',
    recommendation TEXT DEFAULT '',
    llm_analysis TEXT,
    is_false_positive INTEGER DEFAULT 0,
    FOREIGN KEY (report_id) REFERENCES gap_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (code_element_id) REFERENCES code_elements(id)
);

CREATE INDEX idx_gap_items_report ON gap_items(report_id);
CREATE INDEX idx_gap_items_type ON gap_items(gap_type);
CREATE INDEX idx_gap_items_severity ON gap_items(severity);
```

### 2.7 ChatHistory

Speichert Chat-Verlaeufe pro Projekt.

```python
class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

@dataclass
class ChatMessage:
    id: str                              # UUID4
    project_id: str                      # FK -> Project.id
    session_id: str                      # Gruppierung von Nachrichten
    role: MessageRole
    content: str
    sources: list[str] = field(default_factory=list)  # Referenzierte Chunk-IDs
    created_at: datetime = field(default_factory=datetime.utcnow)
```

**SQLite-Tabelle:**

```sql
CREATE TABLE chat_messages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT DEFAULT '[]',          -- JSON array of chunk IDs
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_session ON chat_messages(session_id, created_at);
```

---

## 3. Persistenzschichten

### 3.1 SQLite (Metadaten + Zustand)

**Datenbankdatei:** `data/openaustria_rag.db`

Gespeichert werden:
- Projects, Sources, Documents (Metadaten, nicht Inhalt)
- CodeElements (extrahierte Strukturen)
- GapReports + GapItems
- ChatHistory

**Migrationen:** Alembic oder eigenes einfaches Migrationssystem mit Versions-Tabelle.

```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

### 3.2 ChromaDB (Vektoren + Chunk-Inhalte)

**Verzeichnis:** `data/chromadb/`

Collections:
- `{project_id}_code` -- Code-Chunks
- `{project_id}_documentation` -- Dokumentations-Chunks
- `{project_id}_specification` -- Spezifikations-Chunks

### 3.3 Dateisystem

**Verzeichnisse:**

```
data/
├── openaustria_rag.db          # SQLite
├── chromadb/                    # ChromaDB persistent storage
├── repos/                       # Geclonte Git-Repositories
│   └── {source_id}/
├── uploads/                     # Hochgeladene ZIP-Dateien
│   └── {source_id}/
└── exports/                     # Exportierte Reports
    └── {report_id}.json
```

---

## 4. Datenfluss

```
User legt Projekt an
    |
    v
Project (SQLite) ──> Status: CREATED
    |
User fuegt Source hinzu
    |
    v
Source (SQLite) ──> Status: CONFIGURED
    |
User startet Sync
    |
    v
Source ──> Status: SYNCING
    |
Connector holt Rohdaten
    |
    v
Documents (SQLite, nur Metadaten + Hash)
    |
Code Parser (tree-sitter)
    |
    v
CodeElements (SQLite)
    |
Chunking + Embedding
    |
    v
Chunks (ChromaDB)
    |
    v
Source ──> Status: SYNCED
Project ──> Status: READY
```

---

## 5. Aenderungserkennung (Inkrementelle Updates)

Bei erneutem Sync einer Source:

1. Neuen `content_hash` (SHA-256) berechnen fuer jedes Dokument
2. Vergleich mit gespeichertem Hash in `documents`-Tabelle
3. Nur geaenderte Dokumente neu verarbeiten:
   - Alte Chunks aus ChromaDB loeschen (`document_id`-Filter)
   - Alte CodeElements aus SQLite loeschen
   - Neue Chunks + CodeElements erzeugen

```python
def needs_update(document_id: str, new_hash: str) -> bool:
    existing = db.query(
        "SELECT content_hash FROM documents WHERE id = ?",
        [document_id]
    )
    if not existing:
        return True
    return existing[0].content_hash != new_hash
```

---

## 6. Validierungsregeln

| Feld | Regel |
|---|---|
| `Project.name` | 1-100 Zeichen, unique, alphanumerisch + Leerzeichen + Bindestrich |
| `Source.config` | Muss gueltige JSON sein, wird gegen Typ-spezifisches Schema validiert |
| `Chunk.content` | Nicht leer, max. 8192 Tokens |
| `Chunk.token_count` | > 0, max. 8192 |
| `CodeElement.name` | Nicht leer |
| `GapItem.severity` | Enum-Wert aus {low, medium, high, critical} |
| `GapItem.similarity_score` | 0.0 - 1.0 (wenn gesetzt) |
