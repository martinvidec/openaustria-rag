"""FastAPI REST API (SPEC-06 Section 4)."""

import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from ..analysis.gap_analyzer import FalsePositiveManager, GapAnalyzer, GapReportExporter
from ..config import get_settings
from ..db import MetadataDB
from ..ingestion.chunking import ChunkingService
from ..ingestion.code_parser import CodeParser
from ..ingestion.embedding_service import EmbeddingService
from ..ingestion.pipeline import IngestionPipeline, run_sync
from ..llm.ollama_client import LLMService
from ..llm.prompts import ContextBudget, QueryType
from ..models import (
    ChatMessage,
    MessageRole,
    Project,
    ProjectStatus,
    Source,
    SourceType,
)
from ..retrieval.query_engine import QueryContext, QueryEngine
from ..retrieval.vector_store import VectorStoreService
from .schemas import (
    FalsePositiveUpdate,
    GapReportResponse,
    HealthResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    QueryRequest,
    QueryResponse,
    SettingsResponse,
    SourceCreate,
    SourceResponse,
    SyncStatus,
)


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(title="OpenAustria RAG", version="0.1.0")
    settings = get_settings()

    # Initialize services
    db = MetadataDB()
    vector_store = VectorStoreService()
    embedding_service = EmbeddingService()
    llm_service = LLMService()
    code_parser = CodeParser()
    chunking_service = ChunkingService()
    pipeline = IngestionPipeline(
        db=db,
        code_parser=code_parser,
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    query_engine = QueryEngine(
        embedding_service=embedding_service,
        vector_store=vector_store,
        llm_service=llm_service,
    )

    # --- Projects ---

    @app.get("/api/projects", response_model=list[ProjectResponse])
    def list_projects():
        projects = db.get_all_projects()
        return [_project_to_response(p) for p in projects]

    @app.post("/api/projects", response_model=ProjectResponse, status_code=201)
    def create_project(body: ProjectCreate):
        project = Project(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            settings=body.settings,
        )
        db.save_project(project)
        return _project_to_response(project)

    @app.get("/api/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: str):
        project = db.get_project(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        return _project_to_response(project)

    @app.put("/api/projects/{project_id}", response_model=ProjectResponse)
    def update_project(project_id: str, body: ProjectUpdate):
        project = db.get_project(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        if body.name is not None:
            project.name = body.name
        if body.description is not None:
            project.description = body.description
        if body.settings is not None:
            project.settings = body.settings
        project.updated_at = datetime.now(UTC)
        db.save_project(project)
        return _project_to_response(project)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str):
        project = db.get_project(project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        # Delete vector collections
        for ct in ["code", "documentation", "specification", "config"]:
            col_name = vector_store.collection_name(project_id, ct)
            if col_name in vector_store.list_collections():
                vector_store.delete_collection(col_name)
        db.delete_project(project_id)

    # --- Sources ---

    @app.get("/api/projects/{project_id}/sources", response_model=list[SourceResponse])
    def list_sources(project_id: str):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")
        sources = db.get_sources_by_project(project_id)
        return [_source_to_response(s) for s in sources]

    @app.post("/api/projects/{project_id}/sources", response_model=SourceResponse, status_code=201)
    def create_source(project_id: str, body: SourceCreate):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")
        source = Source(
            id=str(uuid.uuid4()),
            project_id=project_id,
            source_type=SourceType(body.source_type),
            name=body.name,
            config=body.config,
        )
        db.save_source(source)
        return _source_to_response(source)

    @app.delete("/api/sources/{source_id}", status_code=204)
    def delete_source(source_id: str):
        source = db.get_source(source_id)
        if not source:
            raise HTTPException(404, "Source not found")
        db.delete_source(source_id)

    @app.post("/api/sources/{source_id}/sync", status_code=202)
    def start_sync(source_id: str, background_tasks: BackgroundTasks):
        source = db.get_source(source_id)
        if not source:
            raise HTTPException(404, "Source not found")
        project = db.get_project(source.project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        background_tasks.add_task(run_sync, source, project, db, pipeline)
        return {"message": "Sync started", "source_id": source_id}

    @app.get("/api/sources/{source_id}/status", response_model=SyncStatus)
    def get_sync_status(source_id: str):
        source = db.get_source(source_id)
        if not source:
            raise HTTPException(404, "Source not found")
        return SyncStatus(
            source_id=source.id,
            status=source.status.value,
            error_message=source.error_message,
            last_sync_at=source.last_sync_at.isoformat() if source.last_sync_at else None,
        )

    @app.post("/api/sources/{source_id}/test")
    def test_connection(source_id: str):
        source = db.get_source(source_id)
        if not source:
            raise HTTPException(404, "Source not found")
        from ..connectors.base import ConnectorRegistry
        try:
            connector = ConnectorRegistry.create(
                source.source_type.value, source.id, source.config
            )
            success = connector.test_connection()
            return {"success": success}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Chat / Query ---

    @app.post("/api/projects/{project_id}/query", response_model=QueryResponse)
    def query_project(project_id: str, body: QueryRequest):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")

        # Load chat history if session provided
        chat_history = None
        if body.session_id:
            msgs = db.get_chat_history(body.session_id)
            chat_history = [
                {"role": m.role.value, "content": m.content} for m in msgs
            ]

        qt = QueryType(body.query_type) if body.query_type else None
        ctx = QueryContext(
            project_id=project_id,
            query=body.query,
            query_type=qt,
            top_k=body.top_k,
            filters=body.filters,
            chat_history=chat_history,
        )
        try:
            result = query_engine.query(ctx)
        except Exception as e:
            raise HTTPException(503, f"LLM query failed: {e}")

        # Save to chat history
        if body.session_id:
            db.save_chat_message(ChatMessage(
                id=str(uuid.uuid4()),
                project_id=project_id,
                session_id=body.session_id,
                role=MessageRole.USER,
                content=body.query,
            ))
            db.save_chat_message(ChatMessage(
                id=str(uuid.uuid4()),
                project_id=project_id,
                session_id=body.session_id,
                role=MessageRole.ASSISTANT,
                content=result.answer,
                sources=[c.id for c in result.chunks],
            ))

        return QueryResponse(
            answer=result.answer,
            query_type=result.query_type.value,
            sources=[
                {
                    "id": c.id,
                    "file_path": c.file_path,
                    "element_name": c.element_name,
                    "score": round(c.score, 3),
                    "content_preview": c.content[:200],
                }
                for c in result.chunks
            ],
            retrieval_time_ms=round(result.retrieval_time_ms, 1),
            generation_time_ms=round(result.generation_time_ms, 1),
            token_count=result.token_count,
        )

    @app.post("/api/projects/{project_id}/query/stream")
    def query_project_stream(project_id: str, body: QueryRequest):
        """Streaming query via Server-Sent Events."""
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")

        import json as _json
        import time as _time

        qt = QueryType(body.query_type) if body.query_type else None

        def event_stream():
            from ..ingestion.embedding_service import EmbeddingPreprocessor as _EP

            t0 = _time.monotonic()

            # Retrieve
            preprocessed = _EP.preprocess_query(body.query)
            query_embedding = embedding_service.embed_single(preprocessed)

            from ..retrieval.query_engine import CONTENT_TYPES
            all_chunks = []
            for ct in CONTENT_TYPES:
                col_name = vector_store.collection_name(project_id, ct)
                if col_name not in vector_store.list_collections():
                    continue
                col = vector_store.get_or_create_collection(col_name)
                if col.count() == 0:
                    continue
                result = vector_store.query(col, query_embedding, top_k=body.top_k)
                ids = result.get("ids", [[]])[0]
                docs = result.get("documents", [[]])[0]
                dists = result.get("distances", [[]])[0]
                metas = result.get("metadatas", [[]])[0]
                for i, cid in enumerate(ids):
                    score = 1.0 - (dists[i] / 2.0) if i < len(dists) else 0.0
                    all_chunks.append({
                        "id": cid, "content": docs[i], "score": score,
                        "file_path": metas[i].get("file_path", "") if i < len(metas) else "",
                        "source_type": ct,
                    })

            # Sort by score descending — best matches first regardless of collection
            all_chunks.sort(key=lambda c: c["score"], reverse=True)

            retrieval_ms = (_time.monotonic() - t0) * 1000

            # Send sources event (top chunks after sorting)
            top_chunks = all_chunks[:body.top_k]
            yield f"data: {_json.dumps({'type': 'sources', 'sources': [{'file_path': c['file_path'], 'source_type': c['source_type'], 'score': round(c['score'], 3)} for c in top_chunks], 'retrieval_time_ms': round(retrieval_ms, 1)})}\n\n"

            # Assemble context with budget
            context_parts = []
            budget = query_engine.context_budget.available_context_tokens
            used = 0
            for c in top_chunks:
                ct = len(c["content"]) // 4
                if used + ct > budget:
                    break
                context_parts.append(c["content"])
                used += ct
            context = "\n\n---\n\n".join(context_parts) or "(Kein Kontext)"

            # Build prompt
            query_type = qt or query_engine._analyze_query(body.query)
            from ..llm.prompts import PromptManager
            prompt = PromptManager.build_prompt(query_type, body.query, context)

            # Stream LLM tokens
            t1 = _time.monotonic()
            token_count = 0
            for token in llm_service.stream_generate(prompt):
                token_count += 1
                yield f"data: {_json.dumps({'type': 'token', 'content': token})}\n\n"

            gen_ms = (_time.monotonic() - t1) * 1000
            tps = token_count / (gen_ms / 1000) if gen_ms > 0 else 0

            yield f"data: {_json.dumps({'type': 'done', 'token_count': token_count, 'generation_time_ms': round(gen_ms, 1), 'tokens_per_second': round(tps, 1)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/projects/{project_id}/chat/history")
    def get_chat_history(project_id: str, session_id: str):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")
        msgs = db.get_chat_history(session_id)
        return [
            {
                "id": m.id,
                "role": m.role.value,
                "content": m.content,
                "sources": m.sources,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ]

    @app.delete("/api/projects/{project_id}/chat/history", status_code=204)
    def delete_chat_history(project_id: str, session_id: str):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")
        db._conn.execute(
            "DELETE FROM chat_messages WHERE project_id = ? AND session_id = ?",
            (project_id, session_id),
        )
        db._conn.commit()

    # --- Gap Analysis ---

    @app.post("/api/projects/{project_id}/gap-analysis", status_code=202)
    def start_gap_analysis(project_id: str, background_tasks: BackgroundTasks):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")

        def run_analysis():
            import logging
            log = logging.getLogger("openaustria_rag.gap_analysis")
            try:
                log.info(f"Starting gap analysis for project {project_id}")
                analyzer = GapAnalyzer(
                    db=db,
                    vector_store=vector_store,
                    embedding_service=embedding_service,
                    llm_service=llm_service,
                    run_llm_analysis=False,
                )
                report = analyzer.analyze(project_id)
                log.info(
                    f"Gap analysis complete: {report.summary.total_code_elements} elements, "
                    f"{report.summary.undocumented} undocumented, "
                    f"{report.summary.divergent} divergent"
                )
            except Exception:
                log.exception(f"Gap analysis failed for project {project_id}")

        background_tasks.add_task(run_analysis)
        return {"message": "Gap analysis started", "project_id": project_id}

    @app.get("/api/projects/{project_id}/gap-analysis/latest")
    def get_latest_gap_report(project_id: str):
        if not db.get_project(project_id):
            raise HTTPException(404, "Project not found")
        report = db.get_latest_gap_report(project_id)
        if not report:
            raise HTTPException(404, "No gap report found")
        return {
            "id": report.id,
            "project_id": report.project_id,
            "created_at": report.created_at.isoformat(),
            "summary": asdict(report.summary),
            "gaps": [
                {
                    "id": g.id,
                    "gap_type": g.gap_type.value,
                    "severity": g.severity.value,
                    "code_element_name": g.code_element_name,
                    "file_path": g.file_path,
                    "line": g.line,
                    "doc_reference": g.doc_reference,
                    "similarity_score": g.similarity_score,
                    "divergence_description": g.divergence_description,
                    "recommendation": g.recommendation,
                    "is_false_positive": g.is_false_positive,
                }
                for g in report.gaps
            ],
        }

    @app.get("/api/gap-reports/{report_id}/export/{fmt}")
    def export_gap_report(report_id: str, fmt: str):
        # Find report across all projects
        row = db._conn.execute(
            "SELECT project_id FROM gap_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Report not found")
        report = db.get_latest_gap_report(row["project_id"])
        if not report or report.id != report_id:
            raise HTTPException(404, "Report not found")

        if fmt == "json":
            return JSONResponse(
                content=__import__("json").loads(GapReportExporter.to_json(report)),
                media_type="application/json",
            )
        elif fmt == "csv":
            return StreamingResponse(
                iter([GapReportExporter.to_csv(report)]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=gap_report_{report_id}.csv"},
            )
        raise HTTPException(400, f"Unsupported format: {fmt}")

    @app.put("/api/gap-items/{item_id}/false-positive")
    def update_false_positive(item_id: str, body: FalsePositiveUpdate):
        mgr = FalsePositiveManager(db)
        if body.is_false_positive:
            mgr.mark_false_positive(item_id)
        else:
            mgr.unmark_false_positive(item_id)
        return {"id": item_id, "is_false_positive": body.is_false_positive}

    # --- System ---

    @app.get("/api/health", response_model=HealthResponse)
    def health_check():
        ollama_ok = llm_service.health_check()
        embedding_ok = embedding_service.health_check()
        return HealthResponse(
            status="ok" if ollama_ok else "degraded",
            ollama_available=ollama_ok,
            embedding_model_available=embedding_ok,
            database_ok=True,
        )

    @app.get("/api/settings", response_model=SettingsResponse)
    def get_settings_endpoint():
        s = get_settings()
        return SettingsResponse(
            ollama={"base_url": s.ollama.base_url, "model": s.ollama.model, "temperature": s.ollama.temperature},
            embedding={"model": s.embedding.model, "dimensions": s.embedding.dimensions},
            chunking={"code_max_tokens": s.chunking.code_max_tokens, "doc_max_tokens": s.chunking.doc_max_tokens},
            vector_store={"persist_path": s.vector_store.persist_path, "distance_metric": s.vector_store.distance_metric},
            gap_analysis={"name_similarity_threshold": s.gap_analysis.name_similarity_threshold},
        )

    return app


def _project_to_response(p: Project) -> ProjectResponse:
    return ProjectResponse(
        id=p.id,
        name=p.name,
        description=p.description,
        status=p.status.value,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
        settings=p.settings,
    )


def _source_to_response(s: Source) -> SourceResponse:
    return SourceResponse(
        id=s.id,
        project_id=s.project_id,
        source_type=s.source_type.value,
        name=s.name,
        config=s.config,
        status=s.status.value,
        last_sync_at=s.last_sync_at.isoformat() if s.last_sync_at else None,
        error_message=s.error_message,
        created_at=s.created_at.isoformat(),
    )
