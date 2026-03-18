"""Pydantic request/response schemas for the REST API (SPEC-06)."""

from pydantic import BaseModel, Field


# --- Projects ---

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    settings: dict = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str
    settings: dict


# --- Sources ---

class SourceCreate(BaseModel):
    source_type: str
    name: str
    config: dict


class SourceResponse(BaseModel):
    id: str
    project_id: str
    source_type: str
    name: str
    config: dict
    status: str
    last_sync_at: str | None
    error_message: str | None
    created_at: str


class SyncStatus(BaseModel):
    source_id: str
    status: str
    error_message: str | None = None
    last_sync_at: str | None = None


# --- Chat / Query ---

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    query_type: str | None = None
    top_k: int = 15
    session_id: str | None = None
    filters: dict | None = None


class QueryResponse(BaseModel):
    answer: str
    query_type: str
    sources: list[dict] = Field(default_factory=list)
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    token_count: int = 0


# --- Gap Analysis ---

class GapReportResponse(BaseModel):
    id: str
    project_id: str
    created_at: str
    summary: dict
    gaps: list[dict]


class FalsePositiveUpdate(BaseModel):
    is_false_positive: bool


# --- System ---

class HealthResponse(BaseModel):
    status: str
    ollama_available: bool = False
    embedding_model_available: bool = False
    database_ok: bool = True


class SettingsUpdate(BaseModel):
    ollama: dict | None = None
    chunking: dict | None = None
    gap_analysis: dict | None = None


class SettingsResponse(BaseModel):
    ollama: dict
    embedding: dict
    chunking: dict
    vector_store: dict
    gap_analysis: dict
