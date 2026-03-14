# OpenAustria RAG

Eine Dokumentationsplattform, die verschiedene Quellen (Git-Repos, Confluence, ZIP-Uploads) mittels RAG (Retrieval-Augmented Generation) semantisch durchsuchbar macht und Gaps sowie Divergenzen zwischen Code und Dokumentation automatisch identifiziert.

## Kernfunktionen

- **Cross-Source-Suche** -- Code, Dokumentation und Modelle aus verschiedenen Quellen in einer Plattform durchsuchen
- **Gap-Analyse** -- Automatische Erkennung von undokumentiertem Code, fehlender Implementierung und Divergenzen zwischen Code und Dokumentation
- **Flexible LLM-Anbindung** -- Vollstandig lokal (Ollama) oder uber API-Provider (OpenAI, Anthropic, Google, Mistral)
- **Datenhoheit** -- Lokaler Betrieb auf Hardware mit 16 GB RAM moglich, keine Cloud-Abhangigkeit erforderlich

## Architektur

```
Frontend (Streamlit)  -->  API (FastAPI)
                              |
              +---------------+---------------+
              |               |               |
         RAG/Query       Gap-Analyse     Ingestion
         Engine          Engine          Pipeline
              |                              |
         Vector DB                    Connector Layer
         (ChromaDB)                   (Plugin-System)
                                           |
                              +------+-----+------+
                              |      |            |
                            Git   Confluence    ZIP
                            Repo    API       Upload
```

Das System ist als modulare 6-Schichten-Architektur aufgebaut:

1. **Connector Layer** -- Plugin-System mit `BaseConnector` ABC (Git, ZIP, Confluence)
2. **Ingestion Pipeline** -- Format-Erkennung, tree-sitter Code-Parsing, semantisches Chunking, Embedding
3. **Vector Store** -- ChromaDB mit separaten Collections pro Projekt und Content-Typ
4. **RAG/Query Engine** -- Query-Analyse, Retrieval, Re-Ranking, LLM-Generierung
5. **Gap-Analyse Engine** -- Dreistufig: Strukturextraktion, Matching, LLM-Divergenzanalyse
6. **Frontend + API** -- Streamlit UI mit Chat, Gap-Dashboard, Projektverwaltung, Settings

## MVP-Varianten

| | Lokal | Cloud/Hybrid |
|---|---|---|
| **LLM** | Ollama + Mistral 7B | OpenAI, Anthropic, Google, Mistral, Ollama |
| **Embedding** | Nomic Embed Text (lokal) | OpenAI, Voyage AI, Cohere, Ollama |
| **Hardware** | 16 GB RAM Minimum | 4 GB RAM genuegen |
| **Kosten** | Keine laufenden Kosten | $5-50/Monat (nutzungsabhangig) |
| **Datenhoheit** | 100 % lokal | Abhangig vom Provider |
| **Setup** | ~30 Min | ~5 Min |

Details: [Lokal](docs/MVP_KONZEPT.md) | [Cloud/Hybrid](docs/MVP_KONZEPT_CLOUD.md)

## Tech Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.11+ |
| LLM Runtime | Ollama (lokal) / API-Provider |
| RAG Framework | LlamaIndex 0.11+ |
| Vector DB | ChromaDB 0.5+ (MVP), Qdrant (Production) |
| Code Parsing | tree-sitter 0.22+ |
| Metadaten-DB | SQLite |
| API | FastAPI 0.110+ |
| Frontend | Streamlit 1.35+ |

## Quick Start

### Lokale Variante (Ollama)

```bash
# Ollama installieren
curl -fsSL https://ollama.com/install.sh | sh

# Modelle herunterladen
ollama pull mistral
ollama pull nomic-embed-text

# Dependencies installieren
pip install -e ".[dev]"

# Anwendung starten
streamlit run src/openaustria_rag/frontend/app.py
```

### Cloud/Hybrid-Variante (API-Key)

```bash
# Dependencies installieren
pip install -e ".[dev]"

# API-Key setzen (einen der folgenden)
export OPENAI_API_KEY="sk-..."
# oder
export ANTHROPIC_API_KEY="sk-ant-..."

# Anwendung starten
streamlit run src/openaustria_rag/frontend/app.py

# Im Browser: Settings offnen, Provider und Keys konfigurieren
```

## Projektstruktur

```
openaustria-rag/
├── docs/
│   ├── MVP_KONZEPT.md              # Konzept: Lokale Variante
│   ├── MVP_KONZEPT_CLOUD.md        # Konzept: Cloud/Hybrid-Variante
│   └── specs/                      # Technische Spezifikationen (SPEC-01 bis SPEC-06)
├── src/
│   └── openaustria_rag/
│       ├── config.py               # Konfiguration
│       ├── providers/              # LLM/Embedding/VectorDB Adapter
│       ├── connectors/             # Git, ZIP, Confluence Konnektoren
│       ├── ingestion/              # Parsing, Chunking, Indexierung
│       ├── retrieval/              # Vector Store, Query Engine
│       ├── analysis/               # Gap-Analyse Engine
│       ├── llm/                    # Prompt-Templates
│       └── frontend/               # Streamlit UI
├── tests/
└── pyproject.toml
```

## Spezifikationen

| Spec | Thema |
|---|---|
| [SPEC-01](docs/specs/SPEC_01_DATENMODELL.md) | Datenmodell (Project, Source, Document, Chunk, GapReport) |
| [SPEC-02](docs/specs/SPEC_02_KONNEKTOREN.md) | Konnektor-System und Plugin-Architektur |
| [SPEC-03](docs/specs/SPEC_03_INGESTION_PIPELINE.md) | Ingestion Pipeline (tree-sitter, Chunking, Embedding) |
| [SPEC-04](docs/specs/SPEC_04_RAG_RETRIEVAL.md) | RAG & Retrieval (Query Engine, Ollama, Prompts) |
| [SPEC-05](docs/specs/SPEC_05_GAP_ANALYSE.md) | Gap-Analyse Engine |
| [SPEC-06](docs/specs/SPEC_06_FRONTEND_API.md) | Frontend & API (Streamlit, FastAPI) |

## Status

Dieses Projekt befindet sich in der **Spezifikationsphase**. Die Konzeptdokumente und technischen Spezifikationen sind fertiggestellt, die Implementierung steht noch aus.

## Lizenz

TBD
