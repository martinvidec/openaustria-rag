"""Base connector interface and registry as defined in SPEC-02."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from importlib.metadata import entry_points
from typing import Generator

import logging

logger = logging.getLogger(__name__)


# --- Error classes ---

class ConnectorError(Exception):
    """Base exception for connector errors."""

    def __init__(self, message: str, source_id: str = "", recoverable: bool = False):
        self.source_id = source_id
        self.recoverable = recoverable
        super().__init__(message)


class ConnectorConfigError(ConnectorError):
    """Invalid configuration."""


class ConnectorAuthError(ConnectorError):
    """Authentication failure."""


class ConnectorNetworkError(ConnectorError):
    """Network error (recoverable)."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, recoverable=True, **kwargs)


class ConnectorRateLimitError(ConnectorError):
    """Rate limit exceeded (recoverable)."""

    def __init__(self, message: str, retry_after: int = 60, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, recoverable=True, **kwargs)


# --- Data classes ---

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
    """Raw document as delivered by a connector."""

    content: str
    file_path: str
    content_type: str
    language: str | None = None
    encoding: str = "utf-8"
    size_bytes: int = 0
    last_modified: datetime | None = None
    metadata: dict = field(default_factory=dict)


# --- Base class ---

class BaseConnector(ABC):
    """Abstract base class for all connectors."""

    def __init__(self, source_id: str, config: dict):
        self.source_id = source_id
        self.config = config
        self.status = ConnectorStatus.IDLE
        self.progress = ConnectorProgress()
        self._validate_config()

    @abstractmethod
    def _validate_config(self) -> None:
        """Validate the configuration. Raises ConnectorConfigError on failure."""

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the source."""

    @abstractmethod
    def fetch_documents(self) -> Generator[RawDocument, None, None]:
        """Yield documents as a generator (streaming, memory-efficient)."""

    @abstractmethod
    def get_source_info(self) -> dict:
        """Return metadata about the source."""

    def disconnect(self) -> None:
        """Optional cleanup. Default: reset status."""
        self.status = ConnectorStatus.IDLE

    def test_connection(self) -> bool:
        """Test whether the connection works."""
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception as e:
            logger.warning(f"Connection test failed: {e}")
            return False


# --- Registry ---

class ConnectorRegistry:
    """Discovery and instantiation of connectors via entry_points."""

    @staticmethod
    def get_available() -> dict[str, type[BaseConnector]]:
        """Return all registered connector types."""
        connectors = {}
        eps = entry_points(group="openaustria_rag.connectors")
        for ep in eps:
            try:
                connectors[ep.name] = ep.load()
            except (ImportError, ModuleNotFoundError):
                logger.debug(f"Connector '{ep.name}' not available: module not found")
        return connectors

    @staticmethod
    def create(source_type: str, source_id: str, config: dict) -> BaseConnector:
        """Create a connector instance by type name."""
        available = ConnectorRegistry.get_available()
        if source_type not in available:
            raise ConnectorConfigError(
                f"Unknown connector type: {source_type}. "
                f"Available: {list(available.keys())}"
            )
        return available[source_type](source_id, config)
