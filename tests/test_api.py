"""Tests for the FastAPI REST API (SPEC-06)."""

import uuid
from unittest.mock import MagicMock, patch, ANY

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with services pointing to tmp_path."""
    import openaustria_rag.config as cfg
    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")

    # Patch EmbeddingService and LLMService to not connect to Ollama
    with patch("openaustria_rag.frontend.api.EmbeddingService") as mock_emb_cls, \
         patch("openaustria_rag.frontend.api.LLMService") as mock_llm_cls:
        mock_emb = MagicMock()
        mock_emb.embed_single.return_value = [0.1, 0.2, 0.3]
        mock_emb.embed_batch.side_effect = lambda texts: [[0.1, 0.2, 0.3]] * len(texts)
        mock_emb.health_check.return_value = False
        mock_emb_cls.return_value = mock_emb

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Test answer"
        mock_llm.last_token_count = 5
        mock_llm.health_check.return_value = False
        mock_llm_cls.return_value = mock_llm

        from openaustria_rag.frontend.api import create_app
        app = create_app()
        yield TestClient(app)


class TestHealthEndpoint:
    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "database_ok" in data

    def test_settings(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "ollama" in data
        assert "embedding" in data


class TestProjectsCRUD:
    def test_create_project(self, client):
        resp = client.post("/api/projects", json={"name": "Test", "description": "desc"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test"
        assert data["status"] == "created"
        return data["id"]

    def test_list_projects(self, client):
        client.post("/api/projects", json={"name": f"A-{uuid.uuid4().hex[:8]}"})
        client.post("/api/projects", json={"name": f"B-{uuid.uuid4().hex[:8]}"})
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_get_project(self, client):
        create = client.post("/api/projects", json={"name": "Test"})
        pid = create.json()["id"]
        resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test"

    def test_get_project_not_found(self, client):
        resp = client.get("/api/projects/nonexistent")
        assert resp.status_code == 404

    def test_update_project(self, client):
        create = client.post("/api/projects", json={"name": "Old"})
        pid = create.json()["id"]
        resp = client.put(f"/api/projects/{pid}", json={"name": "New"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    def test_delete_project(self, client):
        create = client.post("/api/projects", json={"name": "ToDelete"})
        pid = create.json()["id"]
        resp = client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 204
        assert client.get(f"/api/projects/{pid}").status_code == 404


class TestSourcesCRUD:
    def _create_project(self, client):
        resp = client.post("/api/projects", json={"name": f"P-{uuid.uuid4().hex[:8]}"})
        return resp.json()["id"]

    def test_add_source(self, client):
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/sources", json={
            "source_type": "git",
            "name": "my-repo",
            "config": {"url": "https://github.com/org/repo.git"},
        })
        assert resp.status_code == 201
        assert resp.json()["source_type"] == "git"

    def test_list_sources(self, client):
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/sources", json={
            "source_type": "git", "name": "repo", "config": {"url": "https://example.com/r.git"},
        })
        resp = client.get(f"/api/projects/{pid}/sources")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_delete_source(self, client):
        pid = self._create_project(client)
        create = client.post(f"/api/projects/{pid}/sources", json={
            "source_type": "git", "name": "repo", "config": {"url": "https://example.com/r.git"},
        })
        sid = create.json()["id"]
        resp = client.delete(f"/api/sources/{sid}")
        assert resp.status_code == 204

    def test_sync_status(self, client):
        pid = self._create_project(client)
        create = client.post(f"/api/projects/{pid}/sources", json={
            "source_type": "git", "name": "repo", "config": {"url": "https://example.com/r.git"},
        })
        sid = create.json()["id"]
        resp = client.get(f"/api/sources/{sid}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "configured"

    def test_sync_start_returns_202(self, client):
        pid = self._create_project(client)
        create = client.post(f"/api/projects/{pid}/sources", json={
            "source_type": "git", "name": "repo", "config": {"url": "https://example.com/r.git"},
        })
        sid = create.json()["id"]
        # Background tasks run synchronously in TestClient and may fail
        # (no real git repo), so we just check the endpoint accepts the request
        with patch("openaustria_rag.frontend.api.run_sync"):
            resp = client.post(f"/api/sources/{sid}/sync")
            assert resp.status_code == 202


class TestQueryEndpoint:
    def test_query_project(self, client):
        pid = client.post("/api/projects", json={"name": "Q"}).json()["id"]
        resp = client.post(f"/api/projects/{pid}/query", json={"query": "test question"})
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "query_type" in data

    def test_query_nonexistent_project(self, client):
        resp = client.post("/api/projects/fake/query", json={"query": "test"})
        assert resp.status_code == 404


class TestGapAnalysisEndpoints:
    def test_start_gap_analysis_returns_202(self, client):
        pid = client.post("/api/projects", json={"name": "G"}).json()["id"]
        resp = client.post(f"/api/projects/{pid}/gap-analysis")
        assert resp.status_code == 202

    def test_latest_gap_report_404(self, client):
        pid = client.post("/api/projects", json={"name": "G2"}).json()["id"]
        resp = client.get(f"/api/projects/{pid}/gap-analysis/latest")
        assert resp.status_code == 404
