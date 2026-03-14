# Spezifikationsdokumente -- OpenAustria RAG (Lokale Variante)

**Referenz:** [MVP_KONZEPT.md](../MVP_KONZEPT.md)
**Datum:** 2026-03-14

---

## Dokumentenuebersicht

| Dokument | Inhalt | Wichtigste Themen |
|---|---|---|
| [SPEC-01: Datenmodell](SPEC_01_DATENMODELL.md) | Datenmodelle, Schemas, Persistenz | Project, Source, Document, Chunk, CodeElement, GapReport, SQLite + ChromaDB |
| [SPEC-02: Konnektoren](SPEC_02_KONNEKTOREN.md) | Konnektor-System und Plugin-Architektur | BaseConnector Interface, Git/ZIP/Confluence Implementierung, Fehlerklassen, Tests |
| [SPEC-03: Ingestion Pipeline](SPEC_03_INGESTION_PIPELINE.md) | Verarbeitungspipeline | tree-sitter Code-Parsing, Chunking-Strategien, Embedding-Service, Indexierung |
| [SPEC-04: RAG & Retrieval](SPEC_04_RAG_RETRIEVAL.md) | Query-Verarbeitung und LLM-Integration | QueryEngine, Ollama LLM Service, Prompt-Templates, Caching, LlamaIndex |
| [SPEC-05: Gap-Analyse](SPEC_05_GAP_ANALYSE.md) | Gap-Analyse Engine | Dreistufiger Algorithmus, Matching, LLM-Divergenz-Analyse, False-Positive-Mgmt |
| [SPEC-06: Frontend & API](SPEC_06_FRONTEND_API.md) | UI und REST API | Streamlit-Seiten, FastAPI-Endpunkte, Pydantic-Schemas, Request/Response |

## Abhaengigkeiten zwischen Spezifikationen

```
SPEC-01 (Datenmodell)
  ^         ^        ^
  |         |        |
SPEC-02   SPEC-03  SPEC-05
(Konnekt.) (Ingest.) (Gap)
  |         |    \    |
  |         v     v   v
  +-----> SPEC-04 (RAG)
              |
              v
          SPEC-06 (Frontend/API)
```

- **SPEC-01** definiert alle Datenstrukturen, die von allen anderen Specs verwendet werden
- **SPEC-02** liefert `RawDocument`-Objekte an **SPEC-03**
- **SPEC-03** erzeugt `Chunk`- und `CodeElement`-Objekte, die von **SPEC-04** und **SPEC-05** genutzt werden
- **SPEC-04** stellt die Query-Engine bereit, die **SPEC-06** ueber die API exponiert
- **SPEC-05** nutzt Embedding-Service aus **SPEC-03/04** und LLM-Service aus **SPEC-04**
- **SPEC-06** integriert alle Module in die Benutzeroberflaeche

## Technologie-Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.11+ |
| LLM | Ollama + Mistral 7B Q4_K_M |
| Embedding | Nomic Embed Text v1.5 via Ollama |
| RAG Framework | LlamaIndex 0.11+ |
| Vector DB | ChromaDB 0.5+ |
| Code Parsing | tree-sitter 0.22+ |
| Metadaten-DB | SQLite |
| API | FastAPI 0.110+ |
| Frontend | Streamlit 1.35+ |
