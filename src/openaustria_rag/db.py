"""SQLite persistence layer as defined in SPEC-01."""

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .config import PROJECT_ROOT, get_settings
from .models import (
    ChatMessage,
    CodeElement,
    ContentType,
    Document,
    ElementKind,
    GapItem,
    GapReport,
    GapSummary,
    GapType,
    MessageRole,
    Project,
    ProjectStatus,
    Severity,
    Source,
    SourceStatus,
    SourceType,
)

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settings TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    config TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'configured',
    last_sync_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    language TEXT,
    metadata TEXT DEFAULT '{}',
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS code_elements (
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
    annotations TEXT DEFAULT '[]',
    implements TEXT DEFAULT '[]',
    extends TEXT,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES code_elements(id)
);

CREATE INDEX IF NOT EXISTS idx_code_elements_document ON code_elements(document_id);
CREATE INDEX IF NOT EXISTS idx_code_elements_kind ON code_elements(kind);
CREATE INDEX IF NOT EXISTS idx_code_elements_name ON code_elements(name);

CREATE TABLE IF NOT EXISTS gap_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gap_items (
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

CREATE INDEX IF NOT EXISTS idx_gap_items_report ON gap_items(report_id);
CREATE INDEX IF NOT EXISTS idx_gap_items_type ON gap_items(gap_type);
CREATE INDEX IF NOT EXISTS idx_gap_items_severity ON gap_items(severity);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id, created_at);
"""


def _dt_to_str(dt: datetime) -> str:
    return dt.isoformat()


def _str_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class MetadataDB:
    """SQLite-backed metadata store for the OpenAustria RAG platform."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            settings = get_settings()
            db_path = PROJECT_ROOT / settings.data_dir / "openaustria_rag.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(_SCHEMA_SQL)
        row = cur.execute(
            "SELECT MAX(version) as v FROM schema_version"
        ).fetchone()
        current = row["v"] if row["v"] is not None else 0
        if current < SCHEMA_VERSION:
            cur.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _dt_to_str(datetime.now(UTC))),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- Projects ---

    def save_project(self, project: Project) -> None:
        self._conn.execute(
            """INSERT INTO projects
               (id, name, description, status, created_at, updated_at, settings)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, description=excluded.description,
                 status=excluded.status, updated_at=excluded.updated_at,
                 settings=excluded.settings""",
            (
                project.id,
                project.name,
                project.description,
                project.status.value,
                _dt_to_str(project.created_at),
                _dt_to_str(project.updated_at),
                json.dumps(project.settings),
            ),
        )
        self._conn.commit()

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def get_all_projects(self) -> list[Project]:
        rows = self._conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [self._row_to_project(r) for r in rows]

    def delete_project(self, project_id: str) -> None:
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()

    def _row_to_project(self, row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            status=ProjectStatus(row["status"]),
            created_at=_str_to_dt(row["created_at"]),
            updated_at=_str_to_dt(row["updated_at"]),
            settings=json.loads(row["settings"]),
        )

    # --- Sources ---

    def save_source(self, source: Source) -> None:
        self._conn.execute(
            """INSERT INTO sources
               (id, project_id, source_type, name, config, status, last_sync_at, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, config=excluded.config, status=excluded.status,
                 last_sync_at=excluded.last_sync_at, error_message=excluded.error_message""",
            (
                source.id,
                source.project_id,
                source.source_type.value,
                source.name,
                json.dumps(source.config),
                source.status.value,
                _dt_to_str(source.last_sync_at) if source.last_sync_at else None,
                source.error_message,
                _dt_to_str(source.created_at),
            ),
        )
        self._conn.commit()

    def get_source(self, source_id: str) -> Source | None:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_source(row)

    def get_sources_by_project(self, project_id: str) -> list[Source]:
        rows = self._conn.execute(
            "SELECT * FROM sources WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [self._row_to_source(r) for r in rows]

    def delete_source(self, source_id: str) -> None:
        self._conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        self._conn.commit()

    def _row_to_source(self, row: sqlite3.Row) -> Source:
        return Source(
            id=row["id"],
            project_id=row["project_id"],
            source_type=SourceType(row["source_type"]),
            name=row["name"],
            config=json.loads(row["config"]),
            status=SourceStatus(row["status"]),
            last_sync_at=_str_to_dt(row["last_sync_at"]) if row["last_sync_at"] else None,
            error_message=row["error_message"],
            created_at=_str_to_dt(row["created_at"]),
        )

    # --- Documents ---

    def save_document(self, doc: Document) -> None:
        self._conn.execute(
            """INSERT INTO documents
               (id, source_id, content_type, file_path, language, metadata, content_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 content_type=excluded.content_type, file_path=excluded.file_path,
                 language=excluded.language, metadata=excluded.metadata,
                 content_hash=excluded.content_hash""",
            (
                doc.id,
                doc.source_id,
                doc.content_type.value,
                doc.file_path,
                doc.language,
                json.dumps(doc.metadata),
                doc.content_hash,
                _dt_to_str(doc.created_at),
            ),
        )
        self._conn.commit()

    def get_document(self, document_id: str) -> Document | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def document_unchanged(self, document_id: str, content_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT content_hash FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            return False
        return row["content_hash"] == content_hash

    def delete_documents_by_source(self, source_id: str) -> None:
        self._conn.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
        self._conn.commit()

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            source_id=row["source_id"],
            content_type=ContentType(row["content_type"]),
            file_path=row["file_path"],
            language=row["language"],
            metadata=json.loads(row["metadata"]),
            content_hash=row["content_hash"],
            created_at=_str_to_dt(row["created_at"]),
        )

    # --- CodeElements ---

    def save_code_elements(self, elements: list[CodeElement]) -> None:
        self._conn.executemany(
            """INSERT INTO code_elements
               (id, document_id, kind, name, short_name, signature, visibility,
                parent_id, file_path, start_line, end_line, docstring,
                annotations, implements, extends)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind, name=excluded.name, short_name=excluded.short_name,
                 signature=excluded.signature, visibility=excluded.visibility,
                 parent_id=excluded.parent_id, file_path=excluded.file_path,
                 start_line=excluded.start_line, end_line=excluded.end_line,
                 docstring=excluded.docstring, annotations=excluded.annotations,
                 implements=excluded.implements, extends=excluded.extends""",
            [
                (
                    e.id,
                    e.document_id,
                    e.kind.value,
                    e.name,
                    e.short_name,
                    e.signature,
                    e.visibility,
                    e.parent_id,
                    e.file_path,
                    e.start_line,
                    e.end_line,
                    e.docstring,
                    json.dumps(e.annotations),
                    json.dumps(e.implements),
                    e.extends,
                )
                for e in elements
            ],
        )
        self._conn.commit()

    def get_code_elements_by_project(self, project_id: str) -> list[CodeElement]:
        rows = self._conn.execute(
            """SELECT ce.* FROM code_elements ce
               JOIN documents d ON ce.document_id = d.id
               JOIN sources s ON d.source_id = s.id
               WHERE s.project_id = ?
               ORDER BY ce.file_path, ce.start_line""",
            (project_id,),
        ).fetchall()
        return [self._row_to_code_element(r) for r in rows]

    def delete_code_elements(self, document_id: str) -> None:
        self._conn.execute(
            "DELETE FROM code_elements WHERE document_id = ?", (document_id,)
        )
        self._conn.commit()

    def _row_to_code_element(self, row: sqlite3.Row) -> CodeElement:
        return CodeElement(
            id=row["id"],
            document_id=row["document_id"],
            kind=ElementKind(row["kind"]),
            name=row["name"],
            short_name=row["short_name"],
            signature=row["signature"],
            visibility=row["visibility"],
            parent_id=row["parent_id"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            docstring=row["docstring"],
            annotations=json.loads(row["annotations"]),
            implements=json.loads(row["implements"]),
            extends=row["extends"],
        )

    # --- GapReports ---

    def save_gap_report(self, report: GapReport) -> None:
        self._conn.execute(
            """INSERT INTO gap_reports (id, project_id, created_at, summary)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET summary=excluded.summary""",
            (
                report.id,
                report.project_id,
                _dt_to_str(report.created_at),
                json.dumps(asdict(report.summary)),
            ),
        )
        self._conn.commit()

    def save_gap_items(self, items: list[GapItem]) -> None:
        self._conn.executemany(
            """INSERT INTO gap_items
               (id, report_id, gap_type, severity, code_element_id, code_element_name,
                file_path, line, doc_reference, doc_chunk_id, similarity_score,
                divergence_description, recommendation, llm_analysis, is_false_positive)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    item.id,
                    item.report_id,
                    item.gap_type.value,
                    item.severity.value,
                    item.code_element_id,
                    item.code_element_name,
                    item.file_path,
                    item.line,
                    item.doc_reference,
                    item.doc_chunk_id,
                    item.similarity_score,
                    item.divergence_description,
                    item.recommendation,
                    item.llm_analysis,
                    1 if item.is_false_positive else 0,
                )
                for item in items
            ],
        )
        self._conn.commit()

    def get_latest_gap_report(self, project_id: str) -> GapReport | None:
        row = self._conn.execute(
            """SELECT * FROM gap_reports
               WHERE project_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        report = self._row_to_gap_report(row)
        items = self._conn.execute(
            "SELECT * FROM gap_items WHERE report_id = ?", (report.id,)
        ).fetchall()
        report.gaps = [self._row_to_gap_item(r) for r in items]
        return report

    def get_false_positives(self, project_id: str) -> list[GapItem]:
        rows = self._conn.execute(
            """SELECT gi.* FROM gap_items gi
               JOIN gap_reports gr ON gi.report_id = gr.id
               WHERE gr.project_id = ? AND gi.is_false_positive = 1""",
            (project_id,),
        ).fetchall()
        return [self._row_to_gap_item(r) for r in rows]

    def update_gap_item(self, item_id: str, is_false_positive: bool) -> None:
        self._conn.execute(
            "UPDATE gap_items SET is_false_positive = ? WHERE id = ?",
            (1 if is_false_positive else 0, item_id),
        )
        self._conn.commit()

    def _row_to_gap_report(self, row: sqlite3.Row) -> GapReport:
        summary_data = json.loads(row["summary"])
        return GapReport(
            id=row["id"],
            project_id=row["project_id"],
            created_at=_str_to_dt(row["created_at"]),
            summary=GapSummary(**summary_data),
        )

    def _row_to_gap_item(self, row: sqlite3.Row) -> GapItem:
        return GapItem(
            id=row["id"],
            report_id=row["report_id"],
            gap_type=GapType(row["gap_type"]),
            severity=Severity(row["severity"]),
            code_element_id=row["code_element_id"],
            code_element_name=row["code_element_name"],
            file_path=row["file_path"],
            line=row["line"],
            doc_reference=row["doc_reference"],
            doc_chunk_id=row["doc_chunk_id"],
            similarity_score=row["similarity_score"],
            divergence_description=row["divergence_description"],
            recommendation=row["recommendation"],
            llm_analysis=row["llm_analysis"],
            is_false_positive=bool(row["is_false_positive"]),
        )

    # --- ChatMessages ---

    def save_chat_message(self, msg: ChatMessage) -> None:
        self._conn.execute(
            """INSERT INTO chat_messages
               (id, project_id, session_id, role, content, sources, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id,
                msg.project_id,
                msg.session_id,
                msg.role.value,
                msg.content,
                json.dumps(msg.sources),
                _dt_to_str(msg.created_at),
            ),
        )
        self._conn.commit()

    def get_chat_history(self, session_id: str) -> list[ChatMessage]:
        rows = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._row_to_chat_message(r) for r in rows]

    def _row_to_chat_message(self, row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            id=row["id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            role=MessageRole(row["role"]),
            content=row["content"],
            sources=json.loads(row["sources"]),
            created_at=_str_to_dt(row["created_at"]),
        )
