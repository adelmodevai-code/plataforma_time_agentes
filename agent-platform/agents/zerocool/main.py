"""
Zerocool Microservice — app FastAPI standalone para deploy como pod K8s independente.

Gate de segurança ativo: o agente Zerocool exige request_id aprovado por Adelmo.

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
from memory.redis_client import memory
from messaging.metatron_archiver import metatron_archiver
from messaging.nats_bus import nats_bus

log = structlog.get_logger(__name__)

PORT = int(os.getenv("PORT", "8005"))


class RunRequest(BaseModel):
    request: dict
    history: list[dict]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await memory.connect()
    metatron_archiver.register()  # subscriber para agents.metatron.archive
    await nats_bus.connect()
    log.info("Zerocool microservice pronto.", port=PORT)
    yield
    await nats_bus.disconnect()
    await memory.disconnect()


app = FastAPI(title="Zerocool Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "zerocool", "port": PORT}


@app.post("/run")
async def run(body: RunRequest) -> StreamingResponse:
    from agents.zerocool.agent import ZerocoolAgent

    request = InboundRequest(**body.request)
    history = [ConversationMessage(**h) for h in body.history]
    agent = ZerocoolAgent()

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async for event in agent.run(request, history):
                data = json.dumps(event.model_dump(), ensure_ascii=False, default=str)
                yield f"data: {data}\n\n".encode()
        except Exception as e:
            log.error("Zerocool microservice: erro no stream", error=str(e), exc_info=True)
            err_event = StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.ERROR,
                content=f"Erro interno no Zerocool: {str(e)}",
            )
            yield f"data: {json.dumps(err_event.model_dump())}\n\n".encode()
        finally:
            yield b"data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run("agents.zerocool.main:app", host="0.0.0.0", port=PORT, workers=1)
