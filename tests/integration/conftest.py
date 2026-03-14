"""Shared fixtures for integration tests."""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from git import Repo

from openaustria_rag.db import MetadataDB
from openaustria_rag.ingestion.chunking import ChunkingService
from openaustria_rag.ingestion.code_parser import CodeParser
from openaustria_rag.ingestion.pipeline import IngestionPipeline
from openaustria_rag.models import Project, Source, SourceType
from openaustria_rag.retrieval.vector_store import VectorStoreService

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def db(tmp_path):
    d = MetadataDB(db_path=tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture
def vector_store(tmp_path):
    return VectorStoreService(persist_path=tmp_path / "chromadb")


@pytest.fixture
def mock_embedding():
    """Deterministic mock embedding service."""
    svc = MagicMock()

    def embed_single(text):
        # Simple deterministic hash-based vector
        h = hash(text) % 1000
        return [h / 1000.0, (h * 7 % 1000) / 1000.0, (h * 13 % 1000) / 1000.0]

    def embed_batch(texts):
        return [embed_single(t) for t in texts]

    svc.embed_single.side_effect = embed_single
    svc.embed_batch.side_effect = embed_batch
    svc.health_check.return_value = False
    return svc


@pytest.fixture
def mock_llm():
    """Mock LLM service with static responses."""
    svc = MagicMock()
    svc.generate.return_value = "Dies ist eine Test-Antwort basierend auf dem Kontext."
    svc.last_token_count = 15
    svc.health_check.return_value = False
    return svc


@pytest.fixture
def pipeline(db, vector_store, mock_embedding):
    return IngestionPipeline(
        db=db,
        code_parser=CodeParser(),
        chunking_service=ChunkingService(),
        embedding_service=mock_embedding,
        vector_store=vector_store,
    )


@pytest.fixture
def project(db):
    p = Project(id="int-proj", name="Integration Test Project")
    db.save_project(p)
    return p


@pytest.fixture
def source(db, project):
    import uuid as _uuid
    s = Source(
        id=f"int-src-{_uuid.uuid4().hex[:8]}",
        project_id=project.id,
        source_type=SourceType.GIT,
        name="test-repo",
    )
    db.save_source(s)
    return s


@pytest.fixture
def local_git_repo(tmp_path):
    """Create a local git repo with sample files from fixtures."""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()
    repo = Repo.init(repo_path)

    # Copy fixture files
    for src_file in ["sample_python/service.py", "sample_docs/users.md"]:
        src = FIXTURES_DIR / src_file
        dest_dir = repo_path / Path(src_file).parent
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(src_file).name
        dest.write_text(src.read_text())

    # Add config
    (repo_path / "config.yaml").write_text("database:\n  host: localhost\n  port: 5432\n")

    # Commit (exclude .git directory)
    repo.index.add([
        str(f) for f in repo_path.rglob("*")
        if f.is_file() and ".git" not in f.parts
    ])
    repo.index.commit("Initial commit")

    return repo_path
