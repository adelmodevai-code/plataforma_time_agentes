"""
Metatron Agent — Documentação e Memória.
Usa tool_use loop (mesmo padrão do LogicX) para criar e gerenciar arquivos.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

import anthropic
import structlog

from models.messages import (
    AgentName,
    ConversationMessage,
    EventType,
    InboundRequest,
    StreamEvent,
)
from agents.metatron.prompts import SYSTEM_PROMPT, build_history_context
from agents.metatron.tools import TOOL_DEFINITIONS, execute_tool

log = structlog.get_logger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 6


class MetatronAgent:
    """
    Agente Metatron — usa Claude API com tool_use loop.
    Cria e gerencia arquivos via FileStorage.
    """

    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY não configurada.")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def run(
        self,
        request: InboundRequest,
        history: list[ConversationMessage],
    ) -> AsyncIterator[StreamEvent]:
        log.info("Metatron processando", session_id=request.session_id)

        yield StreamEvent(agent=AgentName.METATRON, type=EventType.TYPING, content="")

        messages = build_history_context(history)
        messages.append({"role": "user", "content": request.content})

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = await self.client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )

                if response.stop_reason == "tool_use":
                    tool_blocks = [b for b in response.content if b.type == "tool_use"]

                    # Notifica a UI sobre cada operação
                    for tb in tool_blocks:
                        yield StreamEvent(
                            agent=AgentName.METATRON,
                            type=EventType.ACTION,
                            content=_describe_action(tb.name, tb.input),
                        )

                    messages.append({"role": "assistant", "content": response.content})

                    # Executa todas as tools em paralelo
                    results = await asyncio.gather(*[
                        execute_tool(tb.name, tb.input, request.session_id)
                        for tb in tool_blocks
                    ])

                    tool_result_content = [
                        {
                            "type": "tool_result",
                            "tool_use_id": tb.id,
                            "content": json.dumps(r, ensure_ascii=False, default=str),
                        }
                        for tb, r in zip(tool_blocks, results)
                    ]
                    messages.append({"role": "user", "content": tool_result_content})

                    # Emite evento FILE_CREATED para cada arquivo criado/atualizado
                    for tb, result in zip(tool_blocks, results):
                        if result.get("file_created") and result.get("download_url"):
                            yield StreamEvent(
                                agent=AgentName.METATRON,
                                type=EventType.FILE_CREATED,
                                content=result.get("message", ""),
                                metadata={
                                    "filename": result["filename"],
                                    "download_url": result["download_url"],
                                    "size_bytes": result.get("size_bytes", 0),
                                },
                            )
                    continue

                # Resposta final em streaming
                async with self.client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield StreamEvent(
                            agent=AgentName.METATRON,
                            type=EventType.MESSAGE,
                            content=text,
                        )

                yield StreamEvent(agent=AgentName.METATRON, type=EventType.COMPLETE, content="")
                return

            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.MESSAGE,
                content="⚠️ Operação inconclusiva após múltiplas iterações. Reformule o pedido.",
            )
            yield StreamEvent(agent=AgentName.METATRON, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error("Metatron: erro", error=str(e), exc_info=True)
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.ERROR,
                content=f"❌ Metatron: {str(e)}",
            )
            yield StreamEvent(agent=AgentName.METATRON, type=EventType.COMPLETE, content="")


def _describe_action(tool_name: str, inp: dict) -> str:
    m = {
        "write_file":     lambda i: f"📝 Criando arquivo: `{i.get('filename', '')}`",
        "create_report":  lambda i: f"📋 Gerando relatório: `{i.get('title', '')}`",
        "append_to_file": lambda i: f"✏️ Adicionando a: `{i.get('filename', '')}`",
        "list_files":     lambda _: "📂 Listando arquivos da sessão...",
        "read_file":      lambda i: f"🔍 Lendo arquivo: `{i.get('filename', '')}`",
    }
    fn = m.get(tool_name)
    return fn(inp) if fn else f"⚙️ {tool_name}"
