"""Tests for the Confluence connector (SPEC-02 Section 5).

Uses unittest.mock to simulate Confluence API responses.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from openaustria_rag.connectors.base import (
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorStatus,
    RawDocument,
)
from openaustria_rag.connectors.confluence_connector import ConfluenceConnector


VALID_CONFIG = {
    "base_url": "https://test.atlassian.net",
    "space_key": "PROJ",
    "email": "user@test.com",
    "api_token": "test-token",
}


def _mock_response(status_code=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from requests.exceptions import HTTPError
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    return resp


def _spaces_response(space_id="space-123"):
    return {"results": [{"id": space_id, "key": "PROJ", "name": "Project"}]}


def _pages_response(pages, next_link=None):
    data = {"results": pages, "_links": {}}
    if next_link:
        data["_links"]["next"] = next_link
    return data


def _make_page(page_id, title, html_body="<p>Content</p>", parent_id=None):
    return {
        "id": page_id,
        "title": title,
        "parentId": parent_id,
        "status": "current",
        "body": {"storage": {"value": html_body}},
        "version": {"number": 1, "createdAt": "2026-01-01T00:00:00Z"},
    }


class TestConfluenceValidation:
    def test_missing_base_url_raises(self):
        config = {**VALID_CONFIG}
        del config["base_url"]
        with pytest.raises(ConnectorConfigError, match="base_url"):
            ConfluenceConnector("s1", config)

    def test_missing_api_token_raises(self):
        config = {**VALID_CONFIG}
        del config["api_token"]
        with pytest.raises(ConnectorConfigError, match="api_token"):
            ConfluenceConnector("s1", config)

    def test_valid_config_accepted(self):
        c = ConfluenceConnector("s1", VALID_CONFIG)
        assert c.status == ConnectorStatus.IDLE


class TestConfluenceConnect:
    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_connect_success(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        session.get.return_value = _mock_response(200, _spaces_response())

        c = ConfluenceConnector("s1", VALID_CONFIG)
        c.connect()
        assert c.status == ConnectorStatus.CONNECTED

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_connect_space_not_found(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        session.get.return_value = _mock_response(200, {"results": []})

        c = ConfluenceConnector("s1", VALID_CONFIG)
        with pytest.raises(ConnectorConfigError, match="not found"):
            c.connect()

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_connect_auth_failure(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        resp = _mock_response(401)
        resp.response = resp
        session.get.return_value = resp

        c = ConfluenceConnector("s1", VALID_CONFIG)
        with pytest.raises(ConnectorAuthError):
            c.connect()


class TestConfluenceFetch:
    def _setup_connector(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        c = ConfluenceConnector("s1", VALID_CONFIG)
        # First call: spaces lookup
        spaces_resp = _mock_response(200, _spaces_response())
        session.get.return_value = spaces_resp
        c.connect()
        return c, session

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_fetch_yields_documents(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)

        pages = [
            _make_page("p1", "Architecture", "<h2>Overview</h2><p>System design</p>"),
            _make_page("p2", "API Guide", "<p>REST endpoints</p>"),
        ]
        pages_resp = _mock_response(200, _pages_response(pages))
        session.get.return_value = pages_resp

        docs = list(c.fetch_documents())
        assert len(docs) == 2
        for doc in docs:
            assert isinstance(doc, RawDocument)
            assert doc.content_type == "documentation"
            assert doc.language == "markdown"

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_html_to_markdown_conversion(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)

        pages = [_make_page("p1", "Test Page", "<h2>Heading</h2><p>Paragraph</p>")]
        session.get.return_value = _mock_response(200, _pages_response(pages))

        docs = list(c.fetch_documents())
        assert "# Test Page" in docs[0].content
        assert "Heading" in docs[0].content
        assert "Paragraph" in docs[0].content

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_metadata_populated(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)

        pages = [_make_page("p1", "Page", parent_id="parent-1")]
        session.get.return_value = _mock_response(200, _pages_response(pages))

        docs = list(c.fetch_documents())
        meta = docs[0].metadata
        assert meta["confluence_page_id"] == "p1"
        assert meta["confluence_title"] == "Page"
        assert meta["confluence_space"] == "PROJ"
        assert meta["confluence_parent_id"] == "parent-1"

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_title_exclusion(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)
        c._conf_config.exclude_title_patterns = ["Meeting Notes*"]

        pages = [
            _make_page("p1", "Architecture"),
            _make_page("p2", "Meeting Notes 2026-01"),
        ]
        session.get.return_value = _mock_response(200, _pages_response(pages))

        docs = list(c.fetch_documents())
        assert len(docs) == 1
        assert docs[0].metadata["confluence_title"] == "Architecture"

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_empty_body_skipped(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)

        pages = [
            _make_page("p1", "Empty", ""),
            _make_page("p2", "Full", "<p>Content</p>"),
        ]
        session.get.return_value = _mock_response(200, _pages_response(pages))

        docs = list(c.fetch_documents())
        assert len(docs) == 1

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_page_limit_respected(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)
        c._conf_config.page_limit = 2

        pages = [
            _make_page("p1", "Page 1"),
            _make_page("p2", "Page 2"),
            _make_page("p3", "Page 3"),
        ]
        session.get.return_value = _mock_response(200, _pages_response(pages))

        docs = list(c.fetch_documents())
        assert len(docs) == 2

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_pagination(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)

        page1 = _pages_response(
            [_make_page("p1", "Page 1")],
            next_link="/wiki/api/v2/spaces/space-123/pages?cursor=abc123",
        )
        page2 = _pages_response([_make_page("p2", "Page 2")])

        session.get.side_effect = [
            _mock_response(200, page1),
            _mock_response(200, page2),
        ]

        docs = list(c.fetch_documents())
        assert len(docs) == 2

    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_progress_tracking(self, mock_session_cls):
        c, session = self._setup_connector(mock_session_cls)

        pages = [_make_page("p1", "Page 1"), _make_page("p2", "Page 2")]
        session.get.return_value = _mock_response(200, _pages_response(pages))

        list(c.fetch_documents())
        assert c.progress.processed == 2


class TestConfluenceRateLimit:
    @patch("openaustria_rag.connectors.confluence_connector.time.sleep")
    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_rate_limit_retry(self, mock_session_cls, mock_sleep):
        session = MagicMock()
        mock_session_cls.return_value = session

        # First: spaces ok. Then: 429, then success
        spaces_resp = _mock_response(200, _spaces_response())
        rate_resp = _mock_response(429, headers={"Retry-After": "5"})
        rate_resp.raise_for_status = MagicMock()  # 429 doesn't raise_for_status
        ok_resp = _mock_response(200, _pages_response([_make_page("p1", "Page")]))

        session.get.side_effect = [spaces_resp, rate_resp, ok_resp]

        c = ConfluenceConnector("s1", VALID_CONFIG)
        c.connect()
        docs = list(c.fetch_documents())
        assert len(docs) == 1
        mock_sleep.assert_called()


class TestConfluenceDisconnect:
    @patch("openaustria_rag.connectors.confluence_connector.requests.Session")
    def test_disconnect(self, mock_session_cls):
        session = MagicMock()
        mock_session_cls.return_value = session
        session.get.return_value = _mock_response(200, _spaces_response())

        c = ConfluenceConnector("s1", VALID_CONFIG)
        c.connect()
        c.disconnect()
        assert c.status == ConnectorStatus.IDLE
        session.close.assert_called_once()
