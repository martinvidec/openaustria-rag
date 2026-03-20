# Analyse: User-Feedback bei langlaufenden Prozessen

## 1. Inventar: Alle Interaktionspunkte mit langlaufenden Prozessen

### 1.1 Quellen-Sync (04_Quellen.py)
| Eigenschaft | Wert |
|---|---|
| **Trigger** | "Sync"-Button pro Quelle |
| **Backend** | `POST /api/sources/{id}/sync` → `run_sync()` als BackgroundTask |
| **Dauer** | 10s - 30min+ (abhaengig von Repo-Groesse, Connector-Typ) |
| **Ist-Feedback** | `st.info("Sync gestartet...")` + Status-Icon wechselt auf syncing |
| **Fehlend** | Kein Fortschritt, kein Auto-Refresh |

### 1.2 Verbindungstest (04_Quellen.py)
| Eigenschaft | Wert |
|---|---|
| **Trigger** | "Test"-Button pro Quelle |
| **Backend** | `POST /api/sources/{id}/test` (synchron) |
| **Dauer** | 5-30s |
| **Ist-Feedback** | Keins waehrend Warten |
| **Fehlend** | Kein Spinner waehrend Test |

### 1.3 Gap-Analyse (03_Gap_Analyse.py)
| Eigenschaft | Wert |
|---|---|
| **Trigger** | "Analyse starten"-Button |
| **Backend** | `POST /api/projects/{id}/gap-analysis` → BackgroundTask |
| **Dauer** | 5s - 15min |
| **Ist-Feedback** | Progress-Bar mit Stage-Label, Auto-Refresh |
| **Fehlend** | Keine Zeitschaetzung, kein Abbruch |

### 1.4 Chat — Blocking-Modus (02_Chat.py)
| Eigenschaft | Wert |
|---|---|
| **Trigger** | Chat-Input bei deaktiviertem Streaming |
| **Dauer** | 0.5-5s |
| **Ist-Feedback** | `st.spinner("Suche und generiere Antwort...")` |
| **Fehlend** | Kein Phasen-Feedback |

### 1.5 Chat — Streaming-Modus (02_Chat.py)
| Eigenschaft | Wert |
|---|---|
| **Trigger** | Chat-Input bei aktiviertem Streaming |
| **Dauer** | 0.5-5s |
| **Ist-Feedback** | Sources-Event → Token-Streaming |
| **Fehlend** | Kein Indikator waehrend Retrieval-Phase |

### 1.6-1.8 Projekt erstellen / Loeschen / Settings
Dauer unter 200ms — kein Handlungsbedarf.

---

## 2. Bewertungsmatrix

| # | Interaktion | Dauer | Ist-Feedback | Handlungsbedarf | Prioritaet |
|---|---|---|---|---|---|
| 1.1 | **Quellen-Sync** | 10s - 30min | Minimal | **HOCH** | **P0** |
| 1.2 | **Verbindungstest** | 5-30s | Keins | **MITTEL** | **P1** |
| 1.3 | **Gap-Analyse** | 5s - 15min | Gut | **NIEDRIG** | **P2** |
| 1.4 | **Chat Blocking** | 0.5-5s | Spinner | **NIEDRIG** | **P3** |
| 1.5 | **Chat Streaming** | 0.5-5s | Gut | **MINIMAL** | **P3** |

---

## 3. Bestehende Patterns zur Wiederverwendung

| Pattern | Wo implementiert | Wiederverwendbar fuer |
|---|---|---|
| In-memory Status Dict + Lock | `api.py` (Gap-Analyse) | Sync-Fortschritt |
| Progress Callback | `gap_analyzer.py` | Ingestion Pipeline |
| Auto-Refresh Fragment `@st.fragment` | `03_Gap_Analyse.py` | Quellen-Seite Sync |
| SSE Streaming | `api.py` (Chat) | Alternative fuer Sync |
| BackgroundTasks | `api.py` (Sync) | Bereits vorhanden |
| `IngestionResult` Dataclass | `pipeline.py` | Sync-Fortschritt Daten |
| `ConnectorProgress` Dataclass | `connectors/base.py` | Connector-Phase Tracking |

---

## 4. Zusammenfassung & Empfehlung

### Sofort umsetzbar (Quick Wins):
1. **Spinner fuer Verbindungstest** — `st.spinner()` um API-Call
2. **Retrieval-Phase-Indikator im Chat** — Status-Text vor Sources-Event

### Mittlerer Aufwand:
3. **Sync-Fortschritt** — Progress-Callback in Pipeline + In-memory Status + Auto-Refresh

### Nice-to-have:
4. **Gap-Analyse ETA + Abbruch**
5. **Chat Blocking-Modus Phasen-Feedback**
