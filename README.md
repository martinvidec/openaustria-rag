# OpenAustria RAG

Eine Dokumentationsplattform, die verschiedene Quellen (Git-Repos, Confluence, ZIP-Uploads) mittels RAG (Retrieval-Augmented Generation) semantisch durchsuchbar macht und Gaps sowie Divergenzen zwischen Code und Dokumentation automatisch identifiziert.

## Kernfunktionen

- **Cross-Source-Suche** -- Code, Dokumentation und Konfiguration aus verschiedenen Quellen in einer Plattform durchsuchen
- **Streaming Chat** -- RAG-basierter Chat mit Wort-fuer-Wort-Streaming, Quellenangaben und Performance-Metriken (tok/s)
- **Gap-Analyse** -- Automatische Erkennung von undokumentiertem Code, fehlender Implementierung und Divergenzen zwischen Code und Dokumentation
- **Datenhoheit** -- Vollstaendig lokaler Betrieb mit Ollama auf Hardware mit 16 GB RAM, keine Cloud-Abhaengigkeit

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

1. **Connector Layer** -- Plugin-System mit `BaseConnector` ABC und `entry_points`-Discovery (Git, ZIP, Confluence)
2. **Ingestion Pipeline** -- tree-sitter Code-Parsing (Java/Python/TypeScript), semantisches Chunking, SHA-256 Change Detection, Batch-Embedding
3. **Vector Store** -- ChromaDB mit Cosine-Distance, separaten Collections pro Projekt und Content-Typ
4. **RAG/Query Engine** -- Query-Typ-Erkennung (DE), Multi-Collection-Retrieval, Keyword+Source-Type Reranking, Embedding-Cache, Streaming
5. **Gap-Analyse Engine** -- Dreistufig: Strukturextraktion mit Boilerplate-Filterung, Name+Embedding Matching, optionale LLM-Divergenzanalyse
6. **Frontend + API** -- Streamlit UI (Chat, Gap-Dashboard, Projektverwaltung, Einstellungen) + FastAPI REST Backend mit 20+ Endpoints

## Quick Start

```bash
# 1. Repository klonen
git clone https://github.com/martinvidec/openaustria-rag.git
cd openaustria-rag

# 2. Dependencies installieren
pip install -e ".[dev]"

# 3. Ollama installieren und Modelle herunterladen
brew install ollama          # macOS
brew services start ollama
ollama pull mistral
ollama pull nomic-embed-text

# 4. Backend starten
uvicorn openaustria_rag.main:app --host 0.0.0.0 --port 8000 &

# 5. Frontend starten
streamlit run src/openaustria_rag/frontend/app.py --server.port 8501

# 6. Im Browser oeffnen: http://localhost:8501
```

## Verwendung

1. **Projekt anlegen** -- Auf der Projekte-Seite ein neues Projekt erstellen
2. **Quellen hinzufuegen** -- Git-Repo URL, ZIP-Upload oder Confluence Space verknuepfen
3. **Sync starten** -- Quellen werden indexiert (Code-Parsing, Chunking, Embedding)
4. **Chat nutzen** -- Fragen an die Codebasis stellen, Antworten mit Quellenverweisen erhalten
5. **Gap-Analyse** -- Dokumentationsluecken und Code-Doku-Divergenzen identifizieren

## Tech Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.11+ |
| LLM Runtime | Ollama (Mistral 7B) |
| Embeddings | Nomic Embed Text v1.5 (768 dim) |
| Vector DB | ChromaDB 1.5+ |
| Code Parsing | tree-sitter (Java, Python, TypeScript) |
| Metadaten-DB | SQLite (WAL mode) |
| API | FastAPI |
| Frontend | Streamlit |

## Projektstruktur

```
openaustria-rag/
├── docs/
│   ├── MVP_KONZEPT.md                 # Konzept: Lokale Variante
│   ├── MVP_KONZEPT_CLOUD.md           # Konzept: Cloud/Hybrid-Variante
│   └── specs/                         # Technische Spezifikationen (SPEC-01 bis SPEC-06)
├── src/openaustria_rag/
│   ├── __init__.py                    # Package (v0.1.0)
│   ├── main.py                        # Uvicorn Entry Point
│   ├── config.py                      # Pydantic Settings (YAML + Env)
│   ├── models.py                      # Datenmodelle (14 Dataclasses, 8 Enums)
│   ├── db.py                          # SQLite Persistenz (MetadataDB)
│   ├── connectors/
│   │   ├── base.py                    # BaseConnector ABC, ConnectorRegistry
│   │   ├── git_connector.py           # Git Clone/Pull, Metadaten-Extraktion
│   │   ├── zip_connector.py           # ZIP-Entpackung, Zip-Slip-Schutz
│   │   ├── confluence_connector.py    # REST API v2, HTML->Markdown, Pagination
│   │   └── utils.py                   # FileFilter, LanguageDetector
│   ├── ingestion/
│   │   ├── code_parser.py             # tree-sitter Queries + Regex Fallback
│   │   ├── chunking.py                # Code/Doku/Config Chunking-Strategien
│   │   ├── embedding_service.py       # Ollama Embedding API
│   │   └── pipeline.py                # Ingestion Orchestrator, Change Detection
│   ├── retrieval/
│   │   ├── vector_store.py            # ChromaDB Wrapper
│   │   └── query_engine.py            # RAG Pipeline, Reranking, Cache
│   ├── llm/
│   │   ├── ollama_client.py           # Generate/Chat/Streaming
│   │   └── prompts.py                 # 5 DE Prompt-Templates, ContextBudget
│   ├── analysis/
│   │   ├── gap_analyzer.py            # 3-Stufen Gap-Analyse, Export, False Positives
│   │   └── matching.py                # CamelCase-Split, Fuzzy-Match, Severity
│   └── frontend/
│       ├── api.py                     # FastAPI App Factory (20+ Endpoints)
│       ├── api_client.py              # HTTP Client fuer Backend
│       ├── schemas.py                 # Pydantic Request/Response Models
│       ├── app.py                     # Streamlit Main App
│       ├── pages/
│       │   ├── 01_Projekte.py         # Projektverwaltung CRUD
│       │   ├── 02_Chat.py             # Streaming Chat mit Quellen
│       │   ├── 03_Gap_Analyse.py      # Dashboard mit Filtern und Export
│       │   ├── 04_Quellen.py          # Git/ZIP/Confluence Verwaltung
│       │   └── 05_Einstellungen.py    # Modell-Auswahl, Parameter
│       └── components/
│           ├── chat_message.py        # Chat-Nachricht Renderer
│           └── gap_table.py           # Gap-Tabelle mit Filtern
├── tests/                             # 305 Tests
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_db.py
│   ├── test_api.py
│   ├── test_smoke.py
│   ├── test_connectors/               # Base, Git, ZIP, Confluence
│   ├── test_ingestion/                # CodeParser, Chunking, Embedding, Pipeline
│   ├── test_retrieval/                # VectorStore, QueryEngine
│   ├── test_llm/                      # OllamaClient, Prompts
│   ├── test_analysis/                 # GapAnalyzer, Matching
│   ├── integration/                   # E2E: Connector->Pipeline->Query->Gap
│   └── fixtures/                      # Sample Java/Python/Markdown
└── pyproject.toml
```

## Tests

```bash
# Alle Tests ausfuehren (ohne echtes Ollama -- alles gemockt)
pytest tests/

# Nur Unit Tests
pytest tests/ --ignore=tests/integration

# Nur Integration Tests
pytest tests/integration/ -m integration

# Mit Coverage
pytest tests/ --cov=openaustria_rag
```

## Konfiguration

Konfiguration ueber `config.yaml` oder Umgebungsvariablen (Prefix `OARAG_`):

```yaml
ollama:
  base_url: "http://localhost:11434"
  model: "mistral"
  temperature: 0.1

embedding:
  model: "nomic-embed-text"

chunking:
  code_max_tokens: 2048
  doc_max_tokens: 1024
  doc_overlap_tokens: 128

vector_store:
  persist_path: "data/chromadb"
  distance_metric: "cosine"
```

```bash
# Oder per Environment
export OARAG_OLLAMA__MODEL=llama3
export OARAG_OLLAMA__BASE_URL=http://localhost:11434
```

## API

REST API auf `http://localhost:8000`:

| Methode | Endpoint | Beschreibung |
|---|---|---|
| GET | `/api/health` | Health Check (Ollama, DB) |
| GET/POST | `/api/projects` | Projekte auflisten/erstellen |
| POST | `/api/projects/{id}/sources` | Quelle hinzufuegen |
| POST | `/api/sources/{id}/sync` | Sync starten (Background) |
| POST | `/api/projects/{id}/query` | RAG Query |
| POST | `/api/projects/{id}/query/stream` | Streaming Query (SSE) |
| POST | `/api/projects/{id}/gap-analysis` | Gap-Analyse starten |
| GET | `/api/projects/{id}/gap-analysis/latest` | Letzter Report |

Vollstaendige API-Dokumentation: `http://localhost:8000/docs`

## Spezifikationen

| Spec | Thema |
|---|---|
| [SPEC-01](docs/specs/SPEC_01_DATENMODELL.md) | Datenmodell (Project, Source, Document, Chunk, GapReport) |
| [SPEC-02](docs/specs/SPEC_02_KONNEKTOREN.md) | Konnektor-System und Plugin-Architektur |
| [SPEC-03](docs/specs/SPEC_03_INGESTION_PIPELINE.md) | Ingestion Pipeline (tree-sitter, Chunking, Embedding) |
| [SPEC-04](docs/specs/SPEC_04_RAG_RETRIEVAL.md) | RAG & Retrieval (Query Engine, Ollama, Prompts) |
| [SPEC-05](docs/specs/SPEC_05_GAP_ANALYSE.md) | Gap-Analyse Engine |
| [SPEC-06](docs/specs/SPEC_06_FRONTEND_API.md) | Frontend & API (Streamlit, FastAPI) |

## Hardware-Anforderungen

| | Minimum | Empfohlen |
|---|---|---|
| RAM | 16 GB | 32 GB |
| CPU | 4 Cores | 8 Cores |
| Storage | 20 GB SSD | 50 GB SSD |
| GPU | Nicht erforderlich | Optional (NVIDIA 8 GB+) |

## Lizenz

MIT
