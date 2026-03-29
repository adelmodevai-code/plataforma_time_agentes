"""
Agent Platform — Python Orchestrator
FastAPI + SSE streaming para o Go Gateway.
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from memory.redis_client import memory
from models.messages import InboundRequest, StreamEvent, EventType, AgentName
from router.agent_router import AgentRouter

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
    await memory.connect()
    log.info("✅ Orchestrator pronto.")
    yield
    log.info("🔻 Orchestrator encerrando...")
    await memory.disconnect()


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
    return {
        "status": "ok",
        "service": "orchestrator",
        "active_agents": [a.value for a in AgentRouter.ACTIVE_AGENTS],
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
        {"name": "CyberT",   "status": "offline", "role": "Segurança",                    "phase": 4},
        {"name": "Zerocool", "status": "offline", "role": "Pentesting autorizado",        "phase": 4},
    ]
    return {"agents": agents}


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
