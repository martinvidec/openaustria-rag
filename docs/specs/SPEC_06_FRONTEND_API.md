# SPEC-06: Frontend & API

**Referenz:** MVP_KONZEPT.md (Lokale Variante)
**Version:** 1.0
**Datum:** 2026-03-14

---

## 1. Ueberblick

Diese Spezifikation beschreibt das Streamlit-Frontend (MVP) und das FastAPI-Backend. Das Frontend bietet Chat-Interface, Gap-Analyse-Dashboard und Projektverwaltung. Das Backend stellt die REST-API bereit.

---

## 2. Frontend-Architektur (Streamlit)

### 2.1 Seitenstruktur

```
app.py (Haupteinstieg)
│
├── pages/
│   ├── 01_Projekte.py          # Projektverwaltung
│   ├── 02_Chat.py              # RAG Chat Interface
│   ├── 03_Gap_Analyse.py       # Gap-Analyse Dashboard
│   ├── 04_Quellen.py           # Quellen-/Konnektor-Verwaltung
│   └── 05_Einstellungen.py     # System-Einstellungen
│
└── components/
    ├── chat_message.py          # Chat-Nachrichten-Komponente
    ├── source_card.py           # Quellen-Karte
    ├── gap_table.py             # Gap-Analyse Tabelle
    └── progress_bar.py          # Ingestion-Fortschritt
```

### 2.2 Session State

```python
# Streamlit Session State Schema
st.session_state = {
    "current_project_id": str | None,
    "chat_history": list[dict],       # [{"role": "user"|"assistant", "content": str}]
    "chat_session_id": str,
    "selected_filters": {
        "source_type": str | None,
        "language": str | None,
        "connector": str | None,
    },
    "ingestion_progress": ConnectorProgress | None,
    "last_gap_report_id": str | None,
}
```

---

## 3. Seiten-Spezifikationen

### 3.1 Projektverwaltung (`01_Projekte.py`)

```
+----------------------------------------------------------+
|  Projekte                                      [+ Neu]   |
+----------------------------------------------------------+
|                                                           |
|  +-----------------------------------------------------+ |
|  | Projekt: my-webapp                                   | |
|  | Status: (gruener Punkt) Bereit                       | |
|  | Quellen: 3 (Git, ZIP, Confluence)                    | |
|  | Chunks: 12.450 | Letzte Indexierung: vor 2 Stunden   | |
|  | [Oeffnen]  [Bearbeiten]  [Loeschen]                  | |
|  +-----------------------------------------------------+ |
|                                                           |
|  +-----------------------------------------------------+ |
|  | Projekt: legacy-system                               | |
|  | Status: (gelber Punkt) Indexierung laeuft (67%)      | |
|  | Quellen: 1 (Git)                                     | |
|  | [Oeffnen]  [Abbrechen]                               | |
|  +-----------------------------------------------------+ |
|                                                           |
+----------------------------------------------------------+
```

**Aktionen:**

| Aktion | Beschreibung |
|---|---|
| Neu | Dialog: Name + Beschreibung eingeben → `POST /api/projects` |
| Oeffnen | Setzt `current_project_id`, navigiert zu Chat |
| Bearbeiten | Inline-Editing von Name/Beschreibung |
| Loeschen | Bestaetigung → `DELETE /api/projects/{id}` (inkl. aller Daten) |

### 3.2 Chat Interface (`02_Chat.py`)

```
+----------------------------------------------------------+
|  Chat - Projekt: my-webapp                                |
+----------------------------------------------------------+
| Filter: [Alle Quellen v] [Alle Sprachen v]               |
+----------------------------------------------------------+
|                                                           |
|  (User) Wie funktioniert die Authentifizierung?           |
|                                                           |
|  (Assistant) Die Authentifizierung basiert auf JWT        |
|  Tokens. Der AuthService generiert Tokens nach           |
|  erfolgreicher Validierung der Credentials.               |
|                                                           |
|  Quellen:                                                 |
|  [1] code - AuthService.java:42 (0.92)                   |
|  [2] doc - Confluence: Security Architecture (0.87)       |
|  [3] code - JwtTokenProvider.java:15 (0.81)              |
|                                                           |
|  Antwortzeit: Retrieval 120ms | Generierung 18.3s        |
|                                                           |
+----------------------------------------------------------+
|  [Nachricht eingeben...                        ] [Senden] |
+----------------------------------------------------------+
```

**Implementierung:**

```python
import streamlit as st

def chat_page():
    st.title(f"Chat - {get_project_name()}")

    # Filter-Sidebar
    with st.sidebar:
        source_filter = st.selectbox(
            "Quelltyp", ["Alle", "Code", "Dokumentation", "Konfiguration"]
        )
        lang_filter = st.selectbox(
            "Sprache", ["Alle", "Java", "Python", "TypeScript"]
        )

    # Chat-History anzeigen
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("Quellen"):
                    for src in msg["sources"]:
                        st.caption(
                            f"[{src['source_type']}] "
                            f"{src['file_path']} "
                            f"({src['similarity']:.2f})"
                        )

    # Chat-Input
    if prompt := st.chat_input("Frage stellen..."):
        # User-Nachricht anzeigen
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Antwort generieren
        with st.chat_message("assistant"):
            with st.spinner("Suche und generiere Antwort..."):
                result = query_engine.query(QueryContext(
                    project_id=st.session_state.current_project_id,
                    query=prompt,
                    filters=build_filters(source_filter, lang_filter),
                ))

            st.markdown(result.answer)

            # Quellen anzeigen
            with st.expander(f"Quellen ({len(result.sources)})"):
                for i, src in enumerate(result.sources, 1):
                    st.caption(
                        f"[{i}] {src.metadata.get('source_type', '')} - "
                        f"{src.metadata.get('file_path', '')} "
                        f"({src.similarity_score:.2f})"
                    )

            st.caption(
                f"Retrieval: {result.retrieval_time_ms}ms | "
                f"Generierung: {result.generation_time_ms}ms | "
                f"Tokens: {result.token_count}"
            )

        # In History speichern
        st.session_state.chat_history.append({
            "role": "assistant",
            "content": result.answer,
            "sources": [
                {
                    "source_type": s.metadata.get("source_type"),
                    "file_path": s.metadata.get("file_path"),
                    "similarity": s.similarity_score,
                }
                for s in result.sources
            ],
        })
```

### 3.3 Gap-Analyse Dashboard (`03_Gap_Analyse.py`)

```
+----------------------------------------------------------+
|  Gap-Analyse - Projekt: my-webapp                         |
+----------------------------------------------------------+
|  [Analyse starten]        Letzte Analyse: 14.03.2026     |
+----------------------------------------------------------+
|                                                           |
|  Zusammenfassung                                          |
|  +--------+  +--------+  +--------+  +--------+         |
|  | 142    |  | 98     |  | 35     |  | 9      |         |
|  | Code-  |  | Doku-  |  | Nicht  |  | Diver- |         |
|  | Elem.  |  | ment.  |  | Doku.  |  | gent   |         |
|  +--------+  +--------+  +--------+  +--------+         |
|                                                           |
|  Coverage: [==============------] 69%                     |
|                                                           |
+----------------------------------------------------------+
|  Gaps (sortiert nach Schweregrad)                         |
+----------------------------------------------------------+
|  Filter: [Alle Typen v] [Alle Schweregrade v] [Suche...] |
+----------------------------------------------------------+
|  KRITISCH | DIVERGENT | OrderController.createOrder()     |
|  Datei: OrderController.java:89                           |
|  Doku beschreibt externen Validierungsservice,            |
|  Code validiert lokal.                                    |
|  [Details] [False Positive markieren]                     |
|  ---------------------------------------------------------|
|  HOCH | UNDOCUMENTED | PaymentService.refund()            |
|  Datei: PaymentService.java:145                           |
|  Keine Dokumentation gefunden.                            |
|  [Details] [False Positive markieren]                     |
|  ---------------------------------------------------------|
|  ...                                                      |
+----------------------------------------------------------+
|  [Export: JSON] [Export: CSV]                              |
+----------------------------------------------------------+
```

**Implementierung:**

```python
def gap_analysis_page():
    st.title(f"Gap-Analyse - {get_project_name()}")
    project_id = st.session_state.current_project_id

    # Analyse starten
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Analyse starten", type="primary"):
            with st.spinner("Gap-Analyse laeuft... Dies kann einige Minuten dauern."):
                progress_bar = st.progress(0)
                report = gap_analyzer.analyze(project_id)
                st.session_state.last_gap_report_id = report.id
            st.success(f"Analyse abgeschlossen: {len(report.gaps)} Gaps gefunden")
            st.rerun()

    # Report anzeigen
    report = load_latest_report(project_id)
    if not report:
        st.info("Noch keine Analyse durchgefuehrt.")
        return

    # Summary-Metriken
    cols = st.columns(4)
    with cols[0]:
        st.metric("Code-Elemente", report.summary.total_code_elements)
    with cols[1]:
        st.metric("Dokumentiert", report.summary.documented)
    with cols[2]:
        st.metric("Nicht dokumentiert", report.summary.undocumented)
    with cols[3]:
        st.metric("Divergent", report.summary.divergent)

    # Coverage-Bar
    st.progress(
        report.summary.documentation_coverage,
        text=f"Dokumentationsabdeckung: {report.summary.documentation_coverage:.0%}"
    )

    st.divider()

    # Filter
    col1, col2, col3 = st.columns(3)
    with col1:
        type_filter = st.selectbox("Typ", ["Alle", "Undokumentiert", "Divergent", "Nicht implementiert"])
    with col2:
        severity_filter = st.selectbox("Schweregrad", ["Alle", "Kritisch", "Hoch", "Mittel", "Niedrig"])
    with col3:
        search = st.text_input("Suche", placeholder="Element-Name...")

    # Gap-Liste
    filtered_gaps = filter_gaps(report.gaps, type_filter, severity_filter, search)

    for gap in filtered_gaps:
        severity_color = {
            "critical": "red", "high": "orange",
            "medium": "blue", "low": "gray"
        }[gap.severity.value]

        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(
                    f"**:{severity_color}[{gap.severity.value.upper()}]** | "
                    f"`{gap.gap_type.value}` | "
                    f"**{gap.code_element_name}**"
                )
                if gap.file_path:
                    st.caption(f"Datei: {gap.file_path}:{gap.line or ''}")
                if gap.divergence_description:
                    st.write(gap.divergence_description)
            with col2:
                if st.button("False Positive", key=f"fp_{gap.id}"):
                    fp_manager.mark_false_positive(gap.id)
                    st.rerun()

    # Export
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        json_data = GapReportExporter.to_json(report)
        st.download_button("Export JSON", json_data, "gap_report.json", "application/json")
    with col2:
        csv_data = GapReportExporter.to_csv(report)
        st.download_button("Export CSV", csv_data, "gap_report.csv", "text/csv")
```

### 3.4 Quellen-Verwaltung (`04_Quellen.py`)

```
+----------------------------------------------------------+
|  Quellen - Projekt: my-webapp                             |
+----------------------------------------------------------+
|  [+ Git Repo] [+ ZIP Upload] [+ Confluence]              |
+----------------------------------------------------------+
|                                                           |
|  +-----------------------------------------------------+ |
|  | (Git) main-repo                                      | |
|  | URL: https://github.com/org/webapp.git               | |
|  | Branch: main | Dateien: 342 | Status: Synced         | |
|  | Letzte Synchronisierung: 14.03.2026 08:30            | |
|  | [Sync]  [Bearbeiten]  [Entfernen]                    | |
|  +-----------------------------------------------------+ |
|                                                           |
|  +-----------------------------------------------------+ |
|  | (Confluence) Projektdoku                             | |
|  | Space: PROJ | Seiten: 87 | Status: Synced            | |
|  | [Sync]  [Bearbeiten]  [Entfernen]                    | |
|  +-----------------------------------------------------+ |
|                                                           |
|  +-----------------------------------------------------+ |
|  | (ZIP) legacy-code-v2.zip                             | |
|  | Dateien: 156 | Status: Synced                        | |
|  | [Entfernen]                                           | |
|  +-----------------------------------------------------+ |
|                                                           |
+----------------------------------------------------------+
```

**Dialoge:**

```python
def add_git_dialog():
    with st.form("add_git"):
        url = st.text_input("Repository URL", placeholder="https://github.com/org/repo.git")
        branch = st.text_input("Branch", value="main", help="Leer fuer Default-Branch")
        token = st.text_input("Access Token (optional)", type="password")
        name = st.text_input("Anzeigename", placeholder="main-repo")

        if st.form_submit_button("Hinzufuegen"):
            config = {"url": url}
            if branch:
                config["branch"] = branch
            if token:
                config["auth_token"] = token

            source = create_source(
                project_id=st.session_state.current_project_id,
                source_type="git",
                name=name or url.split("/")[-1].replace(".git", ""),
                config=config,
            )
            st.success(f"Quelle '{source.name}' hinzugefuegt.")
            st.rerun()

def add_confluence_dialog():
    with st.form("add_confluence"):
        base_url = st.text_input("Confluence URL", placeholder="https://company.atlassian.net")
        space_key = st.text_input("Space Key", placeholder="PROJ")
        email = st.text_input("E-Mail")
        api_token = st.text_input("API Token", type="password")
        name = st.text_input("Anzeigename", placeholder="Projekt-Dokumentation")

        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("Verbindung testen"):
                connector = ConfluenceConnector("test", {
                    "base_url": base_url, "space_key": space_key,
                    "email": email, "api_token": api_token,
                })
                if connector.test_connection():
                    st.success("Verbindung erfolgreich!")
                else:
                    st.error("Verbindung fehlgeschlagen.")

def add_zip_dialog():
    with st.form("add_zip"):
        uploaded_file = st.file_uploader("ZIP-Datei hochladen", type=["zip"])
        name = st.text_input("Anzeigename", placeholder="legacy-code")

        if st.form_submit_button("Hochladen"):
            if uploaded_file:
                # Datei speichern
                upload_path = save_upload(uploaded_file)
                source = create_source(
                    project_id=st.session_state.current_project_id,
                    source_type="zip",
                    name=name or uploaded_file.name,
                    config={"upload_path": upload_path, "filename": uploaded_file.name},
                )
                st.success(f"'{uploaded_file.name}' hochgeladen.")
                st.rerun()
```

### 3.5 Einstellungen (`05_Einstellungen.py`)

```
+----------------------------------------------------------+
|  Einstellungen                                             |
+----------------------------------------------------------+
|                                                           |
|  Ollama                                                   |
|  URL:    [http://localhost:11434        ]                  |
|  Status: (gruener Punkt) Verbunden                       |
|                                                           |
|  LLM Modell:       [v mistral              ]              |
|  Embedding Modell: [v nomic-embed-text     ]              |
|                                                           |
|  --------------------------------------------------      |
|                                                           |
|  Chunking                                                 |
|  Code Max Tokens:     [2048]                              |
|  Doku Max Tokens:     [1024]                              |
|  Doku Overlap Tokens: [128 ]                              |
|                                                           |
|  --------------------------------------------------      |
|                                                           |
|  Gap-Analyse                                              |
|  Name-Similarity:     [0.6  ] (0.0 - 1.0)                |
|  Embedding-Similarity:[0.7  ] (0.0 - 1.0)                |
|  Max LLM Analysen:    [50   ]                             |
|  Test-Dateien ausschliessen: [x]                          |
|                                                           |
|  [Speichern]                                              |
+----------------------------------------------------------+
```

---

## 4. FastAPI Backend

### 4.1 API-Endpunkte

#### Projects

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/projects` | Alle Projekte auflisten |
| `POST` | `/api/projects` | Neues Projekt anlegen |
| `GET` | `/api/projects/{id}` | Projekt-Details |
| `PUT` | `/api/projects/{id}` | Projekt aktualisieren |
| `DELETE` | `/api/projects/{id}` | Projekt loeschen (inkl. aller Daten) |

#### Sources

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/projects/{id}/sources` | Quellen eines Projekts |
| `POST` | `/api/projects/{id}/sources` | Quelle hinzufuegen |
| `PUT` | `/api/sources/{id}` | Quelle aktualisieren |
| `DELETE` | `/api/sources/{id}` | Quelle entfernen |
| `POST` | `/api/sources/{id}/sync` | Synchronisierung starten |
| `GET` | `/api/sources/{id}/status` | Sync-Status abfragen |
| `POST` | `/api/sources/{id}/test` | Verbindung testen |

#### Chat / Query

| Methode | Pfad | Beschreibung |
|---|---|---|
| `POST` | `/api/projects/{id}/query` | RAG-Query ausfuehren |
| `POST` | `/api/projects/{id}/query/stream` | Streaming RAG-Query (SSE) |
| `GET` | `/api/projects/{id}/chat/history` | Chat-Verlauf |
| `DELETE` | `/api/projects/{id}/chat/history` | Chat-Verlauf loeschen |

#### Gap-Analyse

| Methode | Pfad | Beschreibung |
|---|---|---|
| `POST` | `/api/projects/{id}/gap-analysis` | Analyse starten |
| `GET` | `/api/projects/{id}/gap-analysis/latest` | Letzten Report abrufen |
| `GET` | `/api/gap-reports/{id}` | Spezifischen Report abrufen |
| `GET` | `/api/gap-reports/{id}/export/{format}` | Report exportieren (json/csv) |
| `PUT` | `/api/gap-items/{id}/false-positive` | False Positive markieren |

#### System

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/api/health` | Health Check (App + Ollama) |
| `GET` | `/api/settings` | Aktuelle Einstellungen |
| `PUT` | `/api/settings` | Einstellungen aktualisieren |
| `GET` | `/api/stats` | Systemstatistiken |

### 4.2 Request/Response Schemas (Pydantic)

```python
from pydantic import BaseModel, Field

# --- Projects ---

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""

class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str
    source_count: int = 0
    chunk_count: int = 0

# --- Sources ---

class SourceCreate(BaseModel):
    source_type: str                     # "git" | "zip" | "confluence"
    name: str
    config: dict

class SourceResponse(BaseModel):
    id: str
    project_id: str
    source_type: str
    name: str
    status: str
    last_sync_at: str | None
    error_message: str | None

class SyncStatus(BaseModel):
    status: str                          # "syncing" | "synced" | "error"
    progress: float                      # 0.0 - 1.0
    processed: int
    total: int
    errors: int
    current_item: str

# --- Query ---

class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    filters: dict = {}
    top_k: int = Field(default=10, ge=1, le=50)

class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    query_type: str
    token_count: int
    retrieval_time_ms: int
    generation_time_ms: int

# --- Gap Analysis ---

class GapReportResponse(BaseModel):
    id: str
    project_id: str
    created_at: str
    summary: dict
    gaps: list[dict]
    total_gaps: int

# --- Health ---

class HealthResponse(BaseModel):
    status: str                          # "healthy" | "degraded" | "unhealthy"
    ollama: bool
    llm_model: str
    embedding_model: str
    database: bool
    vector_store: bool
```

### 4.3 FastAPI Application

```python
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

app = FastAPI(
    title="OpenAustria RAG API",
    version="1.0.0",
    description="Dokumentationsplattform mit RAG und Gap-Analyse"
)

# --- Health ---

@app.get("/api/health", response_model=HealthResponse)
def health_check():
    ollama_ok = llm_service.health_check()
    return HealthResponse(
        status="healthy" if ollama_ok else "degraded",
        ollama=ollama_ok,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        database=True,
        vector_store=True,
    )

# --- Projects ---

@app.get("/api/projects", response_model=list[ProjectResponse])
def list_projects():
    return db.get_all_projects()

@app.post("/api/projects", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate):
    project = Project(
        id=str(uuid4()),
        name=data.name,
        description=data.description,
    )
    db.save_project(project)
    return project

@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    # Alle zugehoerigen Daten loeschen
    db.delete_project(project_id)
    vector_store.delete_project_collections(project_id)

# --- Query ---

@app.post("/api/projects/{project_id}/query", response_model=QueryResponse)
def query_project(project_id: str, data: QueryRequest):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status != "ready":
        raise HTTPException(400, "Project not indexed yet")

    result = query_engine.query(QueryContext(
        project_id=project_id,
        query=data.query,
        filters=data.filters,
        top_k=data.top_k,
    ))
    return QueryResponse(
        answer=result.answer,
        sources=[
            {
                "chunk_id": s.chunk_id,
                "content_preview": s.content[:200],
                "similarity": s.similarity_score,
                **s.metadata,
            }
            for s in result.sources
        ],
        query_type=result.query_type.value,
        token_count=result.token_count,
        retrieval_time_ms=result.retrieval_time_ms,
        generation_time_ms=result.generation_time_ms,
    )

@app.post("/api/projects/{project_id}/query/stream")
def query_project_stream(project_id: str, data: QueryRequest):
    """Server-Sent Events fuer Streaming-Antworten."""
    def event_generator():
        # Retrieval
        ctx = QueryContext(
            project_id=project_id, query=data.query,
            filters=data.filters, top_k=data.top_k,
        )
        # ... Retrieval + Context Assembly ...
        for token in llm_service.stream_generate(prompt):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'done': True, 'sources': [...]})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Sources ---

@app.post("/api/sources/{source_id}/sync", status_code=202)
def start_sync(source_id: str, background_tasks: BackgroundTasks):
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    background_tasks.add_task(run_ingestion, source)
    return {"message": "Sync started", "source_id": source_id}

# --- Gap Analysis ---

@app.post("/api/projects/{project_id}/gap-analysis", status_code=202)
def start_gap_analysis(project_id: str, background_tasks: BackgroundTasks):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    background_tasks.add_task(run_gap_analysis, project_id)
    return {"message": "Gap analysis started"}
```

---

## 5. Fehlerbehandlung (Frontend)

| Situation | Verhalten |
|---|---|
| Ollama nicht erreichbar | Banner: "Ollama laeuft nicht. Starte mit `ollama serve`." |
| Projekt hat keine Quellen | Hinweis: "Fuege zuerst eine Quelle hinzu." |
| Projekt nicht indexiert | Hinweis: "Starte die Synchronisierung fuer mindestens eine Quelle." |
| Chat ohne Ergebnis | "Keine relevanten Informationen gefunden. Versuche eine andere Formulierung." |
| Sync-Fehler | Fehlermeldung auf Quellen-Karte anzeigen, Retry-Button |
| Gap-Analyse laeuft lange | Fortschrittsbalken + geschaetzte Restzeit |

---

## 6. Testbarkeit

### 6.1 API Tests

```python
from fastapi.testclient import TestClient

client = TestClient(app)

def test_create_project():
    resp = client.post("/api/projects", json={"name": "test", "description": "Test project"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "test"

def test_query_requires_indexed_project():
    resp = client.post("/api/projects/unknown/query", json={"query": "test"})
    assert resp.status_code == 404

def test_health_check():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert "status" in resp.json()

def test_gap_analysis_returns_report():
    # Setup: Projekt mit indexierten Daten
    resp = client.post(f"/api/projects/{project_id}/gap-analysis")
    assert resp.status_code == 202
```

### 6.2 Frontend Tests

Streamlit-Seiten werden manuell getestet. Fuer automatisierte Tests:
- **Unit Tests** fuer Hilfsfunktionen (Filter, Formatierung)
- **Selenium/Playwright** fuer E2E-Tests (optional, Phase 2)
