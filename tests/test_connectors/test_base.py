"""Tests for base connector classes (SPEC-02 Section 2)."""

import pytest

from openaustria_rag.connectors.base import (
    BaseConnector,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorNetworkError,
    ConnectorProgress,
    ConnectorRateLimitError,
    ConnectorRegistry,
    ConnectorStatus,
    RawDocument,
)


class TestErrorClasses:
    def test_connector_error_attributes(self):
        e = ConnectorError("fail", source_id="s1", recoverable=True)
        assert str(e) == "fail"
        assert e.source_id == "s1"
        assert e.recoverable is True

    def test_config_error_is_connector_error(self):
        e = ConnectorConfigError("bad config", source_id="s1")
        assert isinstance(e, ConnectorError)

    def test_auth_error_is_connector_error(self):
        assert isinstance(ConnectorAuthError("no auth"), ConnectorError)

    def test_network_error_is_recoverable(self):
        e = ConnectorNetworkError("timeout", source_id="s1")
        assert e.recoverable is True

    def test_rate_limit_error_has_retry_after(self):
        e = ConnectorRateLimitError("slow down", retry_after=120)
        assert e.retry_after == 120
        assert e.recoverable is True


class TestConnectorProgress:
    def test_percent_zero_total(self):
        p = ConnectorProgress()
        assert p.percent == 0.0

    def test_percent_calculation(self):
        p = ConnectorProgress(total=100, processed=40, skipped=10)
        assert p.percent == 50.0


class TestRawDocument:
    def test_defaults(self):
        doc = RawDocument(content="hello", file_path="a.py", content_type="code")
        assert doc.language is None
        assert doc.encoding == "utf-8"
        assert doc.size_bytes == 0
        assert doc.metadata == {}


class TestConnectorRegistry:
    def test_get_available_returns_dict(self):
        available = ConnectorRegistry.get_available()
        assert isinstance(available, dict)
        # Our entry_points should register the git connector
        assert "git" in available

    def test_create_unknown_type_raises(self):
        with pytest.raises(ConnectorConfigError, match="Unknown connector type"):
            ConnectorRegistry.create("nonexistent", "s1", {})
