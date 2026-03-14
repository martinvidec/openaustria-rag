# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenAustria RAG is a documentation platform that ingests multiple sources (Git repos, Confluence, ZIP uploads) via connectors, indexes them with RAG (Retrieval-Augmented Generation), and identifies gaps/divergences between code and documentation using a local LLM. Two MVP variants exist: a fully local variant (Ollama + 16GB RAM) and a cloud/hybrid variant (API-key-based, provider-flexible).

## Project Status

This project is in the **pre-implementation/specification phase**. No source code exists yet — only concept documents (`docs/MVP_KONZEPT.md`, `docs/MVP_KONZEPT_CLOUD.md`) and detailed technical specifications (`docs/specs/SPEC_01` through `SPEC_06`). Implementation should follow the planned structure in `docs/MVP_KONZEPT.md` Appendix B.

## Planned Tech Stack

- **Language:** Python 3.11+
- **LLM Runtime:** Ollama (Mistral 7B Q4_K_M default)
- **Embeddings:** Nomic Embed Text v1.5 via Ollama
- **RAG Framework:** LlamaIndex 0.11+
- **Vector DB:** ChromaDB 0.5+ (MVP) → Qdrant (Production)
- **Code Parsing:** tree-sitter 0.22+ (Java, Python, TypeScript)
- **Metadata DB:** SQLite
- **API:** FastAPI 0.110+
- **Frontend:** Streamlit 1.35+ (MVP)

## Planned Commands (once implemented)

```bash
# Install
pip install -e ".[dev]"

# Prerequisites
ollama pull mistral
ollama pull nomic-embed-text

# Run frontend
streamlit run src/openaustria_rag/frontend/app.py

# Run tests
pytest tests/
```

## Architecture (6 Layers)

The system is designed as a modular pipeline — specs document exact interfaces:

1. **Connector Layer** (`connectors/`) — Plugin system with `BaseConnector` ABC. Git, ZIP, Confluence connectors yield `RawDocument` generators. New connectors register via `entry_points` in `pyproject.toml`. See SPEC-02.
2. **Ingestion Pipeline** (`ingestion/`) — Processes RawDocuments through: format detection → tree-sitter code parsing → semantic chunking → metadata enrichment → embedding → ChromaDB indexing. See SPEC-03.
3. **Vector Store + Embedding** (`retrieval/`) — ChromaDB with separate collections per `{project_id}_{content_type}`. Nomic Embed Text via Ollama REST API. See SPEC-03/04.
4. **RAG/Query Engine** (`retrieval/`, `llm/`) — Custom QueryEngine with query analysis, embedding, retrieval, re-ranking, context assembly, and LLM generation. Ollama chat/generate API. 5 prompt templates (search, explain, compare, summarize, gap_check). See SPEC-04.
5. **Gap Analysis Engine** (`analysis/`) — Three-stage algorithm: structural extraction (tree-sitter) → matching (name-based + embedding-based) → LLM divergence analysis. Categorizes into: consistent, undocumented, unimplemented, divergent. See SPEC-05.
6. **Frontend + API** (`frontend/`) — Streamlit pages: Projects, Chat, Gap Analysis Dashboard, Sources, Settings. FastAPI REST endpoints. See SPEC-06.

## Key Data Models (SPEC-01)

`Project` → has many `Source` → has many `Document` → has many `Chunk` (ChromaDB) + `CodeElement` (SQLite). Gap analysis produces `GapReport` → has many `GapItem`. All metadata in SQLite (`data/openaustria_rag.db`), vectors in ChromaDB (`data/chromadb/`).

## Language

Documentation and specs are written in German. Code (variable names, comments, docstrings) should be in English. Prompt templates for the LLM are in German (target users are German-speaking).

## Workflow

**IMPORTANT:** At the start of every session, activate the `github-workflow` skill (`.claude/skills/github-workflow/SKILL.md`). This skill manages issue-based development with GitHub Flow:
- Load and present open issues at session start
- Create feature branches per issue (`feature/<number>-<description>`)
- Use Conventional Commits with issue references
- Create pull requests with standardized templates on completion

Every implementation session should work on exactly one GitHub issue.
