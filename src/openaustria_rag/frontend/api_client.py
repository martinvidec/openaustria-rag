"""HTTP client for the FastAPI backend."""

import requests


class APIClient:
    """Requests-based client for the OpenAustria RAG REST API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle(self, resp: requests.Response) -> dict | list | None:
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    # --- Projects ---

    def list_projects(self) -> list[dict]:
        return self._handle(self._session.get(self._url("/api/projects")))

    def create_project(self, name: str, description: str = "") -> dict:
        return self._handle(self._session.post(
            self._url("/api/projects"),
            json={"name": name, "description": description},
        ))

    def get_project(self, project_id: str) -> dict:
        return self._handle(self._session.get(self._url(f"/api/projects/{project_id}")))

    def update_project(self, project_id: str, **kwargs) -> dict:
        return self._handle(self._session.put(
            self._url(f"/api/projects/{project_id}"), json=kwargs,
        ))

    def delete_project(self, project_id: str) -> None:
        self._handle(self._session.delete(self._url(f"/api/projects/{project_id}")))

    # --- Sources ---

    def list_sources(self, project_id: str) -> list[dict]:
        return self._handle(self._session.get(
            self._url(f"/api/projects/{project_id}/sources"),
        ))

    def create_source(self, project_id: str, source_type: str, name: str, config: dict) -> dict:
        return self._handle(self._session.post(
            self._url(f"/api/projects/{project_id}/sources"),
            json={"source_type": source_type, "name": name, "config": config},
        ))

    def delete_source(self, source_id: str) -> None:
        self._handle(self._session.delete(self._url(f"/api/sources/{source_id}")))

    def start_sync(self, source_id: str) -> dict:
        return self._handle(self._session.post(self._url(f"/api/sources/{source_id}/sync")))

    def get_sync_status(self, source_id: str) -> dict:
        return self._handle(self._session.get(self._url(f"/api/sources/{source_id}/status")))

    def test_connection(self, source_id: str) -> dict:
        return self._handle(self._session.post(self._url(f"/api/sources/{source_id}/test")))

    # --- Query ---

    def query(self, project_id: str, query: str, session_id: str | None = None,
              query_type: str | None = None, top_k: int = 10) -> dict:
        body = {"query": query, "top_k": top_k}
        if session_id:
            body["session_id"] = session_id
        if query_type:
            body["query_type"] = query_type
        return self._handle(self._session.post(
            self._url(f"/api/projects/{project_id}/query"), json=body,
        ))

    def get_chat_history(self, project_id: str, session_id: str) -> list[dict]:
        return self._handle(self._session.get(
            self._url(f"/api/projects/{project_id}/chat/history"),
            params={"session_id": session_id},
        ))

    # --- Gap Analysis ---

    def start_gap_analysis(self, project_id: str) -> dict:
        return self._handle(self._session.post(
            self._url(f"/api/projects/{project_id}/gap-analysis"),
        ))

    def get_latest_gap_report(self, project_id: str) -> dict | None:
        resp = self._session.get(
            self._url(f"/api/projects/{project_id}/gap-analysis/latest"),
        )
        if resp.status_code == 404:
            return None
        return self._handle(resp)

    def update_false_positive(self, item_id: str, is_false_positive: bool) -> dict:
        return self._handle(self._session.put(
            self._url(f"/api/gap-items/{item_id}/false-positive"),
            json={"is_false_positive": is_false_positive},
        ))

    # --- System ---

    def health_check(self) -> dict:
        return self._handle(self._session.get(self._url("/api/health")))

    def get_settings(self) -> dict:
        return self._handle(self._session.get(self._url("/api/settings")))
