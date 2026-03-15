"""Central configuration system using Pydantic Settings with YAML + env overrides."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


class OllamaConfig(BaseModel):
    """Ollama LLM runtime configuration."""

    base_url: str = "http://localhost:11434"
    model: str = "mistral"
    temperature: float = 0.1
    timeout_seconds: int = 300


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""

    model: str = "nomic-embed-text"
    dimensions: int = 768
    timeout_seconds: int = 30
    query_prefix: str = "search_query: "
    document_prefix: str = "search_document: "


class ChunkingConfig(BaseModel):
    """Chunking strategy configuration."""

    code_max_tokens: int = 2048
    doc_max_tokens: int = 1024
    doc_min_tokens: int = 64
    doc_overlap_tokens: int = 128
    config_max_tokens: int = 2048
    include_context_header: bool = True


class VectorStoreConfig(BaseModel):
    """ChromaDB vector store configuration."""

    persist_path: str = "data/chromadb"
    distance_metric: str = "cosine"
    batch_size: int = 50
    max_concurrent_documents: int = 4


class CodeParserConfig(BaseModel):
    """tree-sitter code parser configuration."""

    languages: list[str] = Field(default_factory=lambda: ["java", "python", "typescript"])
    fallback_regex: bool = True


class GapAnalysisConfig(BaseModel):
    """Gap analysis engine configuration."""

    name_similarity_threshold: float = 0.6
    embedding_similarity_threshold: float = 0.7
    max_embedding_candidates: int = 5
    run_llm_analysis: bool = True
    max_llm_analyses_per_run: int = 50
    llm_temperature: float = 0.1
    timeout_seconds: int = 60
    element_kinds: list[str] = Field(
        default_factory=lambda: ["class", "interface", "method", "function"]
    )
    exclude_test_files: bool = True
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/test/**",
            "**/*Test.java",
            "**/*_test.py",
            "**/*Spec.scala",
        ]
    )


class YamlSettingsSource(PydanticBaseSettingsSource):
    """Load settings from config.yaml if it exists."""

    def get_field_value(self, field, field_name):
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH) as f:
                return yaml.safe_load(f) or {}
        return {}


class Settings(BaseSettings):
    """Application settings with YAML file + environment variable support.

    Priority (highest to lowest):
    1. Environment variables (prefixed with OARAG_)
    2. config.yaml
    3. Defaults defined here
    """

    model_config = SettingsConfigDict(
        env_prefix="OARAG_",
        env_nested_delimiter="__",
    )

    data_dir: str = "data"
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    code_parser: CodeParserConfig = Field(default_factory=CodeParserConfig)
    gap_analysis: GapAnalysisConfig = Field(default_factory=GapAnalysisConfig)

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (
            kwargs.get("env_settings"),
            YamlSettingsSource(settings_cls),
            kwargs.get("init_settings"),
        )

    def ensure_data_dirs(self) -> None:
        """Create the data directory structure if it doesn't exist."""
        data_path = PROJECT_ROOT / self.data_dir
        (data_path / "chromadb").mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Load and return application settings."""
    settings = Settings()
    settings.ensure_data_dirs()
    return settings
