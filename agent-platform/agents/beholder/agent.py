"""
Beholder Agent — Observabilidade e Sentinela.
Usa Claude API com tool use para consultar Prometheus, Loki e cluster k8s em tempo real.
"""
from __future__ import annotations

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
from agents.beholder.prompts import SYSTEM_PROMPT, build_history_context
from agents.beholder.tools import TOOL_DEFINITIONS, execute_tool

log = structlog.get_logger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 5  # máximo de rounds de tool use por resposta


class BeholderAgent:
    """
    Agente Beholder com tool use.
    Pode consultar Prometheus, Loki e k8s diretamente antes de responder.
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
        """
        Processa a mensagem com tool use loop:
        1. Envia mensagem ao Claude com tools disponíveis
        2. Se Claude quer usar uma tool → executa → devolve resultado
        3. Repete até Claude gerar resposta final de texto
        4. Faz streaming do texto final
        """
        log.info("Beholder processando", session_id=request.session_id)

        yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.TYPING, content="")

        messages = build_history_context(history)
        messages.append({"role": "user", "content": request.content})

        try:
            for round_num in range(MAX_TOOL_ROUNDS):
                response = await self.client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )

                # Verifica se Claude quer usar tools
                if response.stop_reason == "tool_use":
                    # Notifica o usuário que está consultando dados reais
                    tool_blocks = [b for b in response.content if b.type == "tool_use"]
                    for tool_block in tool_blocks:
                        action_msg = _describe_tool_action(tool_block.name, tool_block.input)
                        yield StreamEvent(
                            agent=AgentName.BEHOLDER,
                            type=EventType.ACTION,
                            content=action_msg,
                        )

                    # Adiciona resposta do assistente ao histórico de mensagens
                    messages.append({"role": "assistant", "content": response.content})

                    # Executa todas as tools em paralelo
                    import asyncio
                    tool_results = await asyncio.gather(*[
                        execute_tool(b.name, b.input, session_id=request.session_id)
                        for b in tool_blocks
                    ])

                    # Monta bloco de resultados para o próximo round
                    tool_result_content = []
                    for tool_block, result in zip(tool_blocks, tool_results):
                        tool_result_content.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })

                    messages.append({"role": "user", "content": tool_result_content})
                    continue  # próximo round

                # Claude gerou resposta final — faz streaming
                for block in response.content:
                    if hasattr(block, "text") and block.text:
                        # Stream chunk a chunk simulado (API síncrona usada aqui)
                        # Para streaming real usamos .stream() abaixo
                        pass

                # Re-executa com streaming para a resposta final
                async with self.client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield StreamEvent(
                            agent=AgentName.BEHOLDER,
                            type=EventType.MESSAGE,
                            content=text,
                        )

                yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
                return

            # Atingiu o limite de rounds sem resposta final
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.MESSAGE,
                content="⚠️ Atingido limite de consultas. Por favor, reformule a pergunta.",
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")

        except anthropic.APIConnectionError as e:
            log.error("Beholder: falha de conexão com API Claude", error=str(e))
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.ERROR,
                content="❌ Não foi possível conectar à API Claude.",
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")

        except anthropic.RateLimitError:
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.ERROR,
                content="⚠️ Rate limit da API Claude atingido. Tente novamente em instantes.",
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error("Beholder: erro inesperado", error=str(e), exc_info=True)
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.ERROR,
                content=f"❌ Erro interno no Beholder: {str(e)}",
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")


def _describe_tool_action(tool_name: str, tool_input: dict) -> str:
    """Gera mensagem legível descrevendo a tool que está sendo executada."""
    descriptions = {
        "query_prometheus": lambda i: f"📊 Consultando Prometheus: `{i.get('query', '')}`",
        "query_loki": lambda i: f"📋 Buscando logs no Loki: `{i.get('query', '')}` (últimos {i.get('since', '1h')})",
        "get_cluster_health": lambda i: f"🏥 Verificando saúde do cluster{' no namespace ' + i['namespace'] if i.get('namespace') else ''}...",
        "list_active_alerts": lambda i: f"🚨 Listando alertas ativos{' [' + i['severity'] + ']' if i.get('severity') else ''}...",
        "get_pod_metrics": lambda i: f"⚙️ Coletando métricas dos pods em `{i.get('namespace', 'agent-platform')}`...",
        "publish_alert": lambda i: f"📡 Publicando alerta [{i.get('severity', '?').upper()}]: {i.get('alert_name', '')}...",
    }
    fn = descriptions.get(tool_name)
    return fn(tool_input) if fn else f"🔧 Executando: {tool_name}"
