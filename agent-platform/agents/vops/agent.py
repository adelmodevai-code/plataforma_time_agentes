"""
Vops Agent — Operações de infraestrutura Kubernetes.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator

import anthropic
import structlog

from models.messages import AgentName, ConversationMessage, EventType, InboundRequest, StreamEvent
from agents.vops.prompts import SYSTEM_PROMPT, build_history_context
from agents.vops.tools import TOOL_DEFINITIONS, execute_tool

log = structlog.get_logger(__name__)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 6


class VopsAgent:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY não configurada.")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def run(self, request: InboundRequest, history: list[ConversationMessage]) -> AsyncIterator[StreamEvent]:
        log.info("Vops processando", session_id=request.session_id)

        yield StreamEvent(agent=AgentName.VOPS, type=EventType.TYPING, content="")

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
                            agent=AgentName.VOPS,
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
                    continue

                async with self.client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield StreamEvent(agent=AgentName.VOPS, type=EventType.MESSAGE, content=text)

                yield StreamEvent(agent=AgentName.VOPS, type=EventType.COMPLETE, content="")
                return

            yield StreamEvent(agent=AgentName.VOPS, type=EventType.MESSAGE,
                              content="⚠️ Operação inconclusiva. Verifique o estado do cluster manualmente.")
            yield StreamEvent(agent=AgentName.VOPS, type=EventType.COMPLETE, content="")

        except anthropic.APIStatusError as e:
            is_overloaded = e.status_code == 529 or (isinstance(getattr(e, "body", None), dict) and e.body.get("error", {}).get("type") == "overloaded_error")
            msg = "⚠️ API Claude sobrecarregada. Aguarde alguns segundos e tente novamente." if is_overloaded else f"❌ Erro na API Claude (HTTP {e.status_code}): {e.message}"
            log.warning("Vops: erro de status da API", status=e.status_code, overloaded=is_overloaded)
            yield StreamEvent(agent=AgentName.VOPS, type=EventType.ERROR, content=msg)
            yield StreamEvent(agent=AgentName.VOPS, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error("Vops: erro", error=str(e), exc_info=True)
            yield StreamEvent(agent=AgentName.VOPS, type=EventType.ERROR, content=f"❌ Vops: {str(e)}")
            yield StreamEvent(agent=AgentName.VOPS, type=EventType.COMPLETE, content="")


def _describe_action(tool_name: str, inp: dict) -> str:
    m = {
        "k8s_get": lambda i: f"🔍 Listando `{i['resource']}` em `{i.get('namespace', 'all')}`...",
        "k8s_scale": lambda i: f"⚖️ {'[DRY-RUN] ' if i.get('dry_run') else ''}Escalando `{i['name']}` para {i['replicas']} réplicas...",
        "k8s_rollout_restart": lambda i: f"🔄 {'[DRY-RUN] ' if i.get('dry_run') else ''}Reiniciando deployment `{i['name']}`...",
        "k8s_rollout_status": lambda i: f"📊 Verificando rollout de `{i['name']}`...",
        "k8s_rollout_undo": lambda i: f"⏪ {'[DRY-RUN] ' if i.get('dry_run') else ''}Rollback de `{i['name']}`...",
        "k8s_get_logs": lambda i: f"📋 Coletando logs de `{i['pod_name']}` (últimas {i.get('tail_lines', 50)} linhas)...",
        "k8s_top": lambda i: f"📊 Consultando uso de recursos em `{i['namespace']}`...",
        "k8s_delete_pod": lambda i: f"🗑️ {'[DRY-RUN] ' if i.get('dry_run', True) else '⚠️ '}Deletando pod `{i['pod_name']}`...",
    }
    fn = m.get(tool_name)
    return fn(inp) if fn else f"⚙️ {tool_name}"
