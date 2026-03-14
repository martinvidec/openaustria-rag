"""Confluence API connector as defined in SPEC-02 Section 5."""

import logging
import time
from dataclasses import dataclass, field
from typing import Generator
from urllib.parse import parse_qs, urlparse

import html2text
import requests
from requests.auth import HTTPBasicAuth

from .base import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorStatus,
    RawDocument,
)

logger = logging.getLogger(__name__)

RETRY_CONFIG = {
    "max_retries": 3,
    "backoff_factor": 2,
    "retry_on_status": [429, 500, 502, 503, 504],
}


@dataclass
class ConfluenceConfig:
    base_url: str
    space_key: str
    email: str
    api_token: str
    page_limit: int = 500
    include_labels: list[str] = field(default_factory=list)
    exclude_title_patterns: list[str] = field(default_factory=list)
    include_attachments: bool = False
    sync_archived: bool = False


class ConfluenceConnector(BaseConnector):

    PAGE_SIZE = 25

    def __init__(self, source_id: str, config: dict):
        self._conf_config: ConfluenceConfig | None = None
        self._session: requests.Session | None = None
        self._space_id: str | None = None
        super().__init__(source_id, config)

    def _validate_config(self) -> None:
        required = ["base_url", "space_key", "email", "api_token"]
        for f in required:
            if f not in self.config:
                raise ConnectorConfigError(
                    f"'{f}' is required for Confluence connector",
                    self.source_id,
                )
        self._conf_config = ConfluenceConfig(
            **{k: v for k, v in self.config.items() if k in ConfluenceConfig.__dataclass_fields__}
        )

    def connect(self) -> None:
        self.status = ConnectorStatus.CONNECTING
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(
            self._conf_config.email, self._conf_config.api_token
        )
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        try:
            resp = self._api_get(
                "/wiki/api/v2/spaces",
                params={"keys": self._conf_config.space_key, "limit": 1},
            )
            spaces = resp.get("results", [])
            if not spaces:
                raise ConnectorConfigError(
                    f"Space '{self._conf_config.space_key}' not found",
                    self.source_id,
                )
            self._space_id = spaces[0]["id"]
            self.status = ConnectorStatus.CONNECTED
        except requests.exceptions.ConnectionError as e:
            self.status = ConnectorStatus.ERROR
            raise ConnectorNetworkError(str(e), source_id=self.source_id)
        except requests.exceptions.HTTPError as e:
            self.status = ConnectorStatus.ERROR
            if e.response is not None and e.response.status_code in (401, 403):
                raise ConnectorAuthError(
                    "Authentication failed. Check email and API token.",
                    self.source_id,
                )
            raise ConnectorError(str(e), self.source_id)

    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        if not self._session or not self._space_id:
            raise ConnectorError("Not connected", self.source_id)

        self.status = ConnectorStatus.FETCHING
        h2t = html2text.HTML2Text()
        h2t.ignore_links = False
        h2t.ignore_images = True
        h2t.body_width = 0

        cursor = None
        page_count = 0

        while True:
            params = {
                "limit": self.PAGE_SIZE,
                "body-format": "storage",
                "status": "current",
            }
            if cursor:
                params["cursor"] = cursor

            resp = self._api_get(
                f"/wiki/api/v2/spaces/{self._space_id}/pages",
                params=params,
            )

            pages = resp.get("results", [])
            if not pages:
                break

            for page in pages:
                page_count += 1
                if page_count > self._conf_config.page_limit:
                    self.status = ConnectorStatus.CONNECTED
                    return

                title = page.get("title", "")

                if self._should_exclude_title(title):
                    self.progress.skipped += 1
                    continue

                if self._conf_config.include_labels:
                    page_labels = self._get_page_labels(page["id"])
                    if not any(l in self._conf_config.include_labels for l in page_labels):
                        self.progress.skipped += 1
                        continue

                html_body = page.get("body", {}).get("storage", {}).get("value", "")
                if not html_body:
                    self.progress.skipped += 1
                    continue

                markdown_content = h2t.handle(html_body)
                full_content = f"# {title}\n\n{markdown_content}"

                page_url = (
                    f"{self._conf_config.base_url}/wiki"
                    f"/spaces/{self._conf_config.space_key}"
                    f"/pages/{page['id']}"
                )

                yield RawDocument(
                    content=full_content,
                    file_path=page_url,
                    content_type="documentation",
                    language="markdown",
                    size_bytes=len(full_content.encode("utf-8")),
                    metadata={
                        "confluence_page_id": page["id"],
                        "confluence_title": title,
                        "confluence_space": self._conf_config.space_key,
                        "confluence_version": page.get("version", {}).get("number", 1),
                        "confluence_parent_id": page.get("parentId"),
                        "confluence_status": page.get("status"),
                        "last_modified": page.get("version", {}).get("createdAt"),
                    },
                )
                self.progress.processed += 1

            next_link = resp.get("_links", {}).get("next")
            if not next_link:
                break
            parsed = urlparse(next_link)
            query_params = parse_qs(parsed.query)
            cursor = query_params.get("cursor", [None])[0]
            if not cursor:
                break

        self.status = ConnectorStatus.CONNECTED

    def _api_get(self, path: str, params: dict | None = None) -> dict:
        """Execute a GET request with retry and rate-limit handling."""
        url = f"{self._conf_config.base_url}{path}"
        for attempt in range(RETRY_CONFIG["max_retries"] + 1):
            try:
                resp = self._session.get(url, params=params, timeout=30)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    if attempt < RETRY_CONFIG["max_retries"]:
                        logger.warning(f"Rate limited, retrying in {retry_after}s")
                        time.sleep(retry_after)
                        continue
                    raise ConnectorRateLimitError(
                        "Rate limit exceeded",
                        retry_after=retry_after,
                        source_id=self.source_id,
                    )

                if resp.status_code in RETRY_CONFIG["retry_on_status"] and resp.status_code != 429:
                    if attempt < RETRY_CONFIG["max_retries"]:
                        wait = RETRY_CONFIG["backoff_factor"] ** (attempt + 1)
                        logger.warning(f"Server error {resp.status_code}, retrying in {wait}s")
                        time.sleep(wait)
                        continue

                resp.raise_for_status()
                return resp.json()

            except requests.exceptions.Timeout:
                if attempt < RETRY_CONFIG["max_retries"]:
                    wait = RETRY_CONFIG["backoff_factor"] ** (attempt + 1)
                    logger.warning(f"Request timeout, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                raise ConnectorNetworkError("Request timed out", source_id=self.source_id)

        raise ConnectorError("Max retries exceeded", self.source_id)

    def _get_page_labels(self, page_id: str) -> list[str]:
        try:
            resp = self._api_get(f"/wiki/api/v2/pages/{page_id}/labels")
            return [label["name"] for label in resp.get("results", [])]
        except Exception:
            return []

    def _should_exclude_title(self, title: str) -> bool:
        for pattern in self._conf_config.exclude_title_patterns:
            if pattern.endswith("*"):
                if title.startswith(pattern[:-1]):
                    return True
            elif title == pattern:
                return True
        return False

    def get_source_info(self) -> dict:
        return {
            "space_key": self._conf_config.space_key,
            "space_id": self._space_id,
            "connected": self._session is not None and self._space_id is not None,
            "base_url": self._conf_config.base_url,
        }

    def disconnect(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        self._space_id = None
        super().disconnect()
