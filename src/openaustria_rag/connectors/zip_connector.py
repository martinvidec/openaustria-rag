"""ZIP upload connector as defined in SPEC-02 Section 4."""

import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from typing import Generator

from .base import (
    BaseConnector,
    ConnectorConfigError,
    ConnectorError,
    ConnectorStatus,
    RawDocument,
)
from .utils import FileFilter, classify_content_type, detect_language

logger = logging.getLogger(__name__)


@dataclass
class ZipConfig:
    upload_path: str
    filename: str = ""
    include_patterns: list[str] = field(
        default_factory=lambda: [
            "*.java", "*.py", "*.ts", "*.tsx", "*.js",
            "*.md", "*.rst", "*.txt",
            "*.yaml", "*.yml", "*.json",
        ]
    )
    exclude_patterns: list[str] = field(
        default_factory=lambda: [
            "**/node_modules/**", "**/build/**", "**/dist/**",
            "**/__pycache__/**", "**/target/**",
        ]
    )
    max_file_size_kb: int = 500
    max_total_size_mb: int = 200


class ZipConnector(BaseConnector):

    def __init__(self, source_id: str, config: dict):
        self._zip_config: ZipConfig | None = None
        self._extract_path: str = ""
        super().__init__(source_id, config)

    def _validate_config(self) -> None:
        if "upload_path" not in self.config:
            raise ConnectorConfigError("upload_path is required", self.source_id)
        path = self.config["upload_path"]
        if not os.path.exists(path):
            raise ConnectorConfigError(f"File not found: {path}", self.source_id)
        if not zipfile.is_zipfile(path):
            raise ConnectorConfigError(f"Not a valid ZIP file: {path}", self.source_id)

        size_mb = os.path.getsize(path) / (1024 * 1024)
        max_size = self.config.get("max_total_size_mb", 200)
        if size_mb > max_size:
            raise ConnectorConfigError(
                f"ZIP file too large: {size_mb:.1f} MB (max: {max_size} MB)",
                self.source_id,
            )
        self._zip_config = ZipConfig(
            **{k: v for k, v in self.config.items() if k in ZipConfig.__dataclass_fields__}
        )

    def connect(self) -> None:
        self.status = ConnectorStatus.CONNECTING
        self._extract_path = os.path.join("data", "uploads", self.source_id)
        os.makedirs(self._extract_path, exist_ok=True)

        try:
            with zipfile.ZipFile(self._zip_config.upload_path, "r") as zf:
                # Security: check for path traversal (Zip Slip)
                extract_real = os.path.realpath(self._extract_path)
                for member in zf.namelist():
                    member_path = os.path.realpath(
                        os.path.join(self._extract_path, member)
                    )
                    if not member_path.startswith(extract_real + os.sep) and member_path != extract_real:
                        raise ConnectorError(
                            f"Path traversal detected: {member}",
                            self.source_id,
                        )
                zf.extractall(self._extract_path)
            self.status = ConnectorStatus.CONNECTED
        except zipfile.BadZipFile as e:
            self.status = ConnectorStatus.ERROR
            raise ConnectorError(f"Corrupt ZIP file: {e}", self.source_id)

    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        if not self._extract_path:
            raise ConnectorError("Not connected", self.source_id)

        self.status = ConnectorStatus.FETCHING
        file_filter = FileFilter(
            self._zip_config.include_patterns,
            self._zip_config.exclude_patterns,
            self._zip_config.max_file_size_kb,
        )

        all_files = self._collect_files(file_filter)
        self.progress.total = len(all_files)

        for file_path in all_files:
            abs_path = os.path.join(self._extract_path, file_path)

            if os.path.islink(abs_path):
                self.progress.skipped += 1
                continue

            try:
                size = os.path.getsize(abs_path)
                if size > self._zip_config.max_file_size_kb * 1024:
                    self.progress.skipped += 1
                    continue

                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                language = detect_language(file_path)
                content_type = classify_content_type(language)

                yield RawDocument(
                    content=content,
                    file_path=file_path,
                    content_type=content_type,
                    language=language,
                    size_bytes=size,
                    metadata={"zip_filename": self._zip_config.filename},
                )
                self.progress.processed += 1
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                self.progress.errors += 1

        self.status = ConnectorStatus.CONNECTED

    def _collect_files(self, file_filter: FileFilter) -> list[str]:
        files = []
        for root, dirs, filenames in os.walk(self._extract_path):
            rel_root = os.path.relpath(root, self._extract_path)
            if rel_root == ".":
                rel_root = ""
            dirs[:] = [
                d for d in dirs
                if not file_filter.should_exclude_dir(
                    os.path.join(rel_root, d) if rel_root else d
                )
            ]
            for fname in filenames:
                rel_path = os.path.join(rel_root, fname) if rel_root else fname
                if file_filter.should_include(rel_path):
                    files.append(rel_path)
        return sorted(files)

    def get_source_info(self) -> dict:
        return {
            "filename": self._zip_config.filename,
            "upload_path": self._zip_config.upload_path,
            "extract_path": self._extract_path,
        }

    def disconnect(self) -> None:
        if self._extract_path and os.path.exists(self._extract_path):
            shutil.rmtree(self._extract_path, ignore_errors=True)
        self._extract_path = ""
        super().disconnect()
