"""Tests for the ZIP connector (SPEC-02 Section 4)."""

import os
import zipfile

import pytest

from openaustria_rag.connectors.base import (
    ConnectorConfigError,
    ConnectorError,
    ConnectorStatus,
    RawDocument,
)
from openaustria_rag.connectors.zip_connector import ZipConnector


def _create_test_zip(zip_path, files: dict[str, str]):
    """Create a test ZIP with the given {path: content} mapping."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


@pytest.fixture
def test_zip(tmp_path):
    """Create a simple test ZIP file."""
    zip_path = tmp_path / "test.zip"
    _create_test_zip(zip_path, {
        "README.md": "# Hello\nWorld",
        "src/main.py": "def main():\n    pass\n",
        "src/App.java": "public class App {}",
        "config.yaml": "key: value\n",
    })
    return zip_path


@pytest.fixture
def zip_connector(test_zip, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return ZipConnector("zip-test", {"upload_path": str(test_zip)})


class TestZipValidation:
    def test_missing_upload_path_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConnectorConfigError, match="upload_path is required"):
            ZipConnector("s1", {})

    def test_nonexistent_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConnectorConfigError, match="File not found"):
            ZipConnector("s1", {"upload_path": "/nonexistent.zip"})

    def test_not_a_zip_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        not_zip = tmp_path / "fake.zip"
        not_zip.write_text("this is not a zip")
        with pytest.raises(ConnectorConfigError, match="Not a valid ZIP"):
            ZipConnector("s1", {"upload_path": str(not_zip)})

    def test_oversized_zip_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        zip_path = tmp_path / "big.zip"
        _create_test_zip(zip_path, {"a.py": "x" * 100})
        with pytest.raises(ConnectorConfigError, match="ZIP file too large"):
            ZipConnector("s1", {
                "upload_path": str(zip_path),
                "max_total_size_mb": 0,  # 0 MB limit → always too large
            })


class TestZipConnect:
    def test_connect_extracts(self, zip_connector):
        zip_connector.connect()
        assert zip_connector.status == ConnectorStatus.CONNECTED
        assert os.path.exists(os.path.join("data", "uploads", "zip-test", "README.md"))

    def test_path_traversal_blocked(self, tmp_path, monkeypatch):
        """ZIP with path traversal entries should be rejected."""
        monkeypatch.chdir(tmp_path)
        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("safe.txt", "ok")
            # Manually create an entry with path traversal
            zf.writestr("../../../etc/passwd", "evil content")
        connector = ZipConnector("s1", {"upload_path": str(zip_path)})
        with pytest.raises(ConnectorError, match="Path traversal"):
            connector.connect()


class TestZipFetch:
    def test_fetch_yields_documents(self, zip_connector):
        zip_connector.connect()
        docs = list(zip_connector.fetch_documents())
        assert len(docs) == 4
        for doc in docs:
            assert isinstance(doc, RawDocument)
            assert doc.content
            assert doc.content_type in ("code", "documentation", "config")

    def test_content_types_correct(self, zip_connector):
        zip_connector.connect()
        docs = {d.file_path: d for d in zip_connector.fetch_documents()}
        assert docs["README.md"].content_type == "documentation"
        assert docs["README.md"].language == "markdown"
        assert docs["src/main.py"].content_type == "code"
        assert docs["config.yaml"].content_type == "config"

    def test_progress_tracking(self, zip_connector):
        zip_connector.connect()
        list(zip_connector.fetch_documents())
        assert zip_connector.progress.processed == 4
        assert zip_connector.progress.total == 4

    def test_fetch_without_connect_raises(self, test_zip, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        c = ZipConnector("s1", {"upload_path": str(test_zip)})
        with pytest.raises(ConnectorError, match="Not connected"):
            list(c.fetch_documents())

    def test_metadata_has_zip_filename(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        zip_path = tmp_path / "project.zip"
        _create_test_zip(zip_path, {"main.py": "pass"})
        c = ZipConnector("s1", {
            "upload_path": str(zip_path),
            "filename": "project-v1.zip",
        })
        c.connect()
        docs = list(c.fetch_documents())
        assert docs[0].metadata["zip_filename"] == "project-v1.zip"


class TestZipDisconnect:
    def test_disconnect_cleans_up(self, zip_connector):
        zip_connector.connect()
        extract_path = os.path.join("data", "uploads", "zip-test")
        assert os.path.exists(extract_path)
        zip_connector.disconnect()
        assert not os.path.exists(extract_path)
        assert zip_connector.status == ConnectorStatus.IDLE

    def test_get_source_info(self, zip_connector):
        info = zip_connector.get_source_info()
        assert "upload_path" in info
