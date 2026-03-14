# SPEC-04: RAG & Retrieval Layer

**Referenz:** MVP_KONZEPT.md (Lokale Variante)
**Version:** 1.0
**Datum:** 2026-03-14

---

## 1. Ueberblick

Diese Spezifikation beschreibt den Retrieval- und LLM-Layer: wie User-Queries verarbeitet werden, relevante Chunks aus der Vector DB geholt werden und wie das lokale LLM (Ollama + Mistral 7B) kontextbasierte Antworten generiert.

---

## 2. Query-Verarbeitungsfluss

```
User Query (Chat-Eingabe)
     |
     v
+---------------------------+
| 1. Query Analysis         |  Typ erkennen, Keywords extrahieren
+---------------------------+
     |
     v
+---------------------------+
| 2. Query Expansion        |  Optional: Synonyme, Uebersetzung
+---------------------------+
     |
     v
+---------------------------+
| 3. Embedding              |  Query → Vektor (Nomic Embed Text)
+---------------------------+
     |
     v
+---------------------------+
| 4. Retrieval              |  ChromaDB Similarity Search
+---------------------------+     + Metadaten-Filter
     |
     v
+---------------------------+
| 5. Re-Ranking             |  Relevanz-Sortierung
+---------------------------+
     |
     v
+---------------------------+
| 6. Context Assembly       |  Chunks + Prompt zusammenbauen
+---------------------------+
     |
     v
+---------------------------+
| 7. LLM Generation         |  Ollama / Mistral 7B
+---------------------------+
     |
     v
+---------------------------+
| 8. Response + Sources      |  Antwort + Quellenangaben
+---------------------------+
```

---

## 3. Query Engine

### 3.1 QueryEngine Klasse

```python
from dataclasses import dataclass
from enum import Enum

class QueryType(Enum):
    SEARCH = "search"           # Informationen suchen
    EXPLAIN = "explain"         # Code erklaeren
    COMPARE = "compare"         # Quellen vergleichen
    SUMMARIZE = "summarize"     # Zusammenfassung erstellen
    GAP_CHECK = "gap_check"     # Dokumentationsluecke pruefen

@dataclass
class QueryContext:
    project_id: str
    query: str
    query_type: QueryType = QueryType.SEARCH
    filters: dict = field(default_factory=dict)
    # filters:
    #   source_type: str | None     ("code", "documentation")
    #   language: str | None        ("java", "python")
    #   file_path: str | None       (Prefix-Match)
    #   connector: str | None       ("git", "confluence")
    top_k: int = 10
    include_sources: bool = True

@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    metadata: dict
    similarity_score: float     # 0.0 - 1.0 (1.0 = identisch)

@dataclass
class QueryResult:
    answer: str
    sources: list[RetrievedChunk]
    query_type: QueryType
    token_count: int            # Verbrauchte Tokens
    retrieval_time_ms: int
    generation_time_ms: int

class QueryEngine:
    """Verarbeitet User-Queries gegen die indexierten Dokumente."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        llm_service: LLMService,
        prompt_manager: PromptManager,
    ):
        self.embedding = embedding_service
        self.vector_store = vector_store
        self.llm = llm_service
        self.prompts = prompt_manager

    def query(self, ctx: QueryContext) -> QueryResult:
        """Fuehrt eine vollstaendige RAG-Query aus."""
        import time

        # 1. Query analysieren
        query_type = self._analyze_query(ctx.query) if ctx.query_type == QueryType.SEARCH else ctx.query_type

        # 2. Query fuer Embedding aufbereiten
        processed_query = EmbeddingPreprocessor.preprocess_query(ctx.query)

        # 3. Embedding erzeugen
        t0 = time.monotonic()
        query_embedding = self.embedding.embed_single(processed_query)

        # 4. Retrieval aus relevanten Collections
        retrieved = self._retrieve(ctx, query_embedding)
        retrieval_time = int((time.monotonic() - t0) * 1000)

        # 5. Re-Ranking
        ranked = self._rerank(retrieved, ctx.query)

        # 6. Context zusammenbauen
        context = self._assemble_context(ranked[:ctx.top_k])

        # 7. Prompt erstellen
        prompt = self.prompts.build_prompt(
            query_type=query_type,
            query=ctx.query,
            context=context,
        )

        # 8. LLM-Antwort generieren
        t1 = time.monotonic()
        answer = self.llm.generate(prompt)
        generation_time = int((time.monotonic() - t1) * 1000)

        return QueryResult(
            answer=answer,
            sources=ranked[:ctx.top_k],
            query_type=query_type,
            token_count=self.llm.last_token_count,
            retrieval_time_ms=retrieval_time,
            generation_time_ms=generation_time,
        )

    def _analyze_query(self, query: str) -> QueryType:
        """Erkennt den Query-Typ anhand von Keywords."""
        query_lower = query.lower()
        if any(w in query_lower for w in ["erklaer", "explain", "was macht", "how does"]):
            return QueryType.EXPLAIN
        if any(w in query_lower for w in ["vergleich", "compare", "unterschied", "difference"]):
            return QueryType.COMPARE
        if any(w in query_lower for w in ["zusammenfass", "summarize", "ueberblick", "overview"]):
            return QueryType.SUMMARIZE
        if any(w in query_lower for w in ["dokumentiert", "documented", "gap", "luecke", "fehlt"]):
            return QueryType.GAP_CHECK
        return QueryType.SEARCH

    def _retrieve(
        self,
        ctx: QueryContext,
        query_embedding: list[float],
    ) -> list[RetrievedChunk]:
        """Holt relevante Chunks aus ChromaDB."""
        # Bestimme welche Collections durchsucht werden
        collections_to_search = []
        if ctx.filters.get("source_type"):
            collections_to_search.append(
                f"{ctx.project_id}_{ctx.filters['source_type']}"
            )
        else:
            # Alle Collections des Projekts durchsuchen
            for content_type in ["code", "documentation", "specification", "config"]:
                collections_to_search.append(f"{ctx.project_id}_{content_type}")

        # ChromaDB where-Filter aufbauen
        where_filter = {}
        if ctx.filters.get("language"):
            where_filter["language"] = ctx.filters["language"]
        if ctx.filters.get("connector"):
            where_filter["connector"] = ctx.filters["connector"]

        all_results = []
        for coll_name in collections_to_search:
            try:
                results = self.vector_store.query(
                    collection=coll_name,
                    query_embedding=query_embedding,
                    top_k=ctx.top_k * 2,  # Mehr holen fuer Re-Ranking
                    where=where_filter if where_filter else None,
                )
                # ChromaDB gibt distances zurueck (cosine: 0 = identisch)
                for i in range(len(results["ids"][0])):
                    distance = results["distances"][0][i]
                    similarity = 1 - distance  # Cosine Distance → Similarity
                    all_results.append(RetrievedChunk(
                        chunk_id=results["ids"][0][i],
                        content=results["documents"][0][i],
                        metadata=results["metadatas"][0][i],
                        similarity_score=similarity,
                    ))
            except Exception as e:
                logger.warning(f"Error querying {coll_name}: {e}")

        return all_results

    def _rerank(
        self,
        chunks: list[RetrievedChunk],
        query: str,
    ) -> list[RetrievedChunk]:
        """Re-Ranking basierend auf Similarity + heuristische Faktoren."""
        for chunk in chunks:
            score = chunk.similarity_score

            # Bonus fuer exakte Keyword-Treffer
            query_words = set(query.lower().split())
            content_words = set(chunk.content.lower().split())
            keyword_overlap = len(query_words & content_words) / max(len(query_words), 1)
            score += keyword_overlap * 0.1

            # Bonus fuer Code wenn Query nach Code fragt
            if any(w in query.lower() for w in ["code", "methode", "klasse", "function", "class"]):
                if chunk.metadata.get("source_type") == "code":
                    score += 0.05

            # Bonus fuer Dokumentation wenn Query nach Doku fragt
            if any(w in query.lower() for w in ["doku", "doc", "beschreibung", "spezifikation"]):
                if chunk.metadata.get("source_type") == "documentation":
                    score += 0.05

            chunk.similarity_score = min(score, 1.0)

        # Sortierung: hoechste Similarity zuerst
        chunks.sort(key=lambda c: c.similarity_score, reverse=True)

        # Deduplizierung: Chunks mit >90% Content-Overlap entfernen
        seen_content_hashes = set()
        deduplicated = []
        for chunk in chunks:
            content_hash = hashlib.md5(chunk.content[:200].encode()).hexdigest()
            if content_hash not in seen_content_hashes:
                seen_content_hashes.add(content_hash)
                deduplicated.append(chunk)

        return deduplicated

    def _assemble_context(self, chunks: list[RetrievedChunk]) -> str:
        """Baut den Kontext-String fuer das LLM zusammen."""
        parts = []
        for i, chunk in enumerate(chunks, 1):
            source_info = chunk.metadata.get("file_path", "Unknown")
            element = chunk.metadata.get("element_name", "")
            source_type = chunk.metadata.get("source_type", "")

            header = f"[Quelle {i}: {source_type} - {source_info}"
            if element:
                header += f" ({element})"
            header += f" | Relevanz: {chunk.similarity_score:.2f}]"

            parts.append(f"{header}\n{chunk.content}")

        return "\n\n---\n\n".join(parts)
```

---

## 4. LLM Service (Ollama)

### 4.1 LLMService Klasse

```python
import requests
import json

class LLMService:
    """Kommuniziert mit Ollama REST API fuer Text-Generierung."""

    def __init__(
        self,
        model: str = "mistral",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        context_length: int = 8192,
    ):
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context_length = context_length
        self.last_token_count: int = 0

    def generate(self, prompt: str | list[dict]) -> str:
        """Generiert eine Antwort. Akzeptiert String oder Chat-Messages."""
        if isinstance(prompt, str):
            return self._generate_completion(prompt)
        return self._generate_chat(prompt)

    def _generate_completion(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.context_length,
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        self.last_token_count = data.get("eval_count", 0)
        return data["response"]

    def _generate_chat(self, messages: list[dict]) -> str:
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.context_length,
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        self.last_token_count = data.get("eval_count", 0)
        return data["message"]["content"]

    def stream_generate(self, prompt: str):
        """Streaming-Generierung fuer Chat-UI."""
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                    "num_ctx": self.context_length,
                },
            },
            stream=True,
            timeout=120,
        )
        resp.raise_for_status()
        total_tokens = 0
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                if not data.get("done", False):
                    yield data["response"]
                else:
                    total_tokens = data.get("eval_count", 0)
        self.last_token_count = total_tokens

    def health_check(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False
```

---

## 5. Prompt-Management

### 5.1 PromptManager

```python
class PromptManager:
    """Verwaltet und rendert Prompt-Templates fuer verschiedene Aufgaben."""

    TEMPLATES: dict[QueryType, str] = {
        QueryType.SEARCH: """Du bist ein hilfreicher Assistent fuer Software-Dokumentation.
Beantworte die Frage basierend auf dem bereitgestellten Kontext.
Wenn die Antwort nicht im Kontext enthalten ist, sage das ehrlich.
Referenziere die relevanten Quellen in deiner Antwort.

KONTEXT:
{context}

FRAGE: {query}

ANTWORT:""",

        QueryType.EXPLAIN: """Du bist ein erfahrener Software-Entwickler.
Erklaere den folgenden Code oder das Konzept verstaendlich.
Nutze den bereitgestellten Kontext fuer zusaetzliche Informationen.

KONTEXT:
{context}

ZU ERKLAEREN: {query}

ERKLAERUNG:""",

        QueryType.COMPARE: """Du bist ein Software-Analyst.
Vergleiche die folgenden Quellen und identifiziere Gemeinsamkeiten und Unterschiede.
Strukturiere deine Antwort klar.

KONTEXT:
{context}

VERGLEICHSAUFTRAG: {query}

VERGLEICH:""",

        QueryType.SUMMARIZE: """Du bist ein technischer Redakteur.
Erstelle eine praezise Zusammenfassung basierend auf dem Kontext.
Fokussiere dich auf die wichtigsten Punkte.

KONTEXT:
{context}

ZUSAMMENFASSUNGSAUFTRAG: {query}

ZUSAMMENFASSUNG:""",

        QueryType.GAP_CHECK: """Du bist ein Software-Qualitaetsanalyst.
Pruefe ob die im Kontext beschriebene Funktionalitaet dokumentiert ist.
Identifiziere fehlende oder unvollstaendige Dokumentation.

KONTEXT:
{context}

PRUEFAUFTRAG: {query}

ANALYSE:""",
    }

    def build_prompt(
        self,
        query_type: QueryType,
        query: str,
        context: str,
    ) -> str:
        template = self.TEMPLATES.get(query_type, self.TEMPLATES[QueryType.SEARCH])
        return template.format(query=query, context=context)

    def build_chat_messages(
        self,
        query_type: QueryType,
        query: str,
        context: str,
        chat_history: list[dict] | None = None,
    ) -> list[dict]:
        """Baut Chat-Messages-Format fuer Ollama Chat API."""
        system_msg = self._get_system_message(query_type)
        messages = [{"role": "system", "content": system_msg}]

        # Chat-History einfuegen (letzte N Nachrichten)
        if chat_history:
            for msg in chat_history[-6:]:  # Letzte 3 Austausche
                messages.append(msg)

        # Aktuelle Query mit Kontext
        user_msg = f"Kontext:\n{context}\n\nFrage: {query}"
        messages.append({"role": "user", "content": user_msg})

        return messages

    def _get_system_message(self, query_type: QueryType) -> str:
        system_msgs = {
            QueryType.SEARCH: "Du bist ein hilfreicher Assistent fuer Software-Dokumentation. Antworte praezise und referenziere Quellen.",
            QueryType.EXPLAIN: "Du bist ein erfahrener Entwickler. Erklaere Code und Konzepte verstaendlich.",
            QueryType.COMPARE: "Du bist ein Analyst. Vergleiche Quellen strukturiert und identifiziere Unterschiede.",
            QueryType.SUMMARIZE: "Du bist ein technischer Redakteur. Erstelle praezise Zusammenfassungen.",
            QueryType.GAP_CHECK: "Du bist ein Qualitaetsanalyst. Identifiziere Dokumentationsluecken.",
        }
        return system_msgs.get(query_type, system_msgs[QueryType.SEARCH])
```

### 5.2 Kontext-Budget-Management

```python
class ContextBudget:
    """Verwaltet das Token-Budget fuer Prompt + Kontext + Antwort."""

    def __init__(
        self,
        context_length: int = 8192,     # Mistral 7B: 8k default
        max_response_tokens: int = 2048,
        prompt_overhead: int = 512,      # System-Prompt + Template
    ):
        self.context_length = context_length
        self.max_response = max_response_tokens
        self.prompt_overhead = prompt_overhead

    @property
    def available_context_tokens(self) -> int:
        """Verfuegbare Tokens fuer Retrieved Context."""
        return self.context_length - self.max_response - self.prompt_overhead

    def fit_chunks(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Waehlt Chunks aus die ins Token-Budget passen."""
        budget = self.available_context_tokens
        selected = []
        used_tokens = 0

        for chunk in chunks:
            chunk_tokens = len(chunk.content) // 4  # Grobe Schaetzung
            if used_tokens + chunk_tokens > budget:
                break
            selected.append(chunk)
            used_tokens += chunk_tokens

        return selected
```

---

## 6. LlamaIndex Integration

### 6.1 Setup mit Ollama

```python
from llama_index.core import VectorStoreIndex, Settings
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

def setup_llamaindex(
    llm_model: str = "mistral",
    embedding_model: str = "nomic-embed-text",
    ollama_url: str = "http://localhost:11434",
    chroma_path: str = "data/chromadb",
    collection_name: str = "default",
):
    """Konfiguriert LlamaIndex mit Ollama und ChromaDB."""

    # LLM konfigurieren
    Settings.llm = Ollama(
        model=llm_model,
        base_url=ollama_url,
        temperature=0.1,
        request_timeout=120.0,
        context_window=8192,
    )

    # Embedding konfigurieren
    Settings.embed_model = OllamaEmbedding(
        model_name=embedding_model,
        base_url=ollama_url,
    )

    # ChromaDB Vector Store
    chroma_client = chromadb.PersistentClient(path=chroma_path)
    chroma_collection = chroma_client.get_or_create_collection(collection_name)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    # Index erstellen
    index = VectorStoreIndex.from_vector_store(vector_store)

    return index
```

### 6.2 Entscheidung: Custom QueryEngine vs. LlamaIndex QueryEngine

| Aspekt | Custom (SPEC-04) | LlamaIndex Built-in |
|---|---|---|
| Kontrolle | Volle Kontrolle ueber jeden Schritt | Abstrahiert, weniger Kontrolle |
| Re-Ranking | Eigene Logik moeglich | Plugin-basiert |
| Metadaten-Filter | Direkte ChromaDB-Abfragen | Via MetadataFilters |
| Multi-Collection | Einfach, mehrere Collections | Erfordert Sub-Index-Queries |
| Gap-Analyse Integration | Nahtlos | Eigene Retriever noetig |
| Debugging | Transparent | Schwerer zu debuggen |

**Empfehlung:** Eigene `QueryEngine` (wie oben spezifiziert) mit LlamaIndex als optionalem Beschleuniger fuer Standard-RAG-Queries. Die Gap-Analyse verwendet die Custom-Implementierung.

---

## 7. Caching

### 7.1 Query-Cache

```python
from functools import lru_cache
import hashlib

class QueryCache:
    """Cacht Embedding- und LLM-Ergebnisse um Rechenzeit zu sparen."""

    def __init__(self, max_size: int = 1000):
        self._embedding_cache: dict[str, list[float]] = {}
        self._llm_cache: dict[str, str] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0

    def get_embedding(self, text: str) -> list[float] | None:
        key = hashlib.sha256(text.encode()).hexdigest()
        result = self._embedding_cache.get(key)
        if result:
            self.hits += 1
        else:
            self.misses += 1
        return result

    def set_embedding(self, text: str, embedding: list[float]) -> None:
        if len(self._embedding_cache) >= self.max_size:
            # Aeltesten Eintrag entfernen (FIFO)
            oldest_key = next(iter(self._embedding_cache))
            del self._embedding_cache[oldest_key]
        key = hashlib.sha256(text.encode()).hexdigest()
        self._embedding_cache[key] = embedding

    def get_llm_response(self, prompt_hash: str) -> str | None:
        return self._llm_cache.get(prompt_hash)

    def set_llm_response(self, prompt_hash: str, response: str) -> None:
        if len(self._llm_cache) >= self.max_size:
            oldest_key = next(iter(self._llm_cache))
            del self._llm_cache[oldest_key]
        self._llm_cache[prompt_hash] = response
```

---

## 8. Fehlerbehandlung

| Fehler | Verhalten |
|---|---|
| Ollama nicht erreichbar | Benutzerfreundliche Fehlermeldung: "Ollama laeuft nicht. Bitte starten." |
| Modell nicht geladen | Automatischer `ollama pull` Versuch, dann Fehlermeldung |
| Timeout bei Generierung | 120s Timeout, dann Abbruch mit Teilantwort |
| Leerer Kontext (keine Chunks gefunden) | Antwort ohne RAG-Kontext, Hinweis an User |
| ChromaDB Collection leer | Hinweis: "Projekt noch nicht indexiert" |
| Token-Limit ueberschritten | Kontext automatisch kuerzen (ContextBudget) |

---

## 9. Testbarkeit

```python
class TestQueryEngine:
    def test_query_type_detection(self):
        engine = QueryEngine(...)
        assert engine._analyze_query("Erklaere die UserService Klasse") == QueryType.EXPLAIN
        assert engine._analyze_query("Was macht die createUser Methode?") == QueryType.EXPLAIN
        assert engine._analyze_query("Vergleiche Code und Doku") == QueryType.COMPARE
        assert engine._analyze_query("Ist resetPassword dokumentiert?") == QueryType.GAP_CHECK

    def test_context_budget_limits_chunks(self):
        budget = ContextBudget(context_length=4096, max_response_tokens=1024)
        large_chunks = [
            RetrievedChunk(chunk_id=str(i), content="x" * 2000, metadata={}, similarity_score=0.9)
            for i in range(10)
        ]
        fitted = budget.fit_chunks(large_chunks)
        total_tokens = sum(len(c.content) // 4 for c in fitted)
        assert total_tokens <= budget.available_context_tokens

    def test_reranking_boosts_keyword_matches(self):
        engine = QueryEngine(...)
        chunks = [
            RetrievedChunk("1", "def create_user(): ...", {"source_type": "code"}, 0.8),
            RetrievedChunk("2", "The system manages users", {"source_type": "documentation"}, 0.85),
        ]
        ranked = engine._rerank(chunks, "create_user code")
        # Code-Chunk mit Keyword-Match sollte hoeher ranken
        assert ranked[0].chunk_id == "1"

    def test_empty_retrieval_returns_helpful_message(self):
        # Wenn keine Chunks gefunden werden, soll das LLM trotzdem antworten
        pass

class TestLLMService:
    def test_health_check_returns_false_when_ollama_down(self):
        svc = LLMService(base_url="http://localhost:99999")
        assert svc.health_check() is False

    def test_streaming_yields_tokens(self):
        svc = LLMService()
        tokens = list(svc.stream_generate("Hello"))
        assert len(tokens) > 0
        assert all(isinstance(t, str) for t in tokens)
```
