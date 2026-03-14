"""Tests for the Git connector (SPEC-02 Section 3).

Uses a local test repo created via gitpython in tmp_path.
"""

import os

import pytest
from git import Repo

from openaustria_rag.connectors.base import (
    ConnectorConfigError,
    ConnectorStatus,
    RawDocument,
)
from openaustria_rag.connectors.git_connector import GitConnector


@pytest.fixture
def local_repo(tmp_path):
    """Create a local git repo with test files."""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()
    repo = Repo.init(repo_path)

    # Create test files
    (repo_path / "README.md").write_text("# Test Project\nHello world")
    (repo_path / "main.py").write_text("def hello():\n    print('hi')\n")
    (repo_path / "config.yaml").write_text("key: value\n")

    src_dir = repo_path / "src"
    src_dir.mkdir()
    (src_dir / "app.java").write_text("public class App {}")

    # Add and commit
    repo.index.add([
        str(repo_path / "README.md"),
        str(repo_path / "main.py"),
        str(repo_path / "config.yaml"),
        str(src_dir / "app.java"),
    ])
    repo.index.commit("Initial commit")

    return repo_path


@pytest.fixture
def git_connector(local_repo, tmp_path, monkeypatch):
    """Create a GitConnector pointing to the local repo."""
    # Override data dir so clone goes into tmp
    monkeypatch.chdir(tmp_path)
    connector = GitConnector(
        source_id="test-source",
        config={
            "url": str(local_repo),
            "depth": None,  # Full clone for local repos
        },
    )
    return connector


class TestGitConnectorValidation:
    def test_missing_url_raises(self):
        with pytest.raises(ConnectorConfigError, match="Git URL is required"):
            GitConnector("s1", {})

    def test_invalid_url_raises(self):
        with pytest.raises(ConnectorConfigError, match="Invalid Git URL"):
            GitConnector("s1", {"url": "ftp://example.com/repo"})

    def test_valid_https_url(self):
        # Should not raise (validation only, no connect)
        c = GitConnector("s1", {"url": "https://github.com/org/repo.git"})
        assert c.status == ConnectorStatus.IDLE

    def test_valid_ssh_url(self):
        c = GitConnector("s1", {"url": "git@github.com:org/repo.git"})
        assert c.status == ConnectorStatus.IDLE


class TestGitConnectorConnect:
    def test_connect_clones_repo(self, git_connector):
        git_connector.connect()
        assert git_connector.status == ConnectorStatus.CONNECTED
        assert os.path.exists(
            os.path.join("data", "repos", "test-source", ".git")
        )

    def test_connect_pull_existing(self, git_connector):
        git_connector.connect()
        # Connect again should pull, not re-clone
        git_connector.connect()
        assert git_connector.status == ConnectorStatus.CONNECTED


class TestGitConnectorFetch:
    def test_fetch_yields_raw_documents(self, git_connector):
        git_connector.connect()
        docs = list(git_connector.fetch_documents())
        assert len(docs) > 0
        for doc in docs:
            assert isinstance(doc, RawDocument)
            assert doc.content
            assert doc.file_path
            assert doc.content_type in ("code", "documentation", "config")

    def test_fetch_content_types(self, git_connector):
        git_connector.connect()
        docs = {d.file_path: d for d in git_connector.fetch_documents()}
        assert docs["README.md"].content_type == "documentation"
        assert docs["README.md"].language == "markdown"
        assert docs["main.py"].content_type == "code"
        assert docs["main.py"].language == "python"
        assert docs["config.yaml"].content_type == "config"
        assert docs["config.yaml"].language == "yaml"

    def test_fetch_has_git_metadata(self, git_connector):
        git_connector.connect()
        docs = list(git_connector.fetch_documents())
        doc = docs[0]
        assert doc.metadata.get("git_commit") is not None
        assert doc.metadata.get("git_author") is not None

    def test_progress_tracking(self, git_connector):
        git_connector.connect()
        list(git_connector.fetch_documents())
        assert git_connector.progress.processed > 0
        assert git_connector.progress.total > 0

    def test_fetch_without_connect_raises(self):
        c = GitConnector("s1", {"url": "https://github.com/org/repo.git"})
        with pytest.raises(Exception, match="Not connected"):
            list(c.fetch_documents())


class TestGitConnectorDisconnect:
    def test_disconnect_resets_status(self, git_connector):
        git_connector.connect()
        git_connector.disconnect()
        assert git_connector.status == ConnectorStatus.IDLE

    def test_get_source_info(self, git_connector):
        git_connector.connect()
        info = git_connector.get_source_info()
        assert info["file_count"] > 0


class TestGitConnectorSecurity:
    def test_symlinks_skipped(self, local_repo, tmp_path, monkeypatch):
        """Symlinks should be skipped during fetch."""
        monkeypatch.chdir(tmp_path)
        # Create a symlink in the repo
        symlink_path = local_repo / "link.py"
        symlink_path.symlink_to(local_repo / "main.py")
        repo = Repo(local_repo)
        repo.index.add([str(symlink_path)])
        repo.index.commit("Add symlink")

        connector = GitConnector(
            "s1",
            {"url": str(local_repo), "depth": None},
        )
        connector.connect()
        docs = list(connector.fetch_documents())
        paths = [d.file_path for d in docs]
        assert "link.py" not in paths

    def test_large_files_skipped(self, local_repo, tmp_path, monkeypatch):
        """Files exceeding max_file_size_kb should be skipped."""
        monkeypatch.chdir(tmp_path)
        big_file = local_repo / "big.py"
        big_file.write_text("x" * 600_000)  # ~600 KB
        repo = Repo(local_repo)
        repo.index.add([str(big_file)])
        repo.index.commit("Add big file")

        connector = GitConnector(
            "s1",
            {"url": str(local_repo), "depth": None, "max_file_size_kb": 500},
        )
        connector.connect()
        docs = list(connector.fetch_documents())
        paths = [d.file_path for d in docs]
        assert "big.py" not in paths
        assert connector.progress.skipped > 0
