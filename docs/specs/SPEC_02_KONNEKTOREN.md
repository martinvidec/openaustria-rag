# SPEC-02: Konnektoren

**Referenz:** MVP_KONZEPT.md (Lokale Variante)
**Version:** 1.0
**Datum:** 2026-03-14

---

## 1. Ueberblick

Dieses Dokument spezifiziert das Konnektor-System: das Plugin-Interface, die drei MVP-Konnektoren (Git, ZIP, Confluence) sowie Fehlerbehandlung, Konfiguration und Testbarkeit.

---

## 2. BaseConnector Interface

### 2.1 Abstrakte Basisklasse

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generator
import logging

logger = logging.getLogger(__name__)

class ConnectorStatus(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FETCHING = "fetching"
    ERROR = "error"

@dataclass
class ConnectorProgress:
    total: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    current_item: str = ""

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.processed + self.skipped) / self.total * 100

@dataclass
class RawDocument:
    """Rohes Dokument wie es vom Konnektor geliefert wird."""
    content: str
    file_path: str                       # Relativer Pfad oder URL
    content_type: str                    # "code" | "documentation" | ...
    language: str | None = None
    encoding: str = "utf-8"
    size_bytes: int = 0
    last_modified: datetime | None = None
    metadata: dict = field(default_factory=dict)

class BaseConnector(ABC):
    """Abstrakte Basisklasse fuer alle Konnektoren."""

    def __init__(self, source_id: str, config: dict):
        self.source_id = source_id
        self.config = config
        self.status = ConnectorStatus.IDLE
        self.progress = ConnectorProgress()
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """Validiert die Konfiguration. Wirft ValueError bei Fehlern."""

    @abstractmethod
    def connect(self) -> None:
        """Stellt Verbindung zur Quelle her.
        Wirft ConnectionError bei Fehlern.
        """

    @abstractmethod
    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        """Liefert Dokumente als Generator (Streaming, speicherschonend).
        Wirft ConnectorError bei Fehlern.
        """

    @abstractmethod
    def get_source_info(self) -> dict:
        """Liefert Metadaten ueber die Quelle.
        Z.B. Anzahl Dateien, letzte Aenderung, etc.
        """

    def disconnect(self) -> None:
        """Optionales Cleanup. Default: No-op."""
        self.status = ConnectorStatus.IDLE

    def test_connection(self) -> bool:
        """Testet ob die Verbindung funktioniert."""
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception as e:
            logger.warning(f"Connection test failed: {e}")
            return False
```

### 2.2 Fehlerklassen

```python
class ConnectorError(Exception):
    """Basis-Exception fuer Konnektor-Fehler."""
    def __init__(self, message: str, source_id: str = "", recoverable: bool = False):
        self.source_id = source_id
        self.recoverable = recoverable
        super().__init__(message)

class ConnectorConfigError(ConnectorError):
    """Fehlerhafte Konfiguration."""

class ConnectorAuthError(ConnectorError):
    """Authentifizierungsfehler."""

class ConnectorNetworkError(ConnectorError):
    """Netzwerkfehler (recoverable)."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, recoverable=True, **kwargs)

class ConnectorRateLimitError(ConnectorError):
    """Rate Limit erreicht (recoverable)."""
    def __init__(self, message: str, retry_after: int = 60, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, recoverable=True, **kwargs)
```

### 2.3 Plugin-Registrierung

Konnektoren registrieren sich ueber `entry_points` in `pyproject.toml`:

```toml
[project.entry-points."openaustria_rag.connectors"]
git = "openaustria_rag.connectors.git_connector:GitConnector"
zip = "openaustria_rag.connectors.zip_connector:ZipConnector"
confluence = "openaustria_rag.connectors.confluence_connector:ConfluenceConnector"
```

**ConnectorRegistry:**

```python
from importlib.metadata import entry_points

class ConnectorRegistry:
    """Registrierung und Instanziierung von Konnektoren."""

    @staticmethod
    def get_available() -> dict[str, type[BaseConnector]]:
        """Liefert alle registrierten Konnektor-Typen."""
        connectors = {}
        eps = entry_points(group="openaustria_rag.connectors")
        for ep in eps:
            connectors[ep.name] = ep.load()
        return connectors

    @staticmethod
    def create(source_type: str, source_id: str, config: dict) -> BaseConnector:
        """Erstellt eine Konnektor-Instanz."""
        available = ConnectorRegistry.get_available()
        if source_type not in available:
            raise ConnectorConfigError(
                f"Unknown connector type: {source_type}. "
                f"Available: {list(available.keys())}"
            )
        return available[source_type](source_id, config)
```

---

## 3. Git-Repo Konnektor

### 3.1 Konfiguration

```python
@dataclass
class GitConfig:
    url: str                             # HTTPS oder SSH URL
    branch: str | None = None            # None = Default Branch
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
    max_file_size_kb: int = 500          # Dateien > 500 KB ignorieren
    auth_token: str | None = None        # Personal Access Token
    ssh_key_path: str | None = None
    depth: int | None = 1                # Shallow Clone (None = full)
```

### 3.2 Implementierung

```python
import os
import tempfile
from pathlib import Path
from fnmatch import fnmatch
from git import Repo, GitCommandError

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
        if not (url.startswith("https://") or url.startswith("git@")):
            raise ConnectorConfigError(
                f"Invalid Git URL: {url}. Must start with https:// or git@",
                self.source_id
            )
        self._git_config = GitConfig(**{
            k: v for k, v in self.config.items()
            if k in GitConfig.__dataclass_fields__
        })

    def connect(self) -> None:
        """Clont das Repository in ein lokales Verzeichnis."""
        self.status = ConnectorStatus.CONNECTING
        self._repo_path = os.path.join("data", "repos", self.source_id)
        os.makedirs(self._repo_path, exist_ok=True)

        clone_kwargs = {}
        if self._git_config.depth is not None:
            clone_kwargs["depth"] = self._git_config.depth
        if self._git_config.branch:
            clone_kwargs["branch"] = self._git_config.branch

        try:
            if os.path.exists(os.path.join(self._repo_path, ".git")):
                # Repo existiert bereits -> Pull
                self._repo = Repo(self._repo_path)
                self._repo.remotes.origin.pull()
            else:
                # Neuer Clone
                env = {}
                if self._git_config.auth_token:
                    url = self._git_config.url
                    # Token in URL einbetten fuer HTTPS
                    if url.startswith("https://"):
                        parts = url.split("://", 1)
                        url = f"{parts[0]}://oauth2:{self._git_config.auth_token}@{parts[1]}"
                    clone_kwargs["url"] = url
                else:
                    clone_kwargs["url"] = self._git_config.url

                self._repo = Repo.clone_from(
                    to_path=self._repo_path,
                    **clone_kwargs
                )
            self.status = ConnectorStatus.CONNECTED
        except GitCommandError as e:
            self.status = ConnectorStatus.ERROR
            if "Authentication" in str(e) or "403" in str(e):
                raise ConnectorAuthError(str(e), self.source_id)
            raise ConnectorNetworkError(str(e), source_id=self.source_id)

    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        """Traversiert das Repository und liefert Dokumente."""
        if not self._repo:
            raise ConnectorError("Not connected", self.source_id)

        self.status = ConnectorStatus.FETCHING
        all_files = self._collect_files()
        self.progress.total = len(all_files)

        for file_path in all_files:
            abs_path = os.path.join(self._repo_path, file_path)
            try:
                size = os.path.getsize(abs_path)
                if size > self._git_config.max_file_size_kb * 1024:
                    self.progress.skipped += 1
                    continue

                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                language = self._detect_language(file_path)
                content_type = self._classify_content(file_path, language)

                # Git-Metadaten extrahieren
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
                    }
                )
                self.progress.processed += 1
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                self.progress.errors += 1

        self.status = ConnectorStatus.CONNECTED

    def _collect_files(self) -> list[str]:
        """Sammelt alle relevanten Dateien basierend auf Include/Exclude-Patterns."""
        files = []
        for root, dirs, filenames in os.walk(self._repo_path):
            # Exclude-Directories frueh filtern
            rel_root = os.path.relpath(root, self._repo_path)
            dirs[:] = [
                d for d in dirs
                if not any(
                    fnmatch(os.path.join(rel_root, d) + "/", pat)
                    for pat in self._git_config.exclude_patterns
                )
                and d != ".git"
            ]
            for fname in filenames:
                rel_path = os.path.join(rel_root, fname)
                if rel_path.startswith("./"):
                    rel_path = rel_path[2:]
                if self._matches_include(rel_path) and not self._matches_exclude(rel_path):
                    files.append(rel_path)
        return sorted(files)

    def _matches_include(self, path: str) -> bool:
        return any(fnmatch(path, pat) for pat in self._git_config.include_patterns)

    def _matches_exclude(self, path: str) -> bool:
        return any(fnmatch(path, pat) for pat in self._git_config.exclude_patterns)

    def _detect_language(self, file_path: str) -> str | None:
        ext_map = {
            ".java": "java", ".py": "python", ".ts": "typescript",
            ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
            ".go": "go", ".rs": "rust", ".cs": "csharp", ".kt": "kotlin",
            ".md": "markdown", ".rst": "rst", ".yaml": "yaml",
            ".yml": "yaml", ".json": "json", ".toml": "toml",
            ".xml": "xml", ".html": "html",
        }
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext)

    def _classify_content(self, file_path: str, language: str | None) -> str:
        doc_languages = {"markdown", "rst"}
        config_languages = {"yaml", "json", "toml", "xml"}
        if language in doc_languages:
            return "documentation"
        if language in config_languages:
            return "config"
        return "code"

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
        files = self._collect_files() if self._repo else []
        return {
            "url": self._git_config.url,
            "branch": self._git_config.branch or "default",
            "file_count": len(files),
            "repo_path": self._repo_path,
        }

    def disconnect(self) -> None:
        self._repo = None
        super().disconnect()
```

### 3.3 Sicherheit

| Risiko | Massnahme |
|---|---|
| Repo mit Malware | Dateien werden nur gelesen, nie ausgefuehrt |
| Sehr grosse Repos | `depth=1` (Shallow Clone), `max_file_size_kb` Limit |
| Token in Logs | Token wird nicht geloggt, nur in URL eingebettet |
| Symlink-Angriffe | `os.path.realpath()` pruefen, Symlinks ignorieren |

---

## 4. ZIP-Upload Konnektor

### 4.1 Konfiguration

```python
@dataclass
class ZipConfig:
    upload_path: str                     # Pfad zur hochgeladenen ZIP-Datei
    filename: str = ""                   # Original-Dateiname
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
    max_total_size_mb: int = 200         # Maximale ZIP-Groesse
```

### 4.2 Implementierung

```python
import zipfile
import shutil

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

        # Groessen-Check
        size_mb = os.path.getsize(path) / (1024 * 1024)
        max_size = self.config.get("max_total_size_mb", 200)
        if size_mb > max_size:
            raise ConnectorConfigError(
                f"ZIP file too large: {size_mb:.1f} MB (max: {max_size} MB)",
                self.source_id
            )
        self._zip_config = ZipConfig(**{
            k: v for k, v in self.config.items()
            if k in ZipConfig.__dataclass_fields__
        })

    def connect(self) -> None:
        """Entpackt die ZIP-Datei in ein temporaeres Verzeichnis."""
        self.status = ConnectorStatus.CONNECTING
        self._extract_path = os.path.join("data", "uploads", self.source_id)
        os.makedirs(self._extract_path, exist_ok=True)

        try:
            with zipfile.ZipFile(self._zip_config.upload_path, "r") as zf:
                # Sicherheitspruefung: Path Traversal
                for member in zf.namelist():
                    member_path = os.path.realpath(
                        os.path.join(self._extract_path, member)
                    )
                    if not member_path.startswith(
                        os.path.realpath(self._extract_path)
                    ):
                        raise ConnectorError(
                            f"Path traversal detected: {member}",
                            self.source_id
                        )
                zf.extractall(self._extract_path)
            self.status = ConnectorStatus.CONNECTED
        except zipfile.BadZipFile as e:
            self.status = ConnectorStatus.ERROR
            raise ConnectorError(f"Corrupt ZIP file: {e}", self.source_id)

    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        """Identisch mit GitConnector._collect_files + Iteration.
        Nutzt die gleiche Logik fuer Include/Exclude und Language Detection.
        """
        if not self._extract_path:
            raise ConnectorError("Not connected", self.source_id)

        self.status = ConnectorStatus.FETCHING
        all_files = self._collect_files()
        self.progress.total = len(all_files)

        for file_path in all_files:
            abs_path = os.path.join(self._extract_path, file_path)
            try:
                size = os.path.getsize(abs_path)
                if size > self._zip_config.max_file_size_kb * 1024:
                    self.progress.skipped += 1
                    continue

                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

                language = self._detect_language(file_path)
                content_type = self._classify_content(file_path, language)

                yield RawDocument(
                    content=content,
                    file_path=file_path,
                    content_type=content_type,
                    language=language,
                    size_bytes=size,
                    metadata={
                        "zip_filename": self._zip_config.filename,
                    }
                )
                self.progress.processed += 1
            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                self.progress.errors += 1

        self.status = ConnectorStatus.CONNECTED

    # _collect_files, _detect_language, _classify_content: identisch zum GitConnector
    # → in Praxis als Mixin oder Utility-Funktionen extrahieren

    def disconnect(self) -> None:
        """Loescht das entpackte Verzeichnis."""
        if self._extract_path and os.path.exists(self._extract_path):
            shutil.rmtree(self._extract_path, ignore_errors=True)
        self._extract_path = ""
        super().disconnect()

    def get_source_info(self) -> dict:
        return {
            "filename": self._zip_config.filename,
            "size_mb": os.path.getsize(self._zip_config.upload_path) / (1024*1024),
            "extract_path": self._extract_path,
        }
```

### 4.3 Sicherheit

| Risiko | Massnahme |
|---|---|
| Path Traversal (Zip Slip) | `os.path.realpath()` Check vor Extraktion |
| Zip Bomb | `max_total_size_mb` Limit, Entpack-Ratio pruefen |
| Ausfuehrbare Dateien | Werden nur gelesen, nie ausgefuehrt |
| Temporaere Dateien | `disconnect()` raeumt Verzeichnis auf |

---

## 5. Confluence API Konnektor

### 5.1 Konfiguration

```python
@dataclass
class ConfluenceConfig:
    base_url: str                        # z.B. "https://company.atlassian.net"
    space_key: str                       # z.B. "PROJ"
    email: str
    api_token: str                       # Atlassian API Token
    page_limit: int = 500                # Max Seiten pro Sync
    include_labels: list[str] = field(default_factory=list)
    exclude_title_patterns: list[str] = field(default_factory=list)
    include_attachments: bool = False    # PDFs etc. herunterladen
    sync_archived: bool = False          # Archivierte Seiten einbeziehen
```

### 5.2 Implementierung

```python
import requests
from requests.auth import HTTPBasicAuth
import html2text

class ConfluenceConnector(BaseConnector):

    CONFLUENCE_API_V2 = "/wiki/api/v2"
    PAGE_SIZE = 25  # Confluence API Default

    def __init__(self, source_id: str, config: dict):
        self._conf_config: ConfluenceConfig | None = None
        self._session: requests.Session | None = None
        self._space_id: str | None = None
        super().__init__(source_id, config)

    def _validate_config(self) -> None:
        required = ["base_url", "space_key", "email", "api_token"]
        for field in required:
            if field not in self.config:
                raise ConnectorConfigError(
                    f"'{field}' is required for Confluence connector",
                    self.source_id
                )
        self._conf_config = ConfluenceConfig(**{
            k: v for k, v in self.config.items()
            if k in ConfluenceConfig.__dataclass_fields__
        })

    def connect(self) -> None:
        """Stellt Verbindung zur Confluence API her und validiert Zugang."""
        self.status = ConnectorStatus.CONNECTING
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(
            self._conf_config.email,
            self._conf_config.api_token
        )
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        # Verbindung testen + Space ID ermitteln
        try:
            resp = self._api_get(f"/wiki/api/v2/spaces", params={
                "keys": self._conf_config.space_key,
                "limit": 1,
            })
            spaces = resp.get("results", [])
            if not spaces:
                raise ConnectorConfigError(
                    f"Space '{self._conf_config.space_key}' not found",
                    self.source_id
                )
            self._space_id = spaces[0]["id"]
            self.status = ConnectorStatus.CONNECTED
        except requests.exceptions.ConnectionError as e:
            self.status = ConnectorStatus.ERROR
            raise ConnectorNetworkError(str(e), source_id=self.source_id)
        except requests.exceptions.HTTPError as e:
            self.status = ConnectorStatus.ERROR
            if e.response and e.response.status_code in (401, 403):
                raise ConnectorAuthError(
                    "Authentication failed. Check email and API token.",
                    self.source_id
                )
            raise ConnectorError(str(e), self.source_id)

    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        """Laedt alle Seiten des konfigurierten Confluence Space."""
        if not self._session or not self._space_id:
            raise ConnectorError("Not connected", self.source_id)

        self.status = ConnectorStatus.FETCHING
        h2t = html2text.HTML2Text()
        h2t.ignore_links = False
        h2t.ignore_images = True
        h2t.body_width = 0               # Kein Line-Wrapping

        cursor = None
        page_count = 0

        while True:
            params = {
                "limit": self.PAGE_SIZE,
                "body-format": "storage",  # HTML-Body
                "status": "current",
            }
            if cursor:
                params["cursor"] = cursor

            try:
                resp = self._api_get(
                    f"/wiki/api/v2/spaces/{self._space_id}/pages",
                    params=params
                )
            except ConnectorRateLimitError:
                # Bei Rate Limit: warten und retry
                import time
                time.sleep(60)
                continue

            pages = resp.get("results", [])
            if not pages:
                break

            for page in pages:
                page_count += 1
                if page_count > self._conf_config.page_limit:
                    self.status = ConnectorStatus.CONNECTED
                    return

                title = page.get("title", "")

                # Title-Filter pruefen
                if self._should_exclude_title(title):
                    self.progress.skipped += 1
                    continue

                # Label-Filter pruefen
                if self._conf_config.include_labels:
                    page_labels = self._get_page_labels(page["id"])
                    if not any(l in self._conf_config.include_labels for l in page_labels):
                        self.progress.skipped += 1
                        continue

                # HTML-Body extrahieren und zu Markdown konvertieren
                html_body = page.get("body", {}).get("storage", {}).get("value", "")
                if not html_body:
                    self.progress.skipped += 1
                    continue

                markdown_content = h2t.handle(html_body)
                # Titel als H1 voranstellen
                full_content = f"# {title}\n\n{markdown_content}"

                # Seitenstruktur (Parent) ermitteln
                parent_id = page.get("parentId")

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
                        "confluence_parent_id": parent_id,
                        "confluence_status": page.get("status"),
                        "last_modified": page.get("version", {}).get("createdAt"),
                    }
                )
                self.progress.processed += 1

            # Naechste Seite (Cursor-basierte Pagination)
            next_link = resp.get("_links", {}).get("next")
            if not next_link:
                break
            # Cursor aus next_link URL extrahieren
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(next_link)
            query_params = parse_qs(parsed.query)
            cursor = query_params.get("cursor", [None])[0]
            if not cursor:
                break

        self.status = ConnectorStatus.CONNECTED

    def _api_get(self, path: str, params: dict = None) -> dict:
        """Fuehrt einen GET-Request gegen die Confluence API aus."""
        url = f"{self._conf_config.base_url}{path}"
        resp = self._session.get(url, params=params, timeout=30)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            raise ConnectorRateLimitError(
                "Rate limit exceeded",
                retry_after=retry_after,
                source_id=self.source_id
            )

        resp.raise_for_status()
        return resp.json()

    def _get_page_labels(self, page_id: str) -> list[str]:
        try:
            resp = self._api_get(f"/wiki/api/v2/pages/{page_id}/labels")
            return [l["name"] for l in resp.get("results", [])]
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
        if not self._session or not self._space_id:
            return {"space_key": self._conf_config.space_key, "connected": False}

        try:
            resp = self._api_get(
                f"/wiki/api/v2/spaces/{self._space_id}/pages",
                params={"limit": 1}
            )
            # total aus Response Header oder Schatzung
            return {
                "space_key": self._conf_config.space_key,
                "space_id": self._space_id,
                "connected": True,
                "base_url": self._conf_config.base_url,
            }
        except Exception:
            return {"space_key": self._conf_config.space_key, "connected": False}

    def disconnect(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        super().disconnect()
```

### 5.3 Rate Limiting & Retry

```python
# Retry-Strategie fuer Confluence API:
# - 429 Too Many Requests: Retry-After Header beachten
# - 5xx Server Error: 3 Retries mit exponentiellem Backoff
# - Timeout: 30 Sekunden pro Request, 3 Retries

RETRY_CONFIG = {
    "max_retries": 3,
    "backoff_factor": 2,          # 2s, 4s, 8s
    "retry_on_status": [429, 500, 502, 503, 504],
}
```

### 5.4 Inkrementelle Updates

```python
def fetch_updated_since(self, since: datetime) -> Generator[RawDocument, None, None]:
    """Laedt nur Seiten die seit 'since' geaendert wurden.
    Nutzt Confluence CQL (Content Query Language).
    """
    cql = (
        f'space = "{self._conf_config.space_key}" '
        f'AND lastModified > "{since.strftime("%Y-%m-%d %H:%M")}"'
    )
    # CQL-Suche ueber v1 API (v2 unterstuetzt CQL nicht direkt)
    resp = self._api_get("/wiki/rest/api/content/search", params={
        "cql": cql,
        "limit": self.PAGE_SIZE,
        "expand": "body.storage,version",
    })
    # ... weitere Verarbeitung analog zu fetch_documents
```

---

## 6. Shared Utilities

### 6.1 FileFilter (gemeinsam fuer Git + ZIP)

```python
class FileFilter:
    """Wiederverwendbare Datei-Filterung fuer Git und ZIP Konnektoren."""

    def __init__(
        self,
        include_patterns: list[str],
        exclude_patterns: list[str],
        max_file_size_kb: int = 500,
    ):
        self.include_patterns = include_patterns
        self.exclude_patterns = exclude_patterns
        self.max_file_size_kb = max_file_size_kb

    def should_include(self, rel_path: str, size_bytes: int = 0) -> bool:
        if size_bytes > self.max_file_size_kb * 1024:
            return False
        if not any(fnmatch(rel_path, p) for p in self.include_patterns):
            return False
        if any(fnmatch(rel_path, p) for p in self.exclude_patterns):
            return False
        return True
```

### 6.2 LanguageDetector

```python
EXTENSION_MAP: dict[str, str] = {
    ".java": "java", ".py": "python", ".ts": "typescript",
    ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".cs": "csharp", ".kt": "kotlin",
    ".md": "markdown", ".rst": "rst",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json",
    ".toml": "toml", ".xml": "xml", ".html": "html",
}

CODE_LANGUAGES = {"java", "python", "typescript", "javascript", "go", "rust", "csharp", "kotlin"}
DOC_LANGUAGES = {"markdown", "rst"}
CONFIG_LANGUAGES = {"yaml", "json", "toml", "xml"}

def detect_language(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return EXTENSION_MAP.get(ext)

def classify_content_type(language: str | None) -> str:
    if language in DOC_LANGUAGES:
        return "documentation"
    if language in CONFIG_LANGUAGES:
        return "config"
    return "code"
```

---

## 7. Testbarkeit

### 7.1 Test-Strategie

| Test-Typ | Scope | Ansatz |
|---|---|---|
| Unit Tests | Einzelne Methoden | Mocking von Dateisystem und API |
| Integration Tests | Konnektor Ende-zu-Ende | Echtes lokales Git-Repo, echte ZIP-Datei |
| Confluence Tests | API-Integration | Responses mocken via `responses` Library |
| Contract Tests | Interface-Konformitaet | Jeder Konnektor wird gegen BaseConnector-Contract getestet |

### 7.2 Contract Test

```python
import pytest
from abc import ABC

class ConnectorContractTest(ABC):
    """Jeder Konnektor muss diese Tests bestehen."""

    @pytest.fixture
    @abstractmethod
    def connector(self) -> BaseConnector:
        """Liefert eine konfigurierte Konnektor-Instanz."""

    def test_connect(self, connector):
        connector.connect()
        assert connector.status == ConnectorStatus.CONNECTED

    def test_fetch_documents_yields_raw_documents(self, connector):
        connector.connect()
        docs = list(connector.fetch_documents())
        assert len(docs) > 0
        for doc in docs:
            assert isinstance(doc, RawDocument)
            assert doc.content
            assert doc.file_path
            assert doc.content_type in ("code", "documentation", "config", "specification")

    def test_progress_tracking(self, connector):
        connector.connect()
        list(connector.fetch_documents())
        assert connector.progress.processed > 0
        assert connector.progress.total > 0

    def test_disconnect(self, connector):
        connector.connect()
        connector.disconnect()
        assert connector.status == ConnectorStatus.IDLE

    def test_invalid_config_raises(self):
        with pytest.raises(ConnectorConfigError):
            self.create_connector_with_invalid_config()

    @abstractmethod
    def create_connector_with_invalid_config(self) -> BaseConnector:
        """Erstellt einen Konnektor mit ungueltiger Config."""
```
