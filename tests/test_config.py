"""Tests for the configuration system."""

import pytest

from openaustria_rag.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Ensure tests read no config.yaml so they see pure defaults."""
    import openaustria_rag.config as cfg
    monkeypatch.setattr(cfg, "DEFAULT_CONFIG_PATH", tmp_path / "nonexistent.yaml")


class TestDefaults:
    """Verify all default values match spec requirements."""

    def test_ollama_defaults(self):
        s = Settings()
        assert s.ollama.base_url == "http://localhost:11434"
        assert s.ollama.model == "mistral"
        assert s.ollama.temperature == 0.1

    def test_embedding_defaults(self):
        s = Settings()
        assert s.embedding.model == "nomic-embed-text"
        assert s.embedding.dimensions == 768
        assert s.embedding.query_prefix == "search_query: "
        assert s.embedding.document_prefix == "search_document: "

    def test_chunking_defaults(self):
        s = Settings()
        assert s.chunking.code_max_tokens == 2048
        assert s.chunking.doc_max_tokens == 1024
        assert s.chunking.doc_min_tokens == 64
        assert s.chunking.doc_overlap_tokens == 128
        assert s.chunking.config_max_tokens == 2048
        assert s.chunking.include_context_header is True

    def test_vector_store_defaults(self):
        s = Settings()
        assert s.vector_store.persist_path == "data/chromadb"
        assert s.vector_store.distance_metric == "cosine"
        assert s.vector_store.batch_size == 50

    def test_code_parser_defaults(self):
        s = Settings()
        assert s.code_parser.languages == ["java", "python", "typescript"]
        assert s.code_parser.fallback_regex is True

    def test_gap_analysis_defaults(self):
        s = Settings()
        assert s.gap_analysis.name_similarity_threshold == 0.6
        assert s.gap_analysis.embedding_similarity_threshold == 0.7
        assert s.gap_analysis.max_embedding_candidates == 5
        assert s.gap_analysis.run_llm_analysis is True
        assert s.gap_analysis.max_llm_analyses_per_run == 50
        assert s.gap_analysis.exclude_test_files is True


class TestSettingsLoading:
    """Test settings construction and data dir creation."""

    def test_get_settings_returns_settings(self):
        s = get_settings()
        assert isinstance(s, Settings)

    def test_import_package(self):
        import openaustria_rag
        assert openaustria_rag.__version__ == "0.1.0"

    def test_ensure_data_dirs(self, tmp_path, monkeypatch):
        import openaustria_rag.config as cfg

        monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
        s = Settings(data_dir="data")
        s.ensure_data_dirs()
        assert (tmp_path / "data" / "chromadb").is_dir()

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("OARAG_OLLAMA__MODEL", "llama3")
        s = Settings()
        assert s.ollama.model == "llama3"
