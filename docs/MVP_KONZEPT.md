# MVP Konzeptdokument: OpenAustria RAG Dokumentationsplattform

**Version:** 1.0
**Datum:** 2026-03-14
**Status:** Entwurf

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

In Software-Projekten entsteht Dokumentation an vielen Stellen: Confluence-Seiten, Enterprise-Architect-Modelle, Javadoc, Inline-Kommentare, README-Dateien, Spezifikationen. Diese Quellen sind oft inkonsistent, veraltet oder widerspruchlich. Entwickler und Architekten verbringen erhebliche Zeit damit, relevante Informationen zusammenzusuchen und Abweichungen zwischen Code und Dokumentation manuell zu identifizieren.

### Zielgruppe

- **Software-Architekten**, die Konsistenz zwischen Analyse, Spezifikation und Implementierung sicherstellen mussen
- **Entwickler**, die schnell die relevante Dokumentation zu einem Codebereich finden wollen
- **Projektleiter und QA**, die Dokumentationslucken systematisch identifizieren mochten
- **Teams in regulierten Umgebungen** (Finanz, Gesundheit, offentlicher Sektor), die Nachweispflichten fur Dokumentation haben

### Kernidee

Eine ressourcenschonende, lokal betreibbare Plattform, die:

1. **Verschiedenste Quellen** uber Konnektoren einsammelt (Git-Repos, Confluence, Enterprise Architect, Javadoc, ZIP-Codebases)
2. **RAG (Retrieval-Augmented Generation)** nutzt, um diese Inhalte semantisch durchsuchbar und chatbar zu machen
3. **Gaps und Divergenzen** zwischen Code, Analyse und Spezifikation automatisch identifiziert
4. **Komplett lokal** auf Hardware mit 16 GB RAM lauffahig ist -- keine Cloud-Abhangigkeit, keine Datenweitergabe

### Alleinstellungsmerkmale

| Feature | OpenAustria RAG | Typische Doku-Tools |
|---|---|---|
| Cross-Source-Suche | Ja (Code + Doku + Modelle) | Nein (siloed) |
| Gap-Analyse | Automatisch via LLM | Manuell |
| Lokaler Betrieb | 16 GB RAM genugt | Cloud-basiert |
| Datenhoheit | 100 % lokal | Daten bei Drittanbieter |

---

## 2. Technologie-Evaluation

### 2.1 LLM-Vergleich (lokal, 16 GB RAM)

Alle Modelle werden uber **Ollama** bereitgestellt und mussen in quantisierter Form auf 16 GB RAM laufen. Entscheidende Kriterien: Inference-Geschwindigkeit, Kontextfenster, Qualitat bei Code-Verstandnis und deutschsprachiger Dokumentation.

| Modell | Quantisierung | RAM-Bedarf | Kontext | Code-Qualitat | Deutsch | Empfehlung |
|---|---|---|---|---|---|---|
| **Mistral 7B** | Q4_K_M | ~5 GB | 8k (32k sliding) | Gut | Gut | **MVP-Empfehlung** |
| **Llama 3.1 8B** | Q4_K_M | ~5.5 GB | 128k | Sehr gut | Mittel | Alternative |
| **Phi-3 Medium 14B** | Q4_K_M | ~9 GB | 128k | Sehr gut | Mittel | Fur grossere Hardware |
| **Qwen2 7B** | Q4_K_M | ~5 GB | 128k | Gut | Gut (multilingual) | Alternative |

**Empfehlung fur MVP: Mistral 7B Q4_K_M**

- Bestes Verhaltnis aus RAM-Verbrauch, Geschwindigkeit und Qualitat
- Gute deutschsprachige Fahigkeiten
- Bewahrt in RAG-Szenarien
- Lasst genuegend RAM fur Embedding-Modell + Vector DB + Anwendung

**Alternative: Llama 3.1 8B** fur Projekte, die von dem grosseren Kontextfenster (128k) profitieren, z.B. bei langen Code-Dateien.

### 2.2 RAG-Frameworks

| Framework | Starken | Schwachen | MVP-Eignung |
|---|---|---|---|
| **LlamaIndex** | Spezialisiert auf RAG, exzellente Chunking-Strategien, gute Code-Unterstutzung, aktive Community | Weniger flexibel fur Non-RAG-Workflows | **Empfohlen** |
| **Haystack** | Modulare Pipeline-Architektur, gute Dokumentation | Overhead fur reines RAG, komplexere Konfiguration | Gut |
| **LangChain** | Grosses Okosystem, viele Integrationen | Abstraktions-Overhead, haufige API-Anderungen, Debugging schwierig | Nicht empfohlen |

**Empfehlung: LlamaIndex**

Grunde:
- Nativer Fokus auf Document Retrieval und RAG-Pipelines
- Eingebaute Chunking-Strategien fur Code (tree-sitter Integration moglich)
- `VectorStoreIndex`, `SummaryIndex`, `KnowledgeGraphIndex` out-of-the-box
- Einfache Integration mit Ollama via `Ollama` LLM-Klasse
- Gute Unterstutzung fur Custom Retrievers (wichtig fur Gap-Analyse)

### 2.3 Vector Database

| Vector DB | MVP | Production | Bemerkung |
|---|---|---|---|
| **ChromaDB** | Ja | Nein | Eingebettet, kein Server notig, SQLite-Backend, perfekt fur MVP |
| **Qdrant** | Nein | Ja | Performant, filterfähig, Kubernetes-ready, REST + gRPC API |
| **Milvus** | Nein | Optional | Skalierbar, aber Overhead fur kleine Deployments |

**MVP: ChromaDB** -- Zero-Config, eingebettet in Python-Prozess, persistent auf Disk.

**Migration zu Qdrant** bei:
- \> 500.000 Dokument-Chunks
- Mehrere gleichzeitige Nutzer
- Bedarf an Metadaten-Filterung in Production

### 2.4 Embedding-Modelle (lokal via Ollama)

| Modell | Dimensionen | RAM | Multilinguale Qualitat | Empfehlung |
|---|---|---|---|---|
| **Nomic Embed Text v1.5** | 768 | ~300 MB | Gut (Englisch-fokussiert) | **MVP-Empfehlung** |
| **BGE-M3** | 1024 | ~600 MB | Exzellent (multilingual) | Production |
| **E5-Large v2** | 1024 | ~500 MB | Gut | Alternative |
| **mxbai-embed-large** | 1024 | ~670 MB | Gut | Alternative |

**Empfehlung fur MVP: Nomic Embed Text v1.5**

- Sehr geringer RAM-Bedarf (~300 MB)
- Via Ollama mit einem Befehl installierbar: `ollama pull nomic-embed-text`
- Gute Balance aus Qualitat und Performance
- Unterstutzt variable Dimensionen (Matryoshka Embeddings)

**Upgrade-Pfad:** BGE-M3 fur bessere mehrsprachige Unterstutzung (Deutsch + Englisch gemischte Codebases).

### 2.5 Code-Parsing: tree-sitter

**tree-sitter** wird fur das Parsen von Source Code in Abstract Syntax Trees (AST) eingesetzt.

Vorteile:
- Multi-Language-Support (Java, Python, TypeScript, C#, Go, etc.)
- Inkrementelles Parsing (effizient bei Anderungen)
- Exakte Extraktion von Klassen, Methoden, Interfaces, Kommentaren
- Python-Bindings verfugbar (`tree-sitter` + `tree-sitter-languages`)

Einsatzgebiete in der Plattform:
- **Strukturierte Code-Extraktion**: Klassen, Methoden, Signaturen, Docstrings
- **Intelligentes Chunking**: Code wird entlang semantischer Grenzen aufgeteilt (nicht willkurlich nach Token-Anzahl)
- **Gap-Analyse**: Extraktion von implementierten Interfaces/Klassen fur Abgleich mit Spezifikation

---

## 3. Architektur

### 3.1 Architekturuberblick

```
+------------------------------------------------------------------+
|                         Frontend Layer                            |
|  +-------------------+  +---------------------+                  |
|  |  Chat Interface   |  |  Gap-Analyse        |                  |
|  |  (Streamlit)      |  |  Dashboard          |                  |
|  +-------------------+  +---------------------+                  |
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
| LLM Layer |  | Retrieval  |  | Gap Analysis |  | Ingestion       |
| (Ollama)  |  | Layer      |  | Engine       |  | Pipeline        |
|           |  | (LlamaIdx) |  |              |  |                 |
+-----------+  +------------+  +--------------+  +-----------------+
                    |                                    |
              +------------+                    +-----------------+
              | Vector DB  |                    | Connector Layer |
              | (ChromaDB) |                    | (Plugin-System) |
              +------------+                    +-----------------+
                                                        |
                                        +------+--------+--------+
                                        |      |        |        |
                                       Git  Conflu-   ZIP    Enterprise
                                       Repo  ence   Upload  Architect
```

### 3.2 Schichten im Detail

#### Connector Layer (Plugin-System)

Jeder Konnektor implementiert ein einheitliches Interface:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Document:
    content: str
    metadata: dict          # source, type, path, timestamp, ...
    source_type: str        # "code", "documentation", "specification", "model"

class BaseConnector(ABC):
    @abstractmethod
    def connect(self, config: dict) -> None:
        """Verbindung zur Quelle herstellen."""

    @abstractmethod
    def fetch_documents(self) -> list[Document]:
        """Dokumente aus der Quelle laden."""

    @abstractmethod
    def get_metadata(self) -> dict:
        """Metadaten ueber die Quelle zurueckgeben."""
```

**Plugin-Discovery:** Konnektoren werden uber `entry_points` in `pyproject.toml` registriert. Neue Konnektoren konnen als separate Packages installiert werden.

#### Processing / Ingestion Pipeline

```
Raw Documents
     |
     v
+------------------+
| Format Detection |  (MIME-Type, Dateiendung)
+------------------+
     |
     v
+------------------+
| Content Parsing  |  (tree-sitter fur Code, Markdown-Parser, XML-Parser)
+------------------+
     |
     v
+------------------+
| Chunking         |  (Semantisch: Code nach Klassen/Methoden,
+------------------+   Doku nach Abschnitten)
     |
     v
+------------------+
| Metadata         |  (Source-Typ, Sprache, Pfad, Zeitstempel,
| Enrichment       |   Abhangigkeiten)
+------------------+
     |
     v
+------------------+
| Embedding +      |  (Nomic Embed Text via Ollama)
| Indexierung      |  (ChromaDB Upsert)
+------------------+
```

**Chunking-Strategie:**

| Quelltyp | Strategie | Chunk-Grosse |
|---|---|---|
| Source Code | tree-sitter: Klasse/Methode als Chunk | variabel (max. 2048 Tokens) |
| Markdown/Confluence | Header-basiert (H1/H2/H3 Splits) | 512-1024 Tokens |
| Javadoc | Klasse + Methoden-Docs als Chunk | 512-1024 Tokens |
| EA-Modelle | Element/Diagramm als Chunk | variabel |

#### Vector Store + Embedding Layer

- **Embedding-Modell**: Nomic Embed Text v1.5 (768 Dimensionen)
- **Vector DB**: ChromaDB (persistent, Disk-basiert)
- **Collections**: Separate Collections pro Projekt und Quelltyp
- **Metadaten-Schema**:

```json
{
  "source_type": "code | documentation | specification | model",
  "connector": "git | confluence | zip | ea",
  "language": "java | python | typescript | markdown | ...",
  "file_path": "src/main/java/com/example/Service.java",
  "element_type": "class | method | interface | page | diagram",
  "element_name": "UserService.createUser",
  "project": "my-project",
  "ingested_at": "2026-03-14T10:00:00Z"
}
```

#### LLM / Chat Layer

- **Ollama** als LLM-Runtime (REST API auf `localhost:11434`)
- **LlamaIndex** `Ollama` Integration fur Query Engine
- **Prompt-Templates** fur verschiedene Aufgaben:
  - `chat`: Allgemeine Fragen zur Codebasis beantworten
  - `explain`: Code erklaren
  - `gap_analysis`: Divergenzen zwischen Quellen identifizieren
  - `summarize`: Zusammenfassungen generieren

#### Gap Analysis Engine

Separates Modul, das die Kernfunktionalitat der Plattform darstellt. Siehe [Abschnitt 5](#5-gap-analyse-ansatz) fur Details.

#### Frontend (Chat + Dashboard)

**MVP: Streamlit**
- Schnelle Prototyping-Fahigkeit
- Chat-Interface mit `st.chat_message`
- Dashboard-Komponenten fur Gap-Analyse-Ergebnisse
- Datei-Upload fur ZIP-Codebases
- Projekt-Verwaltung (CRUD)

**Production-Upgrade:** React/Next.js Frontend mit FastAPI-Backend.

---

## 4. Konnektoren

### 4.1 MVP-Konnektoren

#### Git-Repo URL Konnektor

```
Input:  Git-Repository URL (HTTPS/SSH)
Output: Geclontes Repo → Dateien → Parsed Documents
```

Funktionalitat:
- Clone/Pull via `gitpython`
- Rekursives Traversieren der Dateistruktur
- Filterung nach relevanten Dateien (`.java`, `.py`, `.ts`, `.md`, `.yml`, etc.)
- Ignorieren von Build-Artefakten, `node_modules`, `.git`
- tree-sitter Parsing fur Code-Dateien
- Markdown-Parsing fur Dokumentationsdateien
- Extraktion von Git-Metadaten (letzter Commit, Autor, Datum)

#### ZIP-Upload Konnektor

```
Input:  ZIP-Datei (Upload via Frontend)
Output: Entpackte Dateien → Parsed Documents
```

Funktionalitat:
- ZIP-Entpacken in temporares Verzeichnis
- Gleiche Verarbeitungslogik wie Git-Konnektor
- Bereinigung des temporaren Verzeichnisses nach Ingestion
- Sicherheitsprufung: Keine Path-Traversal-Angriffe, Grossenlimit

#### Confluence API Konnektor

```
Input:  Confluence URL + API Token + Space Key
Output: Confluence-Seiten → Parsed Documents
```

Funktionalitat:
- REST API v2 (`/wiki/api/v2/spaces/{id}/pages`)
- Paginierte Abfrage aller Seiten eines Spaces
- HTML-zu-Markdown-Konvertierung (`markdownify` oder `html2text`)
- Extraktion von Seitenstruktur (Parent/Child-Hierarchie)
- Attachment-Download (Bilder, PDFs)
- Inkrementelle Updates (nur geanderte Seiten seit letztem Sync)

### 4.2 Future-Konnektoren

| Konnektor | Prioritat | Komplexitat | Bemerkung |
|---|---|---|---|
| **Enterprise Architect** | Hoch | Hoch | XMI/EAP-Export, UML-Modelle parsen |
| **Javadoc** | Mittel | Niedrig | HTML-Parsing der generierten Docs |
| **Swagger/OpenAPI** | Mittel | Niedrig | JSON/YAML direkt parsbar |
| **Jira** | Niedrig | Mittel | REST API, Issues + Kommentare |
| **SharePoint** | Niedrig | Hoch | Microsoft Graph API |

#### Enterprise Architect Konnektor (Konzept)

- Export als XMI 2.1 (XML-basiert)
- Parsing der UML-Elemente: Klassen, Interfaces, Sequenzdiagramme, Komponentendiagramme
- Mapping auf `Document`-Objekte mit Metadaten
- Besonders wertvoll fur Gap-Analyse: EA-Modell vs. tatsachlicher Code

---

## 5. Gap-Analyse Ansatz

### 5.1 Uberblick

Die Gap-Analyse ist das Kernfeature der Plattform. Sie identifiziert Abweichungen zwischen:

- **Code ↔ Dokumentation**: Implementierte Funktionalitat vs. dokumentierte Funktionalitat
- **Code ↔ Spezifikation**: Implementierung vs. Anforderungen
- **Dokumentation ↔ Spezifikation**: Beschriebene vs. geforderte Funktionalitat

### 5.2 Dreistufiger Ansatz

#### Stufe 1: Strukturelle Extraktion

**Code-Seite (via tree-sitter):**
```
Source Code
    |
    v
tree-sitter AST
    |
    v
+-- Klassen (Name, Package, Interfaces, Vererbung)
+-- Methoden (Signatur, Parameter, Ruckgabetyp, Sichtbarkeit)
+-- Interfaces (Name, Methoden)
+-- Enums, Constants
+-- API-Endpunkte (Annotationen: @GetMapping, @PostMapping, etc.)
+-- Datenbank-Entitaten (@Entity, @Table)
```

**Dokumentations-Seite (aus Konnektoren):**
```
Confluence / Markdown / EA
    |
    v
+-- Beschriebene Komponenten
+-- Beschriebene Schnittstellen
+-- Anforderungen (funktional / nicht-funktional)
+-- Architektur-Entscheidungen
+-- Prozessbeschreibungen
```

#### Stufe 2: Matching-Algorithmus

1. **Namensbasiertes Matching**: Klassen/Methoden-Namen ↔ Dokumentations-Erwahnungen
   - Fuzzy Matching (Levenshtein-Distanz, Token-basiert)
   - CamelCase/snake_case Normalisierung
2. **Embedding-basiertes Matching**: Semantische Ahnlichkeit zwischen Code-Chunks und Doku-Chunks
   - Cosine Similarity auf Embedding-Vektoren
   - Schwellenwert konfigurierbar (default: 0.7)
3. **Kategorisierung**:
   - **Documented & Implemented**: Alles in Ordnung
   - **Implemented, Not Documented**: Code existiert, Doku fehlt
   - **Documented, Not Implemented**: Doku beschreibt etwas, das im Code nicht existiert
   - **Divergent**: Beide existieren, aber widersprechen sich

#### Stufe 3: LLM-basierte semantische Analyse

Fur die Kategorie "Divergent" und Grenzfalle wird das lokale LLM eingesetzt:

```
Prompt-Template (Gap-Analyse):
---
Analysiere die folgende Code-Implementierung und die zugehoerige Dokumentation.
Identifiziere Abweichungen und bewerte deren Schweregrad.

CODE:
{code_chunk}

DOKUMENTATION:
{doc_chunk}

Antworte im folgenden Format:
- Uebereinstimmung: [Ja/Teilweise/Nein]
- Abweichungen: [Liste der Abweichungen]
- Schweregrad: [Niedrig/Mittel/Hoch/Kritisch]
- Empfehlung: [Was sollte angepasst werden]
---
```

### 5.3 Gap-Analyse Output

```json
{
  "project": "my-project",
  "analysis_date": "2026-03-14T10:00:00Z",
  "summary": {
    "total_code_elements": 142,
    "documented": 98,
    "undocumented": 35,
    "divergent": 9,
    "documentation_coverage": "69%"
  },
  "gaps": [
    {
      "type": "undocumented",
      "severity": "medium",
      "code_element": "UserService.resetPassword()",
      "file": "src/main/java/com/example/UserService.java",
      "line": 145,
      "suggestion": "Methode implementiert Passwort-Reset mit E-Mail-Verifikation. Keine entsprechende Dokumentation in Confluence gefunden."
    },
    {
      "type": "divergent",
      "severity": "high",
      "code_element": "OrderController.createOrder()",
      "doc_reference": "Confluence: /spaces/PROJ/pages/12345",
      "divergence": "Dokumentation beschreibt Validierung ueber externen Service. Code validiert lokal.",
      "recommendation": "Dokumentation oder Implementierung anpassen."
    }
  ]
}
```

### 5.4 Dashboard-Visualisierung

- **Coverage-Heatmap**: Visualisierung der Dokumentationsabdeckung pro Package/Modul
- **Gap-Liste**: Sortierbar nach Schweregrad, Typ, Modul
- **Trend-Analyse**: Entwicklung der Dokumentationsabdeckung uber Zeit (bei wiederholten Scans)
- **Export**: JSON, CSV, PDF-Report

---

## 6. Ressourcen-Anforderungen & Benchmarks

### 6.1 Hardware-Konfigurationen

#### Minimalkonfiguration (MVP)

| Komponente | Anforderung |
|---|---|
| **RAM** | 16 GB |
| **CPU** | 4 Cores (x86_64 oder ARM64) |
| **Storage** | 20 GB SSD (fur Modelle + Vector DB) |
| **GPU** | Nicht erforderlich (CPU-Inference) |

**RAM-Aufteilung bei 16 GB:**

```
+-------------------------------------------+
| OS + System                   | ~3 GB     |
| Ollama + Mistral 7B Q4_K_M   | ~5 GB     |
| Ollama + Nomic Embed Text     | ~0.3 GB   |
| ChromaDB (in-process)         | ~0.5 GB   |
| Python App + LlamaIndex       | ~1 GB     |
| Streamlit Frontend             | ~0.2 GB   |
| Puffer                        | ~6 GB     |
+-------------------------------------------+
  Gesamt:                        ~10 GB (von 16 GB)
```

#### Empfohlene Konfiguration

| Komponente | Anforderung |
|---|---|
| **RAM** | 32 GB |
| **CPU** | 8 Cores |
| **Storage** | 50 GB SSD |
| **GPU** | Optional: NVIDIA mit 8 GB+ VRAM (beschleunigt Inference um ~5-10x) |

#### Production-Konfiguration

| Komponente | Anforderung |
|---|---|
| **RAM** | 64 GB |
| **CPU** | 16 Cores |
| **Storage** | 200 GB SSD |
| **GPU** | NVIDIA mit 16 GB+ VRAM |
| **Vector DB** | Qdrant (separater Service) |

### 6.2 Erwartete Performance-Metriken

#### Inference-Geschwindigkeit (Mistral 7B Q4_K_M)

| Hardware | Tokens/s | Antwortzeit (200 Tokens) |
|---|---|---|
| CPU-only (4 Cores, 16 GB) | ~8-12 t/s | ~17-25 Sek |
| CPU-only (8 Cores, 32 GB) | ~15-20 t/s | ~10-13 Sek |
| GPU (RTX 3060, 12 GB VRAM) | ~40-60 t/s | ~3-5 Sek |
| Apple M2, 16 GB unified | ~15-25 t/s | ~8-13 Sek |
| Apple M3 Pro, 18 GB unified | ~25-35 t/s | ~6-8 Sek |

#### Embedding-Geschwindigkeit (Nomic Embed Text)

| Hardware | Chunks/Min | 10.000 Chunks |
|---|---|---|
| CPU-only (4 Cores) | ~200-300 | ~33-50 Min |
| CPU-only (8 Cores) | ~400-600 | ~17-25 Min |
| Apple M2 | ~500-800 | ~13-20 Min |
| GPU (RTX 3060) | ~1500-2500 | ~4-7 Min |

#### Vector-Suche (ChromaDB)

| Datenmenge | Query-Latenz (Top-10) |
|---|---|
| 10.000 Chunks | < 50 ms |
| 100.000 Chunks | < 200 ms |
| 500.000 Chunks | ~500 ms (Migration zu Qdrant empfohlen) |

### 6.3 Kapazitatsplanung

| Projektgrosse | Geschatzte Chunks | Speicherbedarf (Vector DB) | Ingestion-Zeit (CPU) |
|---|---|---|---|
| Klein (< 100 Dateien) | ~1.000-3.000 | ~50 MB | ~5-15 Min |
| Mittel (100-1.000 Dateien) | ~5.000-20.000 | ~200 MB - 1 GB | ~30-90 Min |
| Gross (1.000-10.000 Dateien) | ~20.000-100.000 | ~1-5 GB | ~3-8 Std |

---

## 7. MVP Scope & Roadmap

### 7.1 MVP Scope (Phase 1)

**Ziel:** Funktionierender Prototyp mit Kernfunktionalitat in 8-12 Wochen.

#### In Scope

- [x] Git-Repo Konnektor (Clone + Parse)
- [x] ZIP-Upload Konnektor
- [x] Confluence API Konnektor
- [x] tree-sitter Code-Parsing (Java, Python, TypeScript)
- [x] Semantisches Chunking
- [x] Embedding + Indexierung (Nomic Embed Text + ChromaDB)
- [x] Chat-Interface (Streamlit)
- [x] Einfache RAG-Queries uber LlamaIndex
- [x] Basis-Gap-Analyse (Code vs. Doku Coverage)
- [x] Projekt-Verwaltung (Anlegen, Quellen zuordnen)
- [x] Ollama-Integration (Mistral 7B)

#### Out of Scope (MVP)

- Enterprise Architect Konnektor
- Javadoc Konnektor
- Multi-User / Authentifizierung
- Versionierung von Analyse-Ergebnissen
- CI/CD-Integration
- REST API fur externe Integration
- React/Next.js Frontend
- Qdrant Migration
- Kubernetes Deployment

### 7.2 Roadmap

```
Phase 1: MVP                           Phase 2: Erweiterung
(Wochen 1-12)                          (Wochen 13-24)
+----------------------------------+   +----------------------------------+
| - Git/ZIP/Confluence Konnektoren |   | - EA + Javadoc Konnektoren       |
| - tree-sitter Parsing            |   | - Erweiterte Gap-Analyse         |
| - ChromaDB + Nomic Embed         |   | - FastAPI Backend                |
| - Streamlit Chat UI              |   | - Multi-Projekt-Support          |
| - Basis-Gap-Analyse              |   | - Inkrementelle Re-Indexierung   |
| - Ollama + Mistral 7B            |   | - PDF-Report-Export              |
+----------------------------------+   +----------------------------------+

Phase 3: Production                     Phase 4: Enterprise
(Wochen 25-40)                          (Wochen 41+)
+----------------------------------+   +----------------------------------+
| - React/Next.js Frontend         |   | - Multi-User + RBAC              |
| - Qdrant Migration               |   | - LDAP/SSO Integration           |
| - REST API                       |   | - Audit-Logging                  |
| - CI/CD Integration              |   | - Kubernetes / Docker Compose    |
| - Swagger/OpenAPI Konnektor      |   | - Jira + SharePoint Konnektoren  |
| - Trend-Analyse Dashboard        |   | - Custom LLM Fine-Tuning         |
+----------------------------------+   +----------------------------------+
```

### 7.3 MVP Meilensteine

| Woche | Meilenstein | Deliverable |
|---|---|---|
| 1-2 | Projekt-Setup + Architektur | Repo-Struktur, Dependencies, CI |
| 3-4 | Connector Layer + Git-Konnektor | Funktionierender Git-Konnektor mit tree-sitter |
| 5-6 | Embedding + Vector Store | Ingestion Pipeline, ChromaDB Integration |
| 7-8 | LLM + Chat Interface | Ollama-Integration, Streamlit Chat |
| 9-10 | Confluence + ZIP Konnektor | Alle MVP-Konnektoren funktional |
| 11-12 | Gap-Analyse + Polish | Basis-Gap-Analyse, Testing, Dokumentation |

---

## 8. Risiken & Mitigationen

### 8.1 Technische Risiken

| # | Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|---|
| T1 | **LLM-Qualitat unzureichend auf 16 GB** -- Antworten zu ungenau fur Gap-Analyse | Mittel | Hoch | Prompt-Engineering optimieren; Fallback auf groesseres Modell (Phi-3 14B) bei 32 GB; RAG-Kontext-Qualitat verbessern statt groesseres Modell |
| T2 | **Embedding-Qualitat bei gemischt DE/EN** -- Semantische Suche liefert schlechte Ergebnisse | Mittel | Mittel | BGE-M3 als Alternative testen; Separate Collections fur DE/EN; Query-Expansion mit Ubersetzung |
| T3 | **tree-sitter Language-Support luckenhart** -- Nicht alle Sprachen/Frameworks erkannt | Niedrig | Mittel | Fallback auf Regex-basiertes Parsing; Community-Grammars nutzen; Custom-Grammars fur exotische Sprachen |
| T4 | **ChromaDB Performance bei grossem Datenvolumen** | Mittel | Mittel | Fruhe Migration zu Qdrant einplanen; Chunk-Anzahl durch besseres Chunking reduzieren |
| T5 | **Ollama API-Anderungen / Breaking Changes** | Niedrig | Niedrig | Ollama-Version pinnen; Abstraktionsschicht zwischen App und Ollama |

### 8.2 Fachliche Risiken

| # | Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|---|
| F1 | **Gap-Analyse False Positives** -- Zu viele falsche Alarme machen Feature unbrauchbar | Hoch | Hoch | Schwellenwerte konfigurierbar machen; Feedback-Loop (User markiert False Positives); Iteratives Prompt-Tuning |
| F2 | **Confluence-Inhalte zu unstrukturiert** -- Parsing liefert schlechte Ergebnisse | Mittel | Mittel | HTML-Cleanup-Pipeline; Konfigurierbare Seiten-Filter; Manuelle Seiten-Auswahl |
| F3 | **Benutzerakzeptanz gering** -- Tool wird nicht als nutzlich empfunden | Mittel | Hoch | Fruhes User-Feedback einholen; Quick Wins priorisieren (Chat-Suche vor Gap-Analyse); Einfaches Onboarding |

### 8.3 Organisatorische Risiken

| # | Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|---|
| O1 | **Scope Creep** -- Zu viele Features in MVP | Hoch | Mittel | Striktes MVP-Scope; Feature-Requests in Backlog sammeln; Timeboxed Phasen |
| O2 | **Confluence/Git-Zugriffsrechte** -- Kein Zugang zu relevanten Quellen | Mittel | Hoch | Fruh Zugangsrechte klaren; ZIP-Upload als Fallback; Service-Account beantragen |
| O3 | **Ressourcen-Engpass** -- Zu wenig Entwicklungskapazitat | Mittel | Hoch | MVP minimal halten; Open-Source-Komponenten maximal nutzen; Priorisierung nach Business Value |

### 8.4 Risiko-Matrix

```
Impact
  ^
  |
H |  [F1]           [T1]  [O2,O3]
  |
M |  [T4] [F2]      [T2]  [O1]
  |
L |  [T5]           [T3]
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
| LLM Runtime | Ollama | 0.3+ |
| LLM Modell | Mistral 7B Q4_K_M | latest |
| Embedding Modell | Nomic Embed Text v1.5 | latest |
| RAG Framework | LlamaIndex | 0.11+ |
| Vector Database | ChromaDB | 0.5+ |
| Code Parsing | tree-sitter | 0.22+ |
| Web Framework | FastAPI | 0.110+ |
| Frontend (MVP) | Streamlit | 1.35+ |
| Git Integration | GitPython | 3.1+ |
| HTML Parsing | html2text / markdownify | latest |

### B. Projektstruktur (geplant)

```
openaustria-rag/
├── docs/
│   └── MVP_KONZEPT.md
├── src/
│   └── openaustria_rag/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
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
│       │   └── matching.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── ollama_client.py
│       │   └── prompts.py
│       └── frontend/
│           ├── __init__.py
│           ├── app.py
│           └── components/
├── tests/
├── pyproject.toml
└── README.md
```

### C. Erste Schritte (Quick Start)

```bash
# 1. Ollama installieren
curl -fsSL https://ollama.com/install.sh | sh

# 2. Modelle herunterladen
ollama pull mistral
ollama pull nomic-embed-text

# 3. Projekt-Dependencies installieren
pip install -e ".[dev]"

# 4. Anwendung starten
streamlit run src/openaustria_rag/frontend/app.py
```
