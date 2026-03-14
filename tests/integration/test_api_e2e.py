"""Integration: API End-to-End workflow (SPEC-06)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import openaustria_rag.config as cfg
    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")

    with patch("openaustria_rag.frontend.api.EmbeddingService") as mock_emb_cls, \
         patch("openaustria_rag.frontend.api.LLMService") as mock_llm_cls:
        mock_emb = MagicMock()
        mock_emb.embed_single.side_effect = lambda t: [hash(t) % 100 / 100.0, 0.5, 0.5]
        mock_emb.embed_batch.side_effect = lambda ts: [mock_emb.embed_single(t) for t in ts]
        mock_emb.health_check.return_value = True
        mock_emb_cls.return_value = mock_emb

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Test-Antwort vom LLM."
        mock_llm.last_token_count = 10
        mock_llm.health_check.return_value = True
        mock_llm_cls.return_value = mock_llm

        from openaustria_rag.frontend.api import create_app
        app = create_app()
        yield TestClient(app)


@pytest.mark.integration
class TestAPIEndToEnd:
    def test_full_workflow(self, client):
        """Project → Source → Query → Gap Analysis workflow."""
        # 1. Health check
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # 2. Create project
        resp = client.post("/api/projects", json={
            "name": "E2E Test", "description": "End-to-end test project",
        })
        assert resp.status_code == 201
        project_id = resp.json()["id"]

        # 3. Get project
        resp = client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "E2E Test"

        # 4. Add source
        resp = client.post(f"/api/projects/{project_id}/sources", json={
            "source_type": "git",
            "name": "test-repo",
            "config": {"url": "https://github.com/example/repo.git"},
        })
        assert resp.status_code == 201
        source_id = resp.json()["id"]

        # 5. Check source status
        resp = client.get(f"/api/sources/{source_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "configured"

        # 6. Query (empty project — still works)
        resp = client.post(f"/api/projects/{project_id}/query", json={
            "query": "What is UserService?",
        })
        assert resp.status_code == 200
        assert "answer" in resp.json()

        # 7. Start gap analysis (background)
        with patch("openaustria_rag.frontend.api.GapAnalyzer") as mock_analyzer_cls:
            mock_analyzer = MagicMock()
            mock_analyzer_cls.return_value = mock_analyzer
            resp = client.post(f"/api/projects/{project_id}/gap-analysis")
            assert resp.status_code == 202

        # 8. Delete source
        resp = client.delete(f"/api/sources/{source_id}")
        assert resp.status_code == 204

        # 9. Delete project
        resp = client.delete(f"/api/projects/{project_id}")
        assert resp.status_code == 204

        # 10. Verify deleted
        resp = client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 404

    def test_settings_endpoint(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "ollama" in data
        assert "embedding" in data
        assert "chunking" in data
