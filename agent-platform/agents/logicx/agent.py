"""
LogicX Agent — Raciocínio, correlação e decisão.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator

import anthropic
import structlog

from models.messages import AgentName, ConversationMessage, EventType, InboundRequest, StreamEvent
from agents.logicx.prompts import SYSTEM_PROMPT, build_history_context
from agents.logicx.tools import TOOL_DEFINITIONS, execute_tool

log = structlog.get_logger(__name__)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 6


class LogicXAgent:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY não configurada.")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def run(self, request: InboundRequest, history: list[ConversationMessage]) -> AsyncIterator[StreamEvent]:
        log.info("LogicX processando", session_id=request.session_id)

        yield StreamEvent(agent=AgentName.LOGICX, type=EventType.TYPING, content="")

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

                    for tb in tool_blocks:
                        yield StreamEvent(
                            agent=AgentName.LOGICX,
                            type=EventType.ACTION,
                            content=_describe_action(tb.name, tb.input),
                        )

                    messages.append({"role": "assistant", "content": response.content})

                    import asyncio
                    results = await asyncio.gather(*[execute_tool(b.name, b.input) for b in tool_blocks])

                    tool_result_content = [
                        {"type": "tool_result", "tool_use_id": tb.id,
                         "content": json.dumps(r, ensure_ascii=False, default=str)}
                        for tb, r in zip(tool_blocks, results)
                    ]
                    messages.append({"role": "user", "content": tool_result_content})

                    # Detecta delegação ao Vops — emite evento DELEGATION
                    # O agent_router intercepta este evento e encadeia o Vops
                    for tb, result in zip(tool_blocks, results):
                        if tb.name == "delegate_to_vops" and "delegation" in result:
                            delegation = result["delegation"]
                            yield StreamEvent(
                                agent=AgentName.LOGICX,
                                type=EventType.DELEGATION,
                                content=(
                                    f"⚙️ LogicX → **Vops**: `{delegation['action']}` "
                                    f"em `{delegation['resource_type']}/{delegation['resource_name']}` "
                                    f"[{delegation['namespace']}]\n"
                                    f"📋 Motivo: {delegation['reason']}"
                                ),
                                metadata=delegation,
                            )
                    continue

                # Resposta final com streaming
                async with self.client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield StreamEvent(agent=AgentName.LOGICX, type=EventType.MESSAGE, content=text)

                yield StreamEvent(agent=AgentName.LOGICX, type=EventType.COMPLETE, content="")
                return

            yield StreamEvent(agent=AgentName.LOGICX, type=EventType.MESSAGE,
                              content="⚠️ Análise inconclusiva após múltiplas iterações. Reformule o problema.")
            yield StreamEvent(agent=AgentName.LOGICX, type=EventType.COMPLETE, content="")

        except anthropic.APIStatusError as e:
            is_overloaded = e.status_code == 529 or (isinstance(getattr(e, "body", None), dict) and e.body.get("error", {}).get("type") == "overloaded_error")
            msg = "⚠️ API Claude sobrecarregada. Aguarde alguns segundos e tente novamente." if is_overloaded else f"❌ Erro na API Claude (HTTP {e.status_code}): {e.message}"
            log.warning("LogicX: erro de status da API", status=e.status_code, overloaded=is_overloaded)
            yield StreamEvent(agent=AgentName.LOGICX, type=EventType.ERROR, content=msg)
            yield StreamEvent(agent=AgentName.LOGICX, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error("LogicX: erro", error=str(e), exc_info=True)
            yield StreamEvent(agent=AgentName.LOGICX, type=EventType.ERROR, content=f"❌ LogicX: {str(e)}")
            yield StreamEvent(agent=AgentName.LOGICX, type=EventType.COMPLETE, content="")


def _describe_action(tool_name: str, inp: dict) -> str:
    m = {
        "fetch_beholder_data": lambda i: f"🔭 Buscando dados do Beholder{' em ' + i['namespace'] if i.get('namespace') else ''}...",
        "analyze_anomaly": lambda i: f"🔬 Analisando: `{i.get('signal', '')}`",
        "correlate_signals": lambda i: f"🔗 Correlacionando {len(i.get('signals', []))} sinais em `{i.get('time_window', '15m')}`...",
        "plan_remediation": lambda i: f"📋 Elaborando plano de remediação para: `{i.get('problem', '')}`",
        "delegate_to_vops": lambda i: f"📤 Preparando delegação ao Vops: `{i.get('action')}` em `{i.get('resource_name')}`",
    }
    fn = m.get(tool_name)
    return fn(inp) if fn else f"🔧 {tool_name}"
