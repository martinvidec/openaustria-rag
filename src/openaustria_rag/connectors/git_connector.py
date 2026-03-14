"""Git repository connector as defined in SPEC-02 Section 3."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

from git import GitCommandError, Repo

from .base import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorStatus,
    RawDocument,
)
from .utils import FileFilter, classify_content_type, detect_language

logger = logging.getLogger(__name__)


@dataclass
class GitConfig:
    url: str
    branch: str | None = None
    include_patterns: list[str] = field(
        default_factory=lambda: [
            "*.java", "*.py", "*.ts", "*.tsx", "*.js", "*.jsx",
            "*.go", "*.rs", "*.cs", "*.kt",
            "*.md", "*.rst", "*.txt",
            "*.yaml", "*.yml", "*.json", "*.toml",
            "*.xml", "*.html",
        ]
    )
    exclude_patterns: list[str] = field(
        default_factory=lambda: [
            "**/node_modules/**", "**/.git/**", "**/build/**",
            "**/dist/**", "**/target/**", "**/__pycache__/**",
            "**/venv/**", "**/.venv/**", "**/vendor/**",
            "**/*.min.js", "**/*.min.css",
            "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml",
        ]
    )
    max_file_size_kb: int = 500
    auth_token: str | None = None
    ssh_key_path: str | None = None
    depth: int | None = 1


class GitConnector(BaseConnector):

    def __init__(self, source_id: str, config: dict):
        self._git_config: GitConfig | None = None
        self._repo: Repo | None = None
        self._repo_path: str = ""
        super().__init__(source_id, config)

    def _validate_config(self) -> None:
        if "url" not in self.config:
            raise ConnectorConfigError("Git URL is required", self.source_id)
        url = self.config["url"]
        if not (
            url.startswith("https://")
            or url.startswith("git@")
            or url.startswith("file://")
            or os.path.isdir(url)
        ):
            raise ConnectorConfigError(
                f"Invalid Git URL: {url}. Must start with https://, git@, file://, or be a local path",
                self.source_id,
            )
        self._git_config = GitConfig(
            **{k: v for k, v in self.config.items() if k in GitConfig.__dataclass_fields__}
        )

    def connect(self) -> None:
        self.status = ConnectorStatus.CONNECTING
        self._repo_path = os.path.join("data", "repos", self.source_id)
        os.makedirs(self._repo_path, exist_ok=True)

        clone_kwargs: dict = {}
        if self._git_config.depth is not None:
            clone_kwargs["depth"] = self._git_config.depth
        if self._git_config.branch:
            clone_kwargs["branch"] = self._git_config.branch

        try:
            if os.path.exists(os.path.join(self._repo_path, ".git")):
                self._repo = Repo(self._repo_path)
                self._repo.remotes.origin.pull()
            else:
                clone_url = self._git_config.url
                if self._git_config.auth_token and clone_url.startswith("https://"):
                    parts = clone_url.split("://", 1)
                    clone_url = f"{parts[0]}://oauth2:{self._git_config.auth_token}@{parts[1]}"
                self._repo = Repo.clone_from(
                    url=clone_url, to_path=self._repo_path, **clone_kwargs
                )
            self.status = ConnectorStatus.CONNECTED
        except GitCommandError as e:
            self.status = ConnectorStatus.ERROR
            if "Authentication" in str(e) or "403" in str(e):
                raise ConnectorAuthError(str(e), self.source_id)
            raise ConnectorNetworkError(str(e), source_id=self.source_id)

    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        if not self._repo:
            raise ConnectorError("Not connected", self.source_id)

        self.status = ConnectorStatus.FETCHING
        file_filter = FileFilter(
            self._git_config.include_patterns,
            self._git_config.exclude_patterns,
            self._git_config.max_file_size_kb,
        )

        all_files = self._collect_files(file_filter)
        self.progress.total = len(all_files)

        for file_path in all_files:
            abs_path = os.path.join(self._repo_path, file_path)

            # Skip symlinks for security
            if os.path.islink(abs_path):
                self.progress.skipped += 1
                continue

            try:
                size = os.path.getsize(abs_path)
                if size > self._git_config.max_file_size_kb * 1024:
                    self.progress.skipped += 1
                    continue

                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                language = detect_language(file_path)
                content_type = classify_content_type(language)
                git_meta = self._get_git_metadata(file_path)

                yield RawDocument(
                    content=content,
                    file_path=file_path,
                    content_type=content_type,
                    language=language,
                    size_bytes=size,
                    last_modified=git_meta.get("last_modified"),
                    metadata={
                        "git_commit": git_meta.get("commit"),
                        "git_author": git_meta.get("author"),
                        "git_repo_url": self._git_config.url,
                        "git_branch": self._git_config.branch,
                    },
                )
                self.progress.processed += 1
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                self.progress.errors += 1

        self.status = ConnectorStatus.CONNECTED

    def _collect_files(self, file_filter: FileFilter) -> list[str]:
        files = []
        for root, dirs, filenames in os.walk(self._repo_path):
            rel_root = os.path.relpath(root, self._repo_path)
            if rel_root == ".":
                rel_root = ""
            # Filter directories early
            dirs[:] = [
                d for d in dirs
                if d != ".git"
                and not file_filter.should_exclude_dir(
                    os.path.join(rel_root, d) if rel_root else d
                )
            ]
            for fname in filenames:
                rel_path = os.path.join(rel_root, fname) if rel_root else fname
                if file_filter.should_include(rel_path):
                    files.append(rel_path)
        return sorted(files)

    def _get_git_metadata(self, file_path: str) -> dict:
        try:
            commits = list(self._repo.iter_commits(paths=file_path, max_count=1))
            if commits:
                return {
                    "commit": commits[0].hexsha[:8],
                    "author": str(commits[0].author),
                    "last_modified": commits[0].committed_datetime,
                }
        except Exception:
            pass
        return {}

    def get_source_info(self) -> dict:
        file_filter = FileFilter(
            self._git_config.include_patterns,
            self._git_config.exclude_patterns,
            self._git_config.max_file_size_kb,
        )
        files = self._collect_files(file_filter) if self._repo else []
        return {
            "url": self._git_config.url,
            "branch": self._git_config.branch or "default",
            "file_count": len(files),
            "repo_path": self._repo_path,
        }

    def disconnect(self) -> None:
        self._repo = None
        super().disconnect()
