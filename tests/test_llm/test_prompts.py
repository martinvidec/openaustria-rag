"""Tests for prompt templates and context budget (SPEC-04 Section 5)."""

from dataclasses import dataclass

import pytest

from openaustria_rag.llm.prompts import (
    ContextBudget,
    PromptManager,
    QueryType,
    SYSTEM_MESSAGES,
    TEMPLATES,
)


class TestQueryType:
    def test_all_query_types(self):
        assert len(QueryType) == 5
        assert QueryType.SEARCH.value == "search"
        assert QueryType.GAP_CHECK.value == "gap_check"


class TestTemplates:
    def test_all_types_have_templates(self):
        for qt in QueryType:
            assert qt in TEMPLATES

    def test_all_types_have_system_messages(self):
        for qt in QueryType:
            assert qt in SYSTEM_MESSAGES

    def test_templates_are_german(self):
        for qt in QueryType:
            template = TEMPLATES[qt]
            assert "KONTEXT:" in template
            assert "{context}" in template
            assert "{query}" in template

    def test_system_messages_are_german(self):
        for qt in QueryType:
            msg = SYSTEM_MESSAGES[qt]
            assert "Du bist" in msg


class TestPromptManager:
    def test_build_prompt_search(self):
        prompt = PromptManager.build_prompt(
            QueryType.SEARCH, "What is auth?", "Auth uses JWT tokens."
        )
        assert "What is auth?" in prompt
        assert "Auth uses JWT tokens." in prompt
        assert "KONTEXT:" in prompt
        assert "FRAGE:" in prompt
        assert "ANTWORT:" in prompt

    def test_build_prompt_all_types(self):
        for qt in QueryType:
            prompt = PromptManager.build_prompt(qt, "query", "context")
            assert "query" in prompt
            assert "context" in prompt

    def test_build_chat_messages_basic(self):
        msgs = PromptManager.build_chat_messages(
            QueryType.SEARCH, "test query", "test context"
        )
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert "test query" in msgs[-1]["content"]
        assert "test context" in msgs[-1]["content"]

    def test_build_chat_messages_with_history(self):
        history = [
            {"role": "user", "content": "prev question"},
            {"role": "assistant", "content": "prev answer"},
        ]
        msgs = PromptManager.build_chat_messages(
            QueryType.SEARCH, "new question", "ctx", chat_history=history
        )
        assert len(msgs) == 4  # system + 2 history + current
        assert msgs[1]["content"] == "prev question"
        assert msgs[2]["content"] == "prev answer"

    def test_build_chat_messages_truncates_history(self):
        history = [
            {"role": "user", "content": f"q{i}"}
            for i in range(10)
        ]
        msgs = PromptManager.build_chat_messages(
            QueryType.SEARCH, "latest", "ctx", chat_history=history
        )
        # system + 6 history + current = 8
        assert len(msgs) == 8

    def test_build_chat_messages_no_history(self):
        msgs = PromptManager.build_chat_messages(
            QueryType.EXPLAIN, "explain this", "code here"
        )
        assert len(msgs) == 2  # system + current


class TestContextBudget:
    def test_default_available_tokens(self):
        budget = ContextBudget()
        # 8192 - 1024 - 512 = 6656
        assert budget.available_context_tokens == 6656

    def test_custom_budget(self):
        budget = ContextBudget(
            context_length=4096, max_response_tokens=1024, prompt_overhead=256
        )
        assert budget.available_context_tokens == 2816

    def test_fit_chunks_within_budget(self):
        @dataclass
        class FakeChunk:
            content: str

        budget = ContextBudget()
        chunks = [FakeChunk(content="x" * 400) for _ in range(100)]
        selected = budget.fit_chunks(chunks)
        total_tokens = sum(len(c.content) // 4 for c in selected)
        assert total_tokens <= budget.available_context_tokens
        assert len(selected) < 100

    def test_fit_chunks_all_fit(self):
        @dataclass
        class FakeChunk:
            content: str

        budget = ContextBudget()
        chunks = [FakeChunk(content="short")]
        selected = budget.fit_chunks(chunks)
        assert len(selected) == 1

    def test_fit_chunks_empty(self):
        budget = ContextBudget()
        assert budget.fit_chunks([]) == []
