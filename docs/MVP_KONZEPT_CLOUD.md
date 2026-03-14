# MVP Konzeptdokument: OpenAustria RAG Dokumentationsplattform (Cloud/Hybrid)

**Version:** 1.0
**Datum:** 2026-03-14
**Status:** Entwurf
**Variante:** API-Key-basiert -- LLM und Services nach User-Praferenz

---

## Inhaltsverzeichnis

1. [Executive Summary & Vision](#1-executive-summary--vision)
2. [Technologie-Evaluation](#2-technologie-evaluation)
3. [Architektur](#3-architektur)
4. [Konnektoren](#4-konnektoren)
5. [Gap-Analyse Ansatz](#5-gap-analyse-ansatz)
6. [Ressourcen-Anforderungen & Benchmarks](#6-ressourcen-anforderungen--benchmarks)
7. [MVP Scope & Roadmap](#7-mvp-scope--roadmap)
8. [Risiken & Mitigationen](#8-risiken--mitigationen)

---

## 1. Executive Summary & Vision

### Problemstellung

Software-Dokumentation entsteht verteilt ueber viele Quellen: Confluence, Enterprise-Architect-Modelle, Javadoc, Code-Kommentare, Spezifikationen. Diese Quellen sind oft inkonsistent, veraltet oder widerspruchlich. Das manuelle Zusammensuchen und Abgleichen kostet erhebliche Zeit.

### Kernidee -- API-Key-basierter Ansatz

Im Unterschied zur lokalen Variante (siehe `MVP_KONZEPT.md`) setzt dieses Konzept auf **maximale Flexibilitat bei der Wahl der LLM- und RAG-Infrastruktur**:

- **User wahlt seinen LLM-Provider** (OpenAI, Anthropic, Google, Mistral, Ollama lokal)
- **User wahlt seine Embedding-Infrastruktur** (OpenAI Embeddings, Cohere, Voyage AI, oder lokal)
- **User wahlt seine Vector-DB** (Managed: Pinecone, Weaviate Cloud; Self-hosted: Qdrant, ChromaDB)
- **Konfiguration uber API-Keys** -- ein einheitliches Settings-Interface

### Warum diese Variante?

| Kriterium | Lokal (MVP_KONZEPT.md) | Cloud/Hybrid (dieses Dokument) |
|---|---|---|
| Hardware-Anforderungen | 16 GB RAM Minimum | Beliebig (auch Laptop mit 8 GB) |
| LLM-Qualitat | Limitiert durch lokale Modelle | State-of-the-Art (GPT-4o, Claude, etc.) |
| Datenhoheit | 100 % lokal | Abhaengig vom Provider |
| Kosten (laufend) | Keine (nur Strom) | API-Kosten pro Token |
| Setup-Aufwand | Hoch (Ollama, Modelle, etc.) | Niedrig (API-Key eintragen) |
| Skalierung | Durch Hardware begrenzt | Quasi unbegrenzt |
| Offline-Fahigkeit | Ja | Nein (ausser Ollama-Fallback) |

### Zielgruppe

- **Teams ohne GPU-Hardware**, die trotzdem leistungsfähige RAG-Suche wollen
- **Unternehmen mit bestehenden API-Vertragen** (OpenAI Enterprise, Azure OpenAI, AWS Bedrock)
- **Evaluierer**, die schnell verschiedene LLMs vergleichen mochten
- **Hybrid-Nutzer**, die sensible Daten lokal und unkritische Daten uber APIs verarbeiten wollen

---

## 2. Technologie-Evaluation

### 2.1 LLM-Provider (nach User-Praferenz)

Der User konfiguriert seinen bevorzugten LLM-Provider uber ein einheitliches Settings-Interface. Die Plattform abstrahiert die Provider-spezifischen APIs uber eine gemeinsame Schnittstelle.

#### Unterstuetzte Provider

| Provider | Modelle | API-Key | Besonderheiten |
|---|---|---|---|
| **OpenAI** | GPT-4o, GPT-4o-mini, o3-mini | `OPENAI_API_KEY` | Hoechste Qualitat, breite Verfuegbarkeit |
| **Anthropic** | Claude Sonnet 4, Claude Haiku | `ANTHROPIC_API_KEY` | Grosses Kontextfenster (200k), starke Analyse |
| **Google** | Gemini 2.0 Flash, Gemini 2.5 Pro | `GOOGLE_API_KEY` | Grosses Kontextfenster, kostenguenstiges Flash-Modell |
| **Mistral** | Mistral Large, Mistral Small | `MISTRAL_API_KEY` | EU-Datenresidenz (Frankreich), gutes Deutsch |
| **Azure OpenAI** | GPT-4o (Azure-hosted) | `AZURE_OPENAI_*` | Enterprise-Compliance, VNet-Integration |
| **AWS Bedrock** | Claude, Llama, Mistral | AWS Credentials | AWS-Okosystem-Integration |
| **Ollama (lokal)** | Mistral 7B, Llama 3.1, Phi-3 | Kein Key noetig | Offline, Datenhoheit, keine Kosten |

#### Empfohlene Konfigurationen

| Use Case | Empfohlener Provider | Modell | Kosten/1M Tokens |
|---|---|---|---|
| **Beste Qualitaet** | Anthropic | Claude Sonnet 4 | ~$3 / $15 |
| **Bestes Preis-Leistung** | OpenAI | GPT-4o-mini | ~$0.15 / $0.60 |
| **EU-Datenresidenz** | Mistral | Mistral Large | ~$2 / $6 |
| **Maximale Datenhoheit** | Ollama (lokal) | Mistral 7B Q4 | Kostenlos |
| **Grosser Kontext** | Google | Gemini 2.0 Flash | ~$0.10 / $0.40 |
| **Enterprise/Compliance** | Azure OpenAI | GPT-4o | Vertragsabhaengig |

### 2.2 Embedding-Provider

| Provider | Modell | Dimensionen | Kosten/1M Tokens | Qualitaet |
|---|---|---|---|---|
| **OpenAI** | text-embedding-3-large | 3072 (konfigurierbar) | ~$0.13 | Sehr gut |
| **OpenAI** | text-embedding-3-small | 1536 | ~$0.02 | Gut |
| **Cohere** | embed-v4.0 | 1024 | ~$0.10 | Sehr gut (multilingual) |
| **Voyage AI** | voyage-code-3 | 1024 | ~$0.06 | Exzellent fuer Code |
| **Google** | text-embedding-004 | 768 | ~$0.025 | Gut |
| **Ollama (lokal)** | nomic-embed-text | 768 | Kostenlos | Gut |

**Empfehlung:**
- **Code-lastige Projekte:** Voyage AI `voyage-code-3` (optimiert fuer Code-Semantik)
- **Gemischte Projekte:** OpenAI `text-embedding-3-large` (gute Allround-Qualitaet)
- **Budget/Offline:** Ollama + `nomic-embed-text`

### 2.3 Vector Database

| Anbieter | Typ | API-Key / Config | Eignung |
|---|---|---|---|
| **Pinecone** | Managed Cloud | `PINECONE_API_KEY` | Einfachstes Setup, serverless |
| **Weaviate Cloud** | Managed Cloud | `WEAVIATE_API_KEY` + URL | Hybrid-Suche (Vektor + Keyword) |
| **Qdrant Cloud** | Managed Cloud | `QDRANT_API_KEY` + URL | Gutes Filtern, EU-Hosting |
| **Qdrant** | Self-hosted | URL (kein Key) | Volle Kontrolle, Docker |
| **ChromaDB** | Eingebettet | Kein Key | Zero-Config, MVP |

**Empfehlung:** ChromaDB fuer MVP-Start → Qdrant Cloud oder Pinecone fuer Production.

### 2.4 RAG-Framework

**Empfehlung: LlamaIndex** (wie in der lokalen Variante)

Zusaetzliche Gruende fuer die Cloud-Variante:
- Eingebaute Abstraktionen fuer alle genannten LLM-Provider (`OpenAI`, `Anthropic`, `Gemini`, `MistralAI`, `Ollama`)
- Eingebaute Embedding-Abstraktionen fuer alle genannten Provider
- Eingebaute VectorStore-Integrationen (Pinecone, Qdrant, Weaviate, Chroma)
- **Provider-Wechsel erfordert nur Konfigurationsaenderung**, kein Code-Umbau

### 2.5 Code-Parsing

Identisch zur lokalen Variante: **tree-sitter** fuer multi-language AST-Parsing.

---

## 3. Architektur

### 3.1 Architekturueberblick

```
+------------------------------------------------------------------+
|                         Frontend Layer                            |
|  +-------------------+  +-----------------+  +-----------------+ |
|  |  Chat Interface   |  |  Gap-Analyse    |  |  Settings /     | |
|  |  (Streamlit)      |  |  Dashboard      |  |  Provider-Mgmt  | |
|  +-------------------+  +-----------------+  +-----------------+ |
+------------------------------------------------------------------+
                              |
+------------------------------------------------------------------+
|                       API / Orchestration                         |
|  +-------------------+  +---------------------+                  |
|  |  FastAPI Backend  |  |  Query Router       |                  |
|  +-------------------+  +---------------------+                  |
+------------------------------------------------------------------+
                              |
+------------------+--------------------+--------------------------+
|                  |                    |                           |
v                  v                    v                           v
+-----------+  +------------+  +--------------+  +-----------------+
| Provider  |  | Retrieval  |  | Gap Analysis |  | Ingestion       |
| Abstrac-  |  | Layer      |  | Engine       |  | Pipeline        |
| tion      |  | (LlamaIdx) |  |              |  |                 |
| Layer     |  +------------+  +--------------+  +-----------------+
+-----------+       |                                    |
| LLM       |  +------------+                  +-----------------+
| Adapter   |  | Vector DB  |                  | Connector Layer |
| Embedding |  | Adapter    |                  | (Plugin-System) |
| Adapter   |  +------------+                  +-----------------+
+-----------+       |                                   |
      |        +----+----+              +------+--------+--------+
      |        |    |    |              |      |        |        |
      v        v    v    v             Git  Conflu-   ZIP    Enterprise
  +------+  Chro- Pine- Qdrant        Repo  ence   Upload  Architect
  | OpenAI| maDB  cone  Cloud
  | Anthr.|
  | Google|
  | Mistr.|
  | Ollama|
  +------+
```

### 3.2 Provider Abstraction Layer (Kernkomponente)

Die zentrale Neuerung gegenueber der lokalen Variante ist die **Provider Abstraction Layer**. Sie entkoppelt die Anwendungslogik von konkreten API-Providern.

#### LLM-Adapter Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class LLMProvider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    MISTRAL = "mistral"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"

@dataclass
class LLMConfig:
    provider: LLMProvider
    api_key: str | None           # None fuer Ollama
    model: str                     # z.B. "gpt-4o-mini", "claude-sonnet-4-20250514"
    base_url: str | None = None   # Custom Endpoint (Azure, Self-hosted)
    temperature: float = 0.1
    max_tokens: int = 2048

class LLMAdapter(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        """Chat-Completion ausfuehren."""

    @abstractmethod
    def stream(self, messages: list[dict], **kwargs):
        """Streaming Chat-Completion."""

    @abstractmethod
    def get_token_count(self, text: str) -> int:
        """Token-Zaehlung fuer das konfigurierte Modell."""
```

#### Embedding-Adapter Interface

```python
class EmbeddingProvider(Enum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    GOOGLE = "google"
    OLLAMA = "ollama"

@dataclass
class EmbeddingConfig:
    provider: EmbeddingProvider
    api_key: str | None
    model: str                     # z.B. "text-embedding-3-large"
    dimensions: int | None = None  # Optional: Dimensionen reduzieren

class EmbeddingAdapter(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Batch-Embedding fuer Dokumente."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Einzelnes Query-Embedding."""
```

#### VectorDB-Adapter Interface

```python
class VectorDBProvider(Enum):
    CHROMADB = "chromadb"
    PINECONE = "pinecone"
    QDRANT = "qdrant"
    WEAVIATE = "weaviate"

@dataclass
class VectorDBConfig:
    provider: VectorDBProvider
    api_key: str | None = None
    url: str | None = None         # Fuer Managed/Self-hosted
    collection_prefix: str = "oarag"

class VectorDBAdapter(ABC):
    @abstractmethod
    def upsert(self, documents: list, embeddings: list, metadata: list) -> None:
        """Dokumente indexieren."""

    @abstractmethod
    def query(self, embedding: list[float], top_k: int, filters: dict) -> list:
        """Aehnliche Dokumente suchen."""

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """Dokumente loeschen."""
```

### 3.3 Settings & Key Management

#### Konfigurationsstruktur

```yaml
# config.yaml -- Beispielkonfiguration
llm:
  provider: "anthropic"
  model: "claude-sonnet-4-20250514"
  # api_key wird aus Env-Variable geladen: ANTHROPIC_API_KEY
  temperature: 0.1
  max_tokens: 2048

embedding:
  provider: "openai"
  model: "text-embedding-3-large"
  dimensions: 1024              # Reduzierte Dimensionen fuer Speicher
  # api_key wird aus Env-Variable geladen: OPENAI_API_KEY

vector_db:
  provider: "chromadb"
  path: "./data/chromadb"       # Lokaler Pfad fuer ChromaDB

# Alternative: Qdrant Cloud
# vector_db:
#   provider: "qdrant"
#   url: "https://xxx.qdrant.io:6333"
#   api_key aus Env: QDRANT_API_KEY
```

#### API-Key-Verwaltung im Frontend

```
+-------------------------------------------------------+
|  Einstellungen                                         |
+-------------------------------------------------------+
|                                                        |
|  LLM Provider:  [v Anthropic       ]                  |
|  Modell:        [v Claude Sonnet 4  ]                  |
|  API Key:       [*********************] [Test]         |
|  Status:        (gruener Punkt) Verbunden              |
|                                                        |
|  ---------------------------------------------------- |
|                                                        |
|  Embedding Provider:  [v OpenAI            ]          |
|  Modell:              [v text-embedding-3-large ]     |
|  API Key:             [*********************] [Test]   |
|  Dimensionen:         [1024              ]             |
|  Status:              (gruener Punkt) Verbunden        |
|                                                        |
|  ---------------------------------------------------- |
|                                                        |
|  Vector Database:  [v ChromaDB (lokal)    ]           |
|  Pfad:             [./data/chromadb       ]            |
|  Status:           (gruener Punkt) Bereit              |
|                                                        |
|  [Konfiguration speichern]  [Verbindung testen]       |
+-------------------------------------------------------+
```

#### Sicherheit der API-Keys

| Massnahme | Umsetzung |
|---|---|
| **Speicherung** | Keys werden verschluesselt in lokaler SQLite-DB gespeichert (via `cryptography.fernet`) |
| **Environment Variables** | Alternativ ueber Env-Variablen (`OPENAI_API_KEY`, etc.) |
| **Kein Logging** | API-Keys werden nie in Logs geschrieben |
| **Frontend-Maskierung** | Keys werden im UI nur maskiert angezeigt (`sk-...abc`) |
| **Validierung** | "Test"-Button prueft Key-Gueltigkeit vor dem Speichern |

### 3.4 Provider-Factory (LlamaIndex Integration)

```python
from llama_index.llms.openai import OpenAI
from llama_index.llms.anthropic import Anthropic
from llama_index.llms.gemini import Gemini
from llama_index.llms.mistralai import MistralAI
from llama_index.llms.ollama import Ollama

def create_llm(config: LLMConfig):
    """Erstellt LlamaIndex-LLM basierend auf User-Konfiguration."""
    match config.provider:
        case LLMProvider.OPENAI:
            return OpenAI(
                model=config.model,
                api_key=config.api_key,
                temperature=config.temperature,
            )
        case LLMProvider.ANTHROPIC:
            return Anthropic(
                model=config.model,
                api_key=config.api_key,
                temperature=config.temperature,
            )
        case LLMProvider.GOOGLE:
            return Gemini(
                model=config.model,
                api_key=config.api_key,
            )
        case LLMProvider.MISTRAL:
            return MistralAI(
                model=config.model,
                api_key=config.api_key,
            )
        case LLMProvider.OLLAMA:
            return Ollama(
                model=config.model,
                base_url=config.base_url or "http://localhost:11434",
            )
```

### 3.5 Restliche Schichten

Die folgenden Schichten sind weitgehend identisch zur lokalen Variante (`MVP_KONZEPT.md`):

- **Connector Layer** -- Gleiches Plugin-Interface, gleiche Konnektoren
- **Processing / Ingestion Pipeline** -- Gleiches Chunking und Parsing
- **Gap Analysis Engine** -- Gleicher dreistufiger Ansatz
- **Frontend** -- Streamlit, erweitert um Settings/Provider-Management

---

## 4. Konnektoren

### 4.1 MVP-Konnektoren

Identisch zur lokalen Variante:

- **Git-Repo URL Konnektor** -- Clone + tree-sitter Parsing
- **ZIP-Upload Konnektor** -- Entpacken + Parsing
- **Confluence API Konnektor** -- REST API + HTML-zu-Markdown

Alle Konnektoren nutzen das gleiche `BaseConnector`-Interface. Der Unterschied liegt nur darin, welcher LLM/Embedding-Provider fuer die Indexierung verwendet wird -- das wird ueber die Provider Abstraction Layer gesteuert.

### 4.2 Confluence-Konnektor: API-Key-Handling

Der Confluence-Konnektor ist ein gutes Beispiel fuer konsistentes Key-Management:

```yaml
connectors:
  confluence:
    base_url: "https://mycompany.atlassian.net"
    space_key: "PROJ"
    # Credentials aus Env oder verschluesselt gespeichert:
    # CONFLUENCE_EMAIL + CONFLUENCE_API_TOKEN
```

Das Frontend bietet die gleiche Key-Verwaltung wie fuer LLM-Provider:

```
Confluence Konnektor
  URL:        [https://mycompany.atlassian.net]
  Space:      [PROJ                           ]
  E-Mail:     [user@company.com               ]
  API Token:  [*********************] [Test]
  Status:     (gruener Punkt) Verbunden - 142 Seiten gefunden
```

### 4.3 Future-Konnektoren

Identisch zur lokalen Variante, plus:

| Konnektor | Zusaetzliche Keys |
|---|---|
| **Jira** | `JIRA_API_TOKEN` (gleicher Atlassian-Token wie Confluence) |
| **SharePoint** | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` |
| **GitHub API** | `GITHUB_TOKEN` (fuer private Repos) |

---

## 5. Gap-Analyse Ansatz

### 5.1 Ueberblick

Der dreistufige Ansatz ist identisch zur lokalen Variante:

1. **Strukturelle Extraktion** (tree-sitter + Doku-Parsing)
2. **Matching-Algorithmus** (Namensbasiert + Embedding-basiert)
3. **LLM-basierte semantische Analyse** (Divergenz-Bewertung)

### 5.2 Vorteile des API-Key-Ansatzes fuer Gap-Analyse

| Aspekt | Lokal | Cloud/API |
|---|---|---|
| **Analyse-Qualitaet** | Begrenzt durch 7B-Modell | State-of-the-Art (GPT-4o, Claude) |
| **Kontextfenster** | 8k-32k Tokens | 128k-200k Tokens |
| **Batch-Analyse** | Langsam (CPU-Inference) | Schnell (API-Parallelisierung) |
| **Kosten pro Analyse** | Keine | ~$0.50-$5.00 pro Projekt-Scan |

### 5.3 Hybrid-Strategie fuer Gap-Analyse

Die Plattform unterstuetzt einen **kostenoptimierten Hybrid-Ansatz**:

```
Stufe 1: Strukturelle Extraktion
  → Kein LLM noetig (tree-sitter + Algorithmen)
  → Kosten: $0

Stufe 2: Embedding-basiertes Matching
  → Guenstiges Embedding-Modell (text-embedding-3-small: ~$0.02/1M Tokens)
  → Kosten: ~$0.01-0.05 pro Projekt-Scan

Stufe 3: LLM-Analyse (nur fuer Divergenzen)
  → Nur die ~5-15% unklaren Faelle werden ans LLM geschickt
  → Teures Modell nur wo noetig
  → Kosten: ~$0.10-2.00 pro Projekt-Scan
```

**Kostenkontrolle im Frontend:**

```
Gap-Analyse Einstellungen
  Analyse-Tiefe:       [v Standard           ]
    - Schnell:         Nur Stufe 1+2 (~$0.05)
    - Standard:        Stufe 1+2+3, Top-50 Gaps (~$0.50)
    - Gruendlich:      Stufe 1+2+3, alle Gaps (~$2-5)
  Budget-Limit:        [$5.00 pro Scan       ]
  LLM fuer Analyse:    [v GPT-4o-mini (guenstig)]
```

### 5.4 Multi-Modell-Vergleich fuer Gap-Analyse

Ein besonderes Feature der API-Key-Variante: **Gap-Analyse mit mehreren LLMs parallel**, um die Ergebnisqualitaet zu validieren.

```
Code-Chunk + Doku-Chunk
        |
        +--------+-----------+
        |        |           |
        v        v           v
    GPT-4o   Claude     Mistral Large
        |        |           |
        v        v           v
    Ergebnis  Ergebnis   Ergebnis
        |        |           |
        +--------+-----------+
                 |
                 v
          Konsens-Bewertung
    (Mehrheitsentscheid + Confidence)
```

---

## 6. Ressourcen-Anforderungen & Benchmarks

### 6.1 Hardware-Anforderungen

#### Minimalkonfiguration (API-only)

| Komponente | Anforderung |
|---|---|
| **RAM** | 4 GB genuegen |
| **CPU** | 2 Cores |
| **Storage** | 5 GB SSD (Anwendung + ChromaDB) |
| **GPU** | Nicht erforderlich |
| **Internet** | Erforderlich fuer API-Aufrufe |

Da LLM und Embedding ueber APIs laufen, sind die lokalen Hardware-Anforderungen minimal. Die Anwendung selbst benoetigt nur Speicher fuer ChromaDB und die Python-Runtime.

#### Hybrid-Konfiguration (API + lokaler Fallback)

| Komponente | Anforderung |
|---|---|
| **RAM** | 16 GB (fuer Ollama-Fallback) |
| **CPU** | 4 Cores |
| **Storage** | 20 GB SSD |
| **GPU** | Optional |

### 6.2 Kostenvergleich nach Provider

#### Szenario: Mittelgrosses Projekt (500 Dateien, ~15.000 Chunks)

| Schritt | OpenAI (guenstig) | OpenAI (premium) | Anthropic | Ollama (lokal) |
|---|---|---|---|---|
| **Embedding** (15k Chunks) | $0.03 (3-small) | $0.20 (3-large) | -- | $0.00 |
| **Ingestion-Zusammenfassungen** | $0.50 (4o-mini) | $2.00 (4o) | $3.00 (Sonnet) | $0.00 |
| **50 Chat-Queries** | $0.25 (4o-mini) | $2.50 (4o) | $3.75 (Sonnet) | $0.00 |
| **1x Gap-Analyse** | $0.50 (4o-mini) | $3.00 (4o) | $5.00 (Sonnet) | $0.00 |
| **Gesamt (einmalig)** | **~$1.28** | **~$7.70** | **~$11.75** | **$0.00** |
| **Monatlich (10 Queries/Tag)** | **~$5** | **~$30** | **~$45** | **$0.00** |

#### Kostenoptimierung -- Tiered-Modell-Strategie

```yaml
# Empfohlene kostenoptimierte Konfiguration:
cost_optimization:
  embedding: "openai/text-embedding-3-small"    # Guenstigste Option
  chat_simple: "openai/gpt-4o-mini"             # Einfache Fragen
  chat_complex: "anthropic/claude-sonnet-4"     # Komplexe Analyse
  gap_analysis: "openai/gpt-4o-mini"            # Bulk-Analyse
  gap_validation: "anthropic/claude-sonnet-4"   # Nur fuer kritische Gaps
```

Die Plattform kann **automatisch das kostenguenstigere Modell fuer einfache Aufgaben** und das leistungsfaehigere Modell fuer komplexe Aufgaben verwenden (Query-Routing).

### 6.3 Performance-Metriken (API-basiert)

#### Latenz

| Operation | API (typisch) | Lokal (Ollama, CPU) |
|---|---|---|
| Chat-Antwort (200 Tokens) | 2-4 Sek | 17-25 Sek |
| Embedding (1 Chunk) | < 100 ms | ~200-500 ms |
| Embedding (100 Chunks, Batch) | < 1 Sek | ~20-30 Sek |
| Gap-Analyse (50 Paare) | 30-60 Sek (parallel) | 15-30 Min (seriell) |

#### Durchsatz

| Operation | API | Lokal |
|---|---|---|
| Embedding (Chunks/Min) | ~10.000+ | ~200-800 |
| LLM-Analyse (Paare/Min) | ~50-100 (parallel) | ~2-3 |
| Full Re-Index (15k Chunks) | ~2-5 Min | ~30-90 Min |

### 6.4 Rate Limits und Throttling

| Provider | Rate Limit (typisch) | Mitigation |
|---|---|---|
| OpenAI | 10.000 RPM (Tier 3) | Exponentielles Backoff, Batch-API |
| Anthropic | 4.000 RPM | Request-Queuing, Prioritaeten |
| Google | 1.500 RPM | Throttling, Caching |
| Mistral | 5 RPS | Serielles Processing |

Die Plattform implementiert:
- **Automatisches Rate-Limit-Handling** mit exponentiellem Backoff
- **Request-Caching** (identische Queries werden nicht doppelt gesendet)
- **Batch-APIs** wo verfuegbar (OpenAI Batch API fuer Bulk-Embedding)
- **Budget-Alerts** wenn konfiguriertes Kostenlimit erreicht wird

---

## 7. MVP Scope & Roadmap

### 7.1 MVP Scope (Phase 1)

**Ziel:** Funktionierender Prototyp in 8-12 Wochen.

#### In Scope

- [x] Provider Abstraction Layer (LLM, Embedding, VectorDB)
- [x] Settings UI fuer API-Key-Verwaltung
- [x] Unterstuetzung fuer: OpenAI, Anthropic, Ollama (LLM)
- [x] Unterstuetzung fuer: OpenAI, Ollama (Embeddings)
- [x] ChromaDB als Standard-VectorDB
- [x] Git-Repo Konnektor
- [x] ZIP-Upload Konnektor
- [x] Confluence API Konnektor
- [x] tree-sitter Code-Parsing (Java, Python, TypeScript)
- [x] Chat-Interface (Streamlit)
- [x] Basis-Gap-Analyse
- [x] Kostentracking (Token-Zaehler pro Provider)
- [x] API-Key-Validierung und Verbindungstest

#### Out of Scope (MVP)

- Google, Mistral, Azure als LLM-Provider (einfach nachruestbar)
- Cohere, Voyage AI als Embedding-Provider
- Pinecone, Qdrant Cloud, Weaviate als VectorDB
- Multi-Modell Gap-Analyse (Konsens-Bewertung)
- Query-Routing (automatische Modell-Wahl)
- Enterprise Architect / Javadoc Konnektoren
- Multi-User / Authentifizierung
- React/Next.js Frontend

### 7.2 Roadmap

```
Phase 1: MVP                           Phase 2: Provider-Erweiterung
(Wochen 1-12)                          (Wochen 13-20)
+----------------------------------+   +----------------------------------+
| - Provider Abstraction Layer     |   | - Google, Mistral, Azure Provider|
| - OpenAI + Anthropic + Ollama   |   | - Voyage AI, Cohere Embeddings   |
| - Settings UI + Key Management  |   | - Pinecone + Qdrant Cloud        |
| - Git/ZIP/Confluence Konnektoren |   | - Query-Routing (auto Modell)   |
| - ChromaDB + Streamlit Chat     |   | - Kostenoptimierung (Tiered)     |
| - Basis-Gap-Analyse             |   | - Multi-Modell Gap-Vergleich     |
| - Token-Zaehler / Kosten        |   | - Budget-Alerts                  |
+----------------------------------+   +----------------------------------+

Phase 3: Production                     Phase 4: Enterprise
(Wochen 21-36)                          (Wochen 37+)
+----------------------------------+   +----------------------------------+
| - React/Next.js Frontend         |   | - Multi-User + RBAC              |
| - FastAPI Backend                |   | - SSO / LDAP Integration         |
| - EA + Javadoc Konnektoren       |   | - Team-weite API-Key-Verwaltung  |
| - CI/CD Integration              |   | - Audit-Logging + Compliance     |
| - PDF-Report-Export              |   | - Kubernetes Deployment          |
| - Trend-Analyse Dashboard        |   | - Custom Fine-Tuning Pipeline    |
+----------------------------------+   +----------------------------------+
```

### 7.3 MVP Meilensteine

| Woche | Meilenstein | Deliverable |
|---|---|---|
| 1-2 | Projekt-Setup + Provider Layer | Adapter-Interfaces, Factory, Config-System |
| 3-4 | Settings UI + Key Management | Streamlit-Settings, Key-Validierung, Encryption |
| 5-6 | Connector Layer + Ingestion | Git/ZIP-Konnektor, tree-sitter, Chunking |
| 7-8 | Embedding + VectorDB | ChromaDB-Integration, Provider-agnostisches Embedding |
| 9-10 | Chat + Confluence Konnektor | RAG-Chat, Confluence-Integration |
| 11-12 | Gap-Analyse + Kosten-Tracking | Gap-Analyse, Token-Counter, Testing |

---

## 8. Risiken & Mitigationen

### 8.1 Technische Risiken

| # | Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|---|
| T1 | **API-Ausfall eines Providers** -- Plattform nicht nutzbar | Niedrig | Hoch | Fallback-Provider konfigurierbar; Ollama als Offline-Backup |
| T2 | **API-Aenderungen / Breaking Changes** -- Provider aendert API | Mittel | Mittel | LlamaIndex abstrahiert APIs; Provider-Version pinnen; Adapter-Pattern isoliert Aenderungen |
| T3 | **Rate Limits erreicht** -- Ingestion/Analyse blockiert | Mittel | Mittel | Exponentielles Backoff; Batch-APIs; Caching; User-Warnung |
| T4 | **Embedding-Inkompatibilitaet bei Provider-Wechsel** -- Vektoren passen nicht | Hoch | Hoch | Warnung bei Provider-Wechsel; Re-Indexierung erforderlich; Migration-Tool bereitstellen |
| T5 | **Abstraktion zu generisch** -- Provider-spezifische Features nicht nutzbar | Mittel | Niedrig | Provider-spezifische Erweiterungspunkte im Adapter; Sinnvolle Defaults |

### 8.2 Kosten- und Datenschutz-Risiken

| # | Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|---|
| K1 | **Unkontrollierte API-Kosten** -- User vergisst Budget-Limit | Mittel | Mittel | Standard-Budget-Limit; Token-Zaehler im UI; Warnungen bei Schwellenwerten |
| K2 | **Sensible Daten an Cloud-APIs gesendet** -- Compliance-Verstoss | Mittel | Hoch | Klare Warnung im UI; Ollama-Fallback fuer sensible Projekte; Datenklassifizierung pro Projekt |
| K3 | **API-Key-Leak** -- Keys werden kompromittiert | Niedrig | Hoch | Verschluesselte Speicherung; keine Keys in Logs; Env-Variablen bevorzugt |
| K4 | **Provider stellt Modell ein** -- z.B. altes GPT-Modell wird deprecated | Mittel | Niedrig | Modell-Auswahl ist konfigurierbar; einfacher Wechsel zu Nachfolgemodell |

### 8.3 Fachliche Risiken

| # | Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|---|
| F1 | **Gap-Analyse False Positives** | Hoch | Hoch | Konfigurierbare Schwellenwerte; Feedback-Loop; bessere Modelle reduzieren False Positives |
| F2 | **Qualitaetsunterschiede zwischen Providern verwirrend** | Mittel | Mittel | Empfohlene Konfigurationen bereitstellen; Benchmark-Ergebnisse dokumentieren |
| F3 | **Benutzer ueberfordert von Provider-Auswahl** | Mittel | Mittel | Sinnvolle Defaults; "Empfohlen"-Labels; Quick-Start mit einem Klick |

### 8.4 Risiko-Matrix

```
Impact
  ^
  |
H |  [F1]     [T4]     [T1,K2]
  |
M |  [T5]     [T2,T3]  [K1,F2]
  |            [K4,F3]
L |
  |
  +------------------------------------>
     Niedrig      Mittel       Hoch
                          Wahrscheinlichkeit
```

---

## Anhang

### A. Technologie-Stack Zusammenfassung

| Schicht | Technologie | Version (empfohlen) |
|---|---|---|
| Programmiersprache | Python | 3.11+ |
| RAG Framework | LlamaIndex | 0.11+ |
| LLM Integration | llama-index-llms-openai, -anthropic, -ollama | latest |
| Embedding Integration | llama-index-embeddings-openai, -ollama | latest |
| Vector Database (MVP) | ChromaDB | 0.5+ |
| Code Parsing | tree-sitter | 0.22+ |
| Web Framework | FastAPI | 0.110+ |
| Frontend (MVP) | Streamlit | 1.35+ |
| Key Encryption | cryptography (Fernet) | 43+ |
| Git Integration | GitPython | 3.1+ |
| Config Management | pydantic-settings | 2.0+ |

### B. Projektstruktur (geplant)

```
openaustria-rag/
├── docs/
│   ├── MVP_KONZEPT.md              # Lokale Variante
│   └── MVP_KONZEPT_CLOUD.md        # Diese Datei (API-Key Variante)
├── src/
│   └── openaustria_rag/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py               # Pydantic Settings + YAML Config
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py             # Adapter Interfaces
│       │   ├── llm_factory.py      # LLM Provider Factory
│       │   ├── embedding_factory.py
│       │   ├── vectordb_factory.py
│       │   └── key_manager.py      # Verschluesselte Key-Speicherung
│       ├── connectors/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── git_connector.py
│       │   ├── zip_connector.py
│       │   └── confluence_connector.py
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── pipeline.py
│       │   ├── chunking.py
│       │   └── code_parser.py
│       ├── retrieval/
│       │   ├── __init__.py
│       │   ├── vector_store.py
│       │   └── query_engine.py
│       ├── analysis/
│       │   ├── __init__.py
│       │   ├── gap_analyzer.py
│       │   ├── matching.py
│       │   └── cost_tracker.py     # Token-Zaehlung + Kosten
│       ├── llm/
│       │   ├── __init__.py
│       │   └── prompts.py
│       └── frontend/
│           ├── __init__.py
│           ├── app.py
│           ├── pages/
│           │   ├── chat.py
│           │   ├── gap_analysis.py
│           │   └── settings.py     # Provider-/Key-Verwaltung
│           └── components/
├── tests/
├── pyproject.toml
└── README.md
```

### C. Erste Schritte (Quick Start)

```bash
# 1. Projekt-Dependencies installieren
pip install -e ".[dev]"

# 2a. Mit API-Keys (schnellster Start):
export OPENAI_API_KEY="sk-..."
# ODER
export ANTHROPIC_API_KEY="sk-ant-..."

# 2b. Mit Ollama (kostenlos, lokal):
curl -fsSL https://ollama.com/install.sh | sh
ollama pull mistral
ollama pull nomic-embed-text

# 3. Anwendung starten
streamlit run src/openaustria_rag/frontend/app.py

# 4. Im Browser: Settings oeffnen, Provider und Keys konfigurieren
```

### D. Vergleich der beiden MVP-Varianten

| Aspekt | MVP_KONZEPT.md (Lokal) | MVP_KONZEPT_CLOUD.md (API-Key) |
|---|---|---|
| **Primaerer Fokus** | Datenhoheit, Offline | Flexibilitaet, Qualitaet |
| **LLM** | Ollama + Mistral 7B | User-Wahl (OpenAI, Anthropic, etc.) |
| **Embedding** | Nomic Embed Text (lokal) | User-Wahl (OpenAI, Voyage, etc.) |
| **Hardware** | 16 GB RAM Minimum | 4 GB RAM genuegen |
| **Laufende Kosten** | Keine | $5-50/Monat (nutzungsabhaengig) |
| **Setup-Zeit** | ~30 Min (Ollama + Modelle) | ~5 Min (API-Key eintragen) |
| **Analyse-Qualitaet** | Gut (7B Modell) | Exzellent (State-of-the-Art) |
| **Offline-Faehig** | Ja | Nur mit Ollama-Fallback |
| **Architektur-Differenz** | Direkte Ollama-Integration | Provider Abstraction Layer |
| **Zusaetzliche Module** | -- | Key Manager, Cost Tracker, Settings UI |
