"""Tests for connector utilities (SPEC-02 Section 6)."""

from openaustria_rag.connectors.utils import (
    CODE_LANGUAGES,
    CONFIG_LANGUAGES,
    DOC_LANGUAGES,
    FileFilter,
    classify_content_type,
    detect_language,
)


class TestDetectLanguage:
    def test_python(self):
        assert detect_language("src/main.py") == "python"

    def test_java(self):
        assert detect_language("com/example/App.java") == "java"

    def test_typescript(self):
        assert detect_language("app/index.ts") == "typescript"
        assert detect_language("app/Component.tsx") == "typescript"

    def test_markdown(self):
        assert detect_language("README.md") == "markdown"

    def test_yaml(self):
        assert detect_language("config.yaml") == "yaml"
        assert detect_language("config.yml") == "yaml"

    def test_unknown_extension(self):
        assert detect_language("file.xyz") is None

    def test_case_insensitive(self):
        assert detect_language("Main.PY") == "python"


class TestClassifyContentType:
    def test_code(self):
        assert classify_content_type("python") == "code"
        assert classify_content_type("java") == "code"

    def test_documentation(self):
        assert classify_content_type("markdown") == "documentation"
        assert classify_content_type("rst") == "documentation"

    def test_config(self):
        assert classify_content_type("yaml") == "config"
        assert classify_content_type("json") == "config"

    def test_unknown_defaults_to_code(self):
        assert classify_content_type(None) == "code"
        assert classify_content_type("unknown") == "code"


class TestLanguageSets:
    def test_code_languages(self):
        assert "java" in CODE_LANGUAGES
        assert "python" in CODE_LANGUAGES

    def test_doc_languages(self):
        assert "markdown" in DOC_LANGUAGES

    def test_config_languages(self):
        assert "yaml" in CONFIG_LANGUAGES
        assert "json" in CONFIG_LANGUAGES


class TestFileFilter:
    def test_include_match(self):
        f = FileFilter(include_patterns=["*.py"], exclude_patterns=[])
        assert f.should_include("main.py") is True
        assert f.should_include("main.java") is False

    def test_exclude_match(self):
        f = FileFilter(
            include_patterns=["*.py"],
            exclude_patterns=["**/test/**"],
        )
        assert f.should_include("src/main.py") is True
        assert f.should_include("test/test_main.py") is False

    def test_size_limit(self):
        f = FileFilter(
            include_patterns=["*.py"],
            exclude_patterns=[],
            max_file_size_kb=10,
        )
        assert f.should_include("main.py", size_bytes=5000) is True
        assert f.should_include("big.py", size_bytes=20_000) is False

    def test_should_exclude_dir(self):
        f = FileFilter(
            include_patterns=["*.py"],
            exclude_patterns=["**/node_modules/**"],
        )
        assert f.should_exclude_dir("node_modules") is True
        assert f.should_exclude_dir("src") is False
