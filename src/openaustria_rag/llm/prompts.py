"""Prompt templates and context budget management (SPEC-04 Section 5)."""

from dataclasses import dataclass
from enum import Enum


class QueryType(Enum):
    SEARCH = "search"
    EXPLAIN = "explain"
    COMPARE = "compare"
    SUMMARIZE = "summarize"
    GAP_CHECK = "gap_check"


_NO_HALLUCINATE = (
    "WICHTIG: Erfinde KEINE URLs, Links oder Referenzen. "
    "Verwende NUR Links und URLs die woertlich im Kontext stehen. "
    "Wenn du dir bei einem Link nicht sicher bist, gib ihn NICHT an.\n"
)

TEMPLATES: dict[QueryType, str] = {
    QueryType.SEARCH: (
        "Du bist ein hilfreicher Assistent fuer Software-Dokumentation.\n"
        "Beantworte die Frage basierend auf dem bereitgestellten Kontext.\n"
        "Wenn die Antwort nicht im Kontext enthalten ist, sage das ehrlich.\n"
        "Referenziere die relevanten Quellen in deiner Antwort.\n"
        f"{_NO_HALLUCINATE}\n"
        "KONTEXT:\n{context}\n\n"
        "FRAGE: {query}\n\n"
        "ANTWORT:"
    ),
    QueryType.EXPLAIN: (
        "Du bist ein erfahrener Software-Entwickler.\n"
        "Erklaere den folgenden Code oder das Konzept verstaendlich.\n"
        "Nutze den bereitgestellten Kontext fuer zusaetzliche Informationen.\n"
        f"{_NO_HALLUCINATE}\n"
        "KONTEXT:\n{context}\n\n"
        "ZU ERKLAEREN: {query}\n\n"
        "ERKLAERUNG:"
    ),
    QueryType.COMPARE: (
        "Du bist ein Software-Analyst.\n"
        "Vergleiche die folgenden Quellen und identifiziere Gemeinsamkeiten und Unterschiede.\n"
        "Strukturiere deine Antwort klar.\n"
        f"{_NO_HALLUCINATE}\n"
        "KONTEXT:\n{context}\n\n"
        "VERGLEICHSAUFTRAG: {query}\n\n"
        "VERGLEICH:"
    ),
    QueryType.SUMMARIZE: (
        "Du bist ein technischer Redakteur.\n"
        "Erstelle eine praezise Zusammenfassung basierend auf dem Kontext.\n"
        "Fokussiere dich auf die wichtigsten Punkte.\n"
        f"{_NO_HALLUCINATE}\n"
        "KONTEXT:\n{context}\n\n"
        "ZUSAMMENFASSUNGSAUFTRAG: {query}\n\n"
        "ZUSAMMENFASSUNG:"
    ),
    QueryType.GAP_CHECK: (
        "Du bist ein Software-Qualitaetsanalyst.\n"
        "Pruefe ob die im Kontext beschriebene Funktionalitaet dokumentiert ist.\n"
        "Identifiziere fehlende oder unvollstaendige Dokumentation.\n"
        f"{_NO_HALLUCINATE}\n"
        "KONTEXT:\n{context}\n\n"
        "PRUEFAUFTRAG: {query}\n\n"
        "ANALYSE:"
    ),
}

_SYS_NO_HALLUCINATE = " Erfinde KEINE URLs oder Links — verwende nur solche die woertlich im Kontext stehen."

SYSTEM_MESSAGES: dict[QueryType, str] = {
    QueryType.SEARCH: "Du bist ein hilfreicher Assistent fuer Software-Dokumentation. Antworte praezise und referenziere Quellen." + _SYS_NO_HALLUCINATE,
    QueryType.EXPLAIN: "Du bist ein erfahrener Entwickler. Erklaere Code und Konzepte verstaendlich." + _SYS_NO_HALLUCINATE,
    QueryType.COMPARE: "Du bist ein Analyst. Vergleiche Quellen strukturiert und identifiziere Unterschiede." + _SYS_NO_HALLUCINATE,
    QueryType.SUMMARIZE: "Du bist ein technischer Redakteur. Erstelle praezise Zusammenfassungen." + _SYS_NO_HALLUCINATE,
    QueryType.GAP_CHECK: "Du bist ein Qualitaetsanalyst. Identifiziere Dokumentationsluecken.",
}

MAX_CHAT_HISTORY = 6  # Last 6 messages = 3 exchanges


class PromptManager:
    """Build prompts and chat messages from templates."""

    @staticmethod
    def build_prompt(query_type: QueryType, query: str, context: str) -> str:
        """Render a prompt template with query and context."""
        template = TEMPLATES[query_type]
        return template.format(query=query, context=context)

    @staticmethod
    def build_chat_messages(
        query_type: QueryType,
        query: str,
        context: str,
        chat_history: list[dict] | None = None,
    ) -> list[dict]:
        """Build chat messages with system prompt, history, and current query."""
        messages = [
            {"role": "system", "content": SYSTEM_MESSAGES[query_type]},
        ]

        if chat_history:
            messages.extend(chat_history[-MAX_CHAT_HISTORY:])

        messages.append({
            "role": "user",
            "content": f"Kontext:\n{context}\n\nFrage: {query}",
        })

        return messages


class ContextBudget:
    """Token budget management for prompt + context + response."""

    def __init__(
        self,
        context_length: int = 8192,
        max_response_tokens: int = 1024,
        prompt_overhead: int = 512,
    ):
        self.context_length = context_length
        self.max_response_tokens = max_response_tokens
        self.prompt_overhead = prompt_overhead

    @property
    def available_context_tokens(self) -> int:
        """Tokens available for retrieved context."""
        return self.context_length - self.max_response_tokens - self.prompt_overhead

    def fit_chunks(self, chunks: list) -> list:
        """Select chunks that fit within the token budget.

        Each chunk must have a `.content` attribute.
        """
        budget = self.available_context_tokens
        selected = []
        used_tokens = 0

        for chunk in chunks:
            chunk_tokens = len(chunk.content) // 4
            if used_tokens + chunk_tokens > budget:
                break
            selected.append(chunk)
            used_tokens += chunk_tokens

        return selected
