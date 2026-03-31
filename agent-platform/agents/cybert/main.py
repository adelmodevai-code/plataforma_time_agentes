"""
CyberT Microservice — app FastAPI standalone para deploy como pod K8s independente.

Expõe:
    POST /run    → aceita RunRequest, responde SSE com StreamEvent
    GET  /health → health check
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from models.messages import (
    AgentName,
    ConversationMessage,
    EventType,
    InboundRequest,
    StreamEvent,
)
from messaging.nats_bus import nats_bus
from utils.retry import connect_with_retry

log = structlog.get_logger(__name__)

PORT = int(os.getenv("PORT", "8004"))


class RunRequest(BaseModel):
    request: dict
    history: list[dict]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry(nats_bus.connect, "NATS")
    log.info("CyberT microservice pronto.", port=PORT)
    yield
    await nats_bus.disconnect()


app = FastAPI(title="CyberT Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "cybert", "port": PORT}


@app.post("/run")
async def run(body: RunRequest) -> StreamingResponse:
    from agents.cybert.agent import CyberTAgent

    request = InboundRequest(**body.request)
    history = [ConversationMessage(**h) for h in body.history]
    agent = CyberTAgent()

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async for event in agent.run(request, history):
                data = json.dumps(event.model_dump(), ensure_ascii=False, default=str)
                yield f"data: {data}\n\n".encode()
        except Exception as e:
            log.error("CyberT microservice: erro no stream", error=str(e), exc_info=True)
            err_event = StreamEvent(
                agent=AgentName.CYBERT,
                type=EventType.ERROR,
                content=f"Erro interno no CyberT: {str(e)}",
            )
            yield f"data: {json.dumps(err_event.model_dump())}\n\n".encode()
        finally:
            yield b"data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run("agents.cybert.main:app", host="0.0.0.0", port=PORT, workers=1)
