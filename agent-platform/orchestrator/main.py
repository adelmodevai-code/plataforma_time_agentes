"""
Agent Platform — Python Orchestrator
FastAPI + SSE streaming para o Go Gateway.
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from memory.redis_client import memory
from memory.qdrant_memory import vector_memory
from messaging.alert_broadcaster import alert_broadcaster
from messaging.metatron_archiver import metatron_archiver
from messaging.nats_bus import nats_bus
from models.messages import InboundRequest, StreamEvent, EventType, AgentName, FeedbackRequest
from memory.qdrant_memory import make_point_id
from router.agent_router import AgentRouter
from storage.file_storage import StorageError, file_storage
from utils.retry import connect_with_retry

log = structlog.get_logger(__name__)

# Métricas Prometheus
REQUEST_COUNT = Counter(
    "orchestrator_requests_total",
    "Total de requisições processadas",
    ["agent", "type"],
)
REQUEST_DURATION = Histogram(
    "orchestrator_request_duration_seconds",
    "Duração das requisições",
    ["agent"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: conecta/desconecta recursos ao iniciar/parar."""
    log.info("🚀 Orchestrator iniciando...")
    await connect_with_retry(memory.connect, "Redis")
    await connect_with_retry(vector_memory.connect, "Qdrant")
    metatron_archiver.register()   # registra subscriber ANTES do connect
    await connect_with_retry(nats_bus.connect, "NATS")
    alert_broadcaster.start()
    log.info("✅ Orchestrator pronto — Redis, Qdrant, NATS, AlertBroadcaster e MetatronArchiver ativos.")
    yield
    log.info("🔻 Orchestrator encerrando...")
    await alert_broadcaster.stop()
    await nats_bus.disconnect()
    await memory.disconnect()
    await vector_memory.disconnect()


app = FastAPI(
    title="Agent Platform Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = AgentRouter()


@app.get("/health")
async def health():
    qdrant_info = await vector_memory.collection_info()
    return {
        "status": "ok",
        "service": "orchestrator",
        "active_agents": [a.value for a in AgentRouter.ACTIVE_AGENTS],
        "memory": {
            "redis": "connected",
            "qdrant": "connected" if vector_memory.available else "unavailable",
            "qdrant_collection": qdrant_info,
        },
        "messaging": {
            "nats": "connected" if nats_bus.available else "unavailable",
        },
    }


@app.get("/memory/stats")
async def memory_stats():
    """Estatísticas da memória vetorial."""
    info = await vector_memory.collection_info()
    return {
        "qdrant_available": vector_memory.available,
        "collection": info,
    }


@app.get("/metrics")
async def metrics():
    """Endpoint de métricas para o Prometheus."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/agents/status")
async def agents_status():
    """Status de cada agente."""
    agents = [
        {"name": "Beholder",  "status": "online",  "role": "Observabilidade e sentinela", "phase": 1},
        {"name": "Metatron",  "status": "online",  "role": "Documentação (sob demanda)",  "phase": 1},
        {"name": "LogicX",   "status": "online",  "role": "Análise e decisão",            "phase": 3},
        {"name": "Vops",     "status": "online",  "role": "Infraestrutura k8s",           "phase": 3},
        {"name": "CyberT",   "status": "online",  "role": "Segurança e auditoria",        "phase": 4},
        {"name": "Zerocool", "status": "online",  "role": "Pentesting autorizado",        "phase": 4},
    ]
    return {"agents": agents}


@app.get("/files/{file_path:path}")
async def serve_file(file_path: str):
    """
    Serve arquivos gerados pelo Metatron.
    file_path = "session_id/filename.md"
    """
    try:
        resolved = file_storage.resolve_for_serving(file_path)
    except StorageError as e:
        raise HTTPException(status_code=404, detail=str(e))

    suffix = resolved.suffix.lower()
    media_type_map = {
        ".md":   "text/markdown; charset=utf-8",
        ".txt":  "text/plain; charset=utf-8",
        ".json": "application/json",
    }
    media_type = media_type_map.get(suffix, "application/octet-stream")
    disposition = "inline" if suffix in (".md", ".txt") else "attachment"

    return FileResponse(
        path=resolved,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{resolved.name}"'},
    )


@app.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Recebe feedback (👍/👎) do usuário e salva na memória vetorial do agente."""
    if req.rating not in ("positive", "negative"):
        raise HTTPException(status_code=422, detail="rating deve ser 'positive' ou 'negative'")

    point_id = make_point_id(req.session_id, req.message_id, "assistant")
    payload = {
        "feedback": req.rating,
        "feedback_score": 1.0 if req.rating == "positive" else -1.0,
        "feedback_at": datetime.now(timezone.utc).isoformat(),
    }
    if req.comment:
        payload["feedback_comment"] = req.comment

    success = await vector_memory.update_payload(point_id, payload)
    if not success:
        raise HTTPException(status_code=503, detail="Qdrant indisponível — feedback não registrado")

    log.info(
        "Feedback registrado.",
        agent=req.agent.value,
        rating=req.rating,
        session_id=req.session_id[:8],
        point_id=point_id[:8],
    )
    return {"status": "ok", "point_id": point_id}


@app.post("/v1/chat/stream")
async def chat_stream(request: InboundRequest):
    """
    Endpoint principal. Recebe mensagem do Gateway e faz streaming SSE.
    """
    start = time.time()

    async def event_generator():
        chosen_agent = "system"
        try:
            async for event in router.route(request):
                if event.agent != AgentName.SYSTEM:
                    chosen_agent = event.agent.value
                yield event.to_sse()
        except Exception as e:
            log.error("Erro no event generator", error=str(e), exc_info=True)
            error_event = StreamEvent(
                agent=AgentName.SYSTEM,
                type=EventType.ERROR,
                content=f"Erro interno: {str(e)}",
            )
            yield error_event.to_sse()
        finally:
            duration = time.time() - start
            REQUEST_COUNT.labels(agent=chosen_agent, type=request.type.value).inc()
            REQUEST_DURATION.labels(agent=chosen_agent).observe(duration)
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
