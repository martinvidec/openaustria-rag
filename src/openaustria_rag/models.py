"""Core data models as defined in SPEC-01."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- Project ---

class ProjectStatus(Enum):
    CREATED = "created"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


@dataclass
class Project:
    id: str
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.CREATED
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    settings: dict = field(default_factory=dict)


# --- Source ---

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
    id: str
    project_id: str
    source_type: SourceType
    name: str
    config: dict = field(default_factory=dict)
    status: SourceStatus = SourceStatus.CONFIGURED
    last_sync_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=_utcnow)


# --- Document ---

class ContentType(Enum):
    CODE = "code"
    DOCUMENTATION = "documentation"
    SPECIFICATION = "specification"
    MODEL = "model"
    CONFIG = "config"


@dataclass
class Document:
    id: str
    source_id: str
    content_type: ContentType
    file_path: str
    content_hash: str
    language: str | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)


# --- Chunk (stored in ChromaDB, not SQLite) ---

@dataclass
class ChunkMetadata:
    source_type: str = ""
    connector: str = ""
    language: str = ""
    file_path: str = ""
    element_type: str = ""
    element_name: str = ""
    project_id: str = ""
    source_id: str = ""
    document_id: str = ""
    start_line: int | None = None
    end_line: int | None = None
    parent_element: str | None = None
    ingested_at: str = ""


@dataclass
class Chunk:
    id: str
    document_id: str
    content: str
    embedding: list[float] | None = None
    chunk_index: int = 0
    token_count: int = 0
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)


# --- CodeElement ---

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
    id: str
    document_id: str
    kind: ElementKind
    name: str
    short_name: str
    signature: str | None = None
    visibility: str | None = None
    parent_id: str | None = None
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    docstring: str | None = None
    annotations: list[str] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    extends: str | None = None


# --- Gap Analysis ---

class GapType(Enum):
    UNDOCUMENTED = "undocumented"
    UNIMPLEMENTED = "unimplemented"
    DIVERGENT = "divergent"
    CONSISTENT = "consistent"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class GapSummary:
    total_code_elements: int = 0
    documented: int = 0
    undocumented: int = 0
    unimplemented: int = 0
    divergent: int = 0
    documentation_coverage: float = 0.0


@dataclass
class GapItem:
    id: str
    report_id: str
    gap_type: GapType
    severity: Severity
    code_element_id: str | None = None
    code_element_name: str = ""
    file_path: str = ""
    line: int | None = None
    doc_reference: str | None = None
    doc_chunk_id: str | None = None
    similarity_score: float | None = None
    divergence_description: str = ""
    recommendation: str = ""
    llm_analysis: str | None = None
    is_false_positive: bool = False


@dataclass
class GapReport:
    id: str
    project_id: str
    created_at: datetime = field(default_factory=_utcnow)
    summary: GapSummary = field(default_factory=GapSummary)
    gaps: list[GapItem] = field(default_factory=list)


# --- Chat ---

class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ChatMessage:
    id: str
    project_id: str
    session_id: str
    role: MessageRole
    content: str
    sources: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
