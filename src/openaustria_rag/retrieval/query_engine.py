"""RAG query engine (SPEC-04 Sections 3, 6, 7)."""

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from ..ingestion.embedding_service import EmbeddingPreprocessor, EmbeddingService
from ..llm.ollama_client import LLMService
from ..llm.prompts import ContextBudget, PromptManager, QueryType
from .vector_store import VectorStoreService

logger = logging.getLogger(__name__)

# Keywords for query type detection (German)
_TYPE_KEYWORDS: dict[QueryType, list[str]] = {
    QueryType.EXPLAIN: ["erkläre", "erklär", "erklaere", "was ist", "was bedeutet", "wie funktioniert"],
    QueryType.COMPARE: ["vergleiche", "unterschied", "gemeinsamkeit", "vs", "versus"],
    QueryType.SUMMARIZE: ["zusammenfassung", "fasse zusammen", "überblick", "ueberblick"],
    QueryType.GAP_CHECK: ["dokumentiert", "dokumentation fehlt", "undokumentiert", "gap", "lücke", "luecke"],
}

CONTENT_TYPES = ["code", "documentation", "specification", "config"]


@dataclass
class QueryContext:
    project_id: str
    query: str
    query_type: QueryType | None = None
    top_k: int = 10
    filters: dict | None = None
    chat_history: list[dict] | None = None


@dataclass
class RetrievedChunk:
    id: str
    content: str
    score: float
    file_path: str = ""
    element_name: str = ""
    source_type: str = ""
    language: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class QueryResult:
    answer: str
    query_type: QueryType
    chunks: list[RetrievedChunk] = field(default_factory=list)
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    token_count: int = 0


class QueryCache:
    """Simple FIFO cache for embeddings and LLM responses."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._cache: OrderedDict[str, object] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str):
        key = self._key(text)
        if key in self._cache:
            self.hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self.misses += 1
        return None

    def put(self, text: str, value):
        key = self._key(text)
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self.max_size:
            self._cache.popitem(last=False)


class QueryEngine:
    """Full RAG pipeline: analyze → embed → retrieve → rerank → generate."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStoreService,
        llm_service: LLMService,
        context_budget: ContextBudget | None = None,
    ):
        self.embedding = embedding_service
        self.vector_store = vector_store
        self.llm = llm_service
        self.context_budget = context_budget or ContextBudget()
        self.embedding_cache = QueryCache()

    def query(self, ctx: QueryContext) -> QueryResult:
        """Execute the full RAG pipeline."""
        # 1. Analyze query type
        query_type = ctx.query_type or self._analyze_query(ctx.query)

        # 2. Embed query
        t0 = time.monotonic()
        cached = self.embedding_cache.get(ctx.query)
        if cached is not None:
            query_embedding = cached
        else:
            preprocessed = EmbeddingPreprocessor.preprocess_query(ctx.query)
            query_embedding = self.embedding.embed_single(preprocessed)
            self.embedding_cache.put(ctx.query, query_embedding)

        # 3. Retrieve from multiple collections
        raw_chunks = self._retrieve(
            ctx.project_id, query_embedding, ctx.top_k, ctx.filters
        )
        retrieval_ms = (time.monotonic() - t0) * 1000

        # 4. Rerank
        reranked = self._rerank(raw_chunks, ctx.query)

        # 5. Fit to context budget
        fitted = self.context_budget.fit_chunks(reranked)

        # 6. Assemble context
        context_text = self._assemble_context(fitted)

        # 7. Generate LLM response
        t1 = time.monotonic()
        if ctx.chat_history:
            messages = PromptManager.build_chat_messages(
                query_type, ctx.query, context_text, ctx.chat_history
            )
            answer = self.llm.generate(messages)
        else:
            prompt = PromptManager.build_prompt(query_type, ctx.query, context_text)
            answer = self.llm.generate(prompt)
        generation_ms = (time.monotonic() - t1) * 1000

        answer = _sanitize_links(answer, context_text)

        return QueryResult(
            answer=answer,
            query_type=query_type,
            chunks=fitted,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=generation_ms,
            token_count=self.llm.last_token_count,
        )

    def _analyze_query(self, query: str) -> QueryType:
        """Detect query type from keywords."""
        query_lower = query.lower()
        for qt, keywords in _TYPE_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                return qt
        return QueryType.SEARCH

    def _retrieve(
        self,
        project_id: str,
        query_embedding: list[float],
        top_k: int,
        filters: dict | None,
    ) -> list[RetrievedChunk]:
        """Search across all content type collections."""
        all_chunks: list[RetrievedChunk] = []

        for ct in CONTENT_TYPES:
            col_name = self.vector_store.collection_name(project_id, ct)
            if col_name not in self.vector_store.list_collections():
                continue

            collection = self.vector_store.get_or_create_collection(col_name)
            if collection.count() == 0:
                continue

            result = self.vector_store.query(
                collection, query_embedding, top_k=top_k, where=filters
            )

            ids = result.get("ids", [[]])[0]
            docs = result.get("documents", [[]])[0]
            dists = result.get("distances", [[]])[0]
            metas = result.get("metadatas", [[]])[0]

            for i, chunk_id in enumerate(ids):
                # ChromaDB cosine distance: 0 = identical, 2 = opposite
                # Convert to similarity: 1 - (distance / 2)
                score = 1.0 - (dists[i] / 2.0)
                meta = metas[i] if i < len(metas) else {}
                all_chunks.append(RetrievedChunk(
                    id=chunk_id,
                    content=docs[i],
                    score=score,
                    file_path=meta.get("file_path", ""),
                    element_name=meta.get("element_name", ""),
                    source_type=meta.get("source_type", ct),
                    language=meta.get("language", ""),
                    metadata=meta,
                ))

        return all_chunks

    def _rerank(
        self, chunks: list[RetrievedChunk], query: str
    ) -> list[RetrievedChunk]:
        """Rerank chunks with keyword bonus and deduplication."""
        query_words = set(query.lower().split())

        for chunk in chunks:
            # Keyword bonus
            content_lower = chunk.content.lower()
            keyword_hits = sum(1 for w in query_words if w in content_lower)
            chunk.score += keyword_hits * 0.02

            # Source type bonus (documentation slightly preferred for search)
            if chunk.source_type == "documentation":
                chunk.score += 0.01

        # Deduplicate by content hash
        seen: set[str] = set()
        unique: list[RetrievedChunk] = []
        for chunk in chunks:
            content_key = hashlib.md5(chunk.content.encode()).hexdigest()
            if content_key not in seen:
                seen.add(content_key)
                unique.append(chunk)

        # Sort by score descending
        unique.sort(key=lambda c: c.score, reverse=True)
        return unique

    @staticmethod
    def _assemble_context(chunks: list[RetrievedChunk]) -> str:
        """Build context string with source headers."""
        if not chunks:
            return "(Kein relevanter Kontext gefunden)"

        parts = []
        for i, chunk in enumerate(chunks, 1):
            source_info = chunk.file_path
            if chunk.element_name:
                source_info += f" ({chunk.element_name})"
            parts.append(f"[Quelle {i}: {source_info}]\n{chunk.content}")

        return "\n\n---\n\n".join(parts)


def _sanitize_links(answer: str, context: str) -> str:
    """Remove or flag URLs in the answer that don't appear in the context."""
    import re
    url_pattern = re.compile(r'https?://[^\s\)\]>\"\']+')

    context_urls = set(url_pattern.findall(context))

    def check_url(match):
        url = match.group(0)
        # Check if URL (or a prefix of it) exists in context
        for ctx_url in context_urls:
            if url.startswith(ctx_url) or ctx_url.startswith(url):
                return url
        # Hallucinated — remove the link but keep descriptive text
        return f"~~{url}~~ *(Link nicht verifiziert)*"

    return url_pattern.sub(check_url, answer)
