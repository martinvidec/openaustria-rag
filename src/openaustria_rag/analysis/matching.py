"""Matching utilities for gap analysis (SPEC-05)."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..models import CodeElement, GapType, Severity


@dataclass
class NameMatchResult:
    matched: bool = False
    score: float = 0.0
    matched_text: str = ""


@dataclass
class LLMAnalysisResult:
    consistent: bool = False
    divergences: str = ""
    severity: str = ""
    recommendation: str = ""
    raw_response: str = ""


@dataclass
class MatchResult:
    code_element: CodeElement
    gap_type: GapType = GapType.UNDOCUMENTED
    doc_chunk_id: str | None = None
    doc_chunk_content: str = ""
    doc_reference: str = ""
    name_score: float = 0.0
    embedding_score: float = 0.0
    llm_analysis: LLMAnalysisResult | None = None


def split_camel_case(name: str) -> list[str]:
    """Split CamelCase and snake_case into words."""
    # Handle snake_case first
    parts = name.replace("_", " ").split()
    # Split CamelCase
    result = []
    for part in parts:
        words = re.sub(r"([A-Z])", r" \1", part).split()
        result.extend(w.lower() for w in words if w)
    return result


def fuzzy_match_in_text(term: str, text: str, threshold: float = 0.6) -> NameMatchResult:
    """Match a term against words and two-word combinations in text."""
    term_lower = term.lower()
    words = text.lower().split()

    best_score = 0.0
    best_match = ""

    # Check individual words
    for word in words:
        score = SequenceMatcher(None, term_lower, word).ratio()
        if score > best_score:
            best_score = score
            best_match = word

    # Check two-word combinations
    for i in range(len(words) - 1):
        combo = f"{words[i]} {words[i + 1]}"
        score = SequenceMatcher(None, term_lower, combo).ratio()
        if score > best_score:
            best_score = score
            best_match = combo

    return NameMatchResult(
        matched=best_score >= threshold,
        score=best_score,
        matched_text=best_match,
    )


def generate_search_terms(element: CodeElement) -> list[str]:
    """Generate search terms from a code element for matching."""
    terms = [element.short_name, element.name]

    # CamelCase split
    camel_words = split_camel_case(element.short_name)
    if len(camel_words) > 1:
        terms.append(" ".join(camel_words))

    # snake_case version
    snake = "_".join(camel_words)
    if snake != element.short_name.lower():
        terms.append(snake)

    return list(dict.fromkeys(terms))  # Deduplicate preserving order


def element_to_search_text(element: CodeElement) -> str:
    """Convert a code element to searchable text for embedding."""
    parts = [element.name]
    if element.signature:
        parts.append(element.signature)
    if element.docstring:
        parts.append(element.docstring)
    if element.annotations:
        parts.append(" ".join(element.annotations))
    return " ".join(parts)


BOILERPLATE_PATTERNS = {
    "get", "set", "is", "has", "toString", "hashCode", "equals",
    "compareTo", "__init__", "__str__", "__repr__", "__eq__",
    "__hash__", "__lt__", "__gt__", "__le__", "__ge__",
}

BOILERPLATE_PREFIXES = ("get_", "set_", "is_", "has_")


def is_boilerplate(element: CodeElement) -> bool:
    """Check if an element is boilerplate (getter/setter/toString etc.)."""
    name = element.short_name
    if name in BOILERPLATE_PATTERNS:
        return True
    if any(name.startswith(p) for p in BOILERPLATE_PREFIXES):
        return True
    # Java-style getters/setters: getX, setX, isX
    if len(name) > 3 and name[:3] in ("get", "set") and name[3].isupper():
        return True
    if len(name) > 2 and name[:2] == "is" and name[2].isupper():
        return True
    return False


def estimate_severity(element: CodeElement) -> Severity:
    """Estimate severity based on element type and annotations."""
    # API endpoints are HIGH
    if element.annotations:
        api_annotations = {"@GetMapping", "@PostMapping", "@PutMapping",
                          "@DeleteMapping", "@RequestMapping", "@RestController",
                          "@Controller"}
        if any(any(a.startswith(ann) for ann in api_annotations)
               for a in element.annotations):
            return Severity.HIGH

    # Public interfaces are HIGH
    from ..models import ElementKind
    if element.kind == ElementKind.INTERFACE:
        return Severity.HIGH

    # Public classes/methods are MEDIUM
    if element.visibility == "public":
        return Severity.MEDIUM

    # Private elements are LOW
    if element.visibility == "private":
        return Severity.LOW

    return Severity.MEDIUM
