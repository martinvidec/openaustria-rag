"""Shared utilities for connectors: file filtering and language detection (SPEC-02 Section 6)."""

from fnmatch import fnmatch
from pathlib import Path, PurePosixPath


EXTENSION_MAP: dict[str, str] = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
}

CODE_LANGUAGES = {"java", "python", "typescript", "javascript", "go", "rust", "csharp", "kotlin"}
DOC_LANGUAGES = {"markdown", "rst", "text"}
CONFIG_LANGUAGES = {"yaml", "json", "toml", "xml"}


def detect_language(file_path: str) -> str | None:
    """Detect programming/markup language from file extension."""
    ext = Path(file_path).suffix.lower()
    return EXTENSION_MAP.get(ext)


def classify_content_type(language: str | None) -> str:
    """Classify content type based on detected language."""
    if language in DOC_LANGUAGES:
        return "documentation"
    if language in CONFIG_LANGUAGES:
        return "config"
    return "code"


class FileFilter:
    """Reusable file filtering for Git and ZIP connectors."""

    def __init__(
        self,
        include_patterns: list[str],
        exclude_patterns: list[str],
        max_file_size_kb: int = 500,
    ):
        self.include_patterns = include_patterns
        self.exclude_patterns = exclude_patterns
        self.max_file_size_kb = max_file_size_kb

    def _matches_pattern(self, rel_path: str, pattern: str) -> bool:
        """Match a path against a pattern, supporting ** for recursive matching."""
        if "**" in pattern:
            # For patterns like **/dirname/**, check if dirname appears as a path component
            stripped = pattern.replace("**", "").strip("/")
            if "/" not in stripped:
                # Simple directory exclusion: **/test/** -> check if "test" is a component
                parts = PurePosixPath(rel_path).parts
                return stripped in parts
            return PurePosixPath(rel_path).match(pattern)
        return fnmatch(rel_path, pattern) or fnmatch(Path(rel_path).name, pattern)

    def should_include(self, rel_path: str, size_bytes: int = 0) -> bool:
        """Check if a file should be included based on patterns and size."""
        if size_bytes > self.max_file_size_kb * 1024:
            return False
        if not any(self._matches_pattern(rel_path, p) for p in self.include_patterns):
            return False
        if any(self._matches_pattern(rel_path, p) for p in self.exclude_patterns):
            return False
        return True

    def should_exclude_dir(self, rel_dir_path: str) -> bool:
        """Check if a directory should be skipped entirely."""
        dir_name = Path(rel_dir_path).name
        for pattern in self.exclude_patterns:
            if "**" in pattern:
                parts = pattern.split("/")
                # Check if any part of the pattern is the directory name
                if dir_name in parts:
                    return True
            else:
                dir_with_slash = rel_dir_path.rstrip("/") + "/"
                if fnmatch(dir_with_slash, pattern):
                    return True
        return False
