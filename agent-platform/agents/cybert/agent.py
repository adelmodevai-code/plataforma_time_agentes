"""
CyberT Agent — Segurança e Auditoria.
Usa Claude API com tool use para auditar cluster k8s.
Quando identifica vulnerabilidade crítica, solicita autorização para Zerocool via gate de aprovação.
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
from agents.cybert.prompts import SYSTEM_PROMPT, build_history_context
from agents.cybert.tools import TOOL_DEFINITIONS, execute_tool

log = structlog.get_logger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 6  # auditoria pode precisar de mais rounds (múltiplos checks)


class CyberTAgent:
    """
    Agente CyberT com tool use para segurança e auditoria k8s.

    Comportamento especial:
    - Quando `request_pentest_authorization` retorna `approval_required: True`,
      emite um StreamEvent do tipo APPROVAL_REQUEST para acionar o modal na UI.
    - O fluxo de aprovação continua no agent_router (resolve_approval).
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
        Tool use loop com gate de autorização para pentest:
        1. Envia mensagem ao Claude com tools de auditoria
        2. Executa tools → acumula achados
        3. Se `request_pentest_authorization` → emite APPROVAL_REQUEST e suspende
        4. Claude gera relatório final com os achados
        """
        log.info("CyberT processando", session_id=request.session_id)

        yield StreamEvent(agent=AgentName.CYBERT, type=EventType.TYPING, content="")

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

                if response.stop_reason == "tool_use":
                    tool_blocks = [b for b in response.content if b.type == "tool_use"]

                    # Notifica UI sobre cada tool em execução
                    for tool_block in tool_blocks:
                        action_msg = _describe_tool_action(tool_block.name, tool_block.input)
                        yield StreamEvent(
                            agent=AgentName.CYBERT,
                            type=EventType.ACTION,
                            content=action_msg,
                        )

                    # Adiciona resposta do assistente ao histórico
                    messages.append({"role": "assistant", "content": response.content})

                    # Executa todas as tools em paralelo
                    tool_results = await asyncio.gather(*[
                        execute_tool(b.name, b.input)
                        for b in tool_blocks
                    ])

                    # Verifica se alguma tool retornou approval_required
                    approval_event = _check_for_approval_request(tool_blocks, tool_results)
                    if approval_event is not None:
                        # Emite evento de aprovação para a UI exibir o modal
                        yield approval_event
                        # Informa Claude que a solicitação foi enviada
                        tool_result_content = []
                        for tool_block, result in zip(tool_blocks, tool_results):
                            tool_result_content.append({
                                "type": "tool_result",
                                "tool_use_id": tool_block.id,
                                "content": json.dumps(result, ensure_ascii=False, default=str),
                            })
                        messages.append({"role": "user", "content": tool_result_content})
                        # Claude continua para gerar o relatório parcial + aviso de aguardo
                        # (não retorna aqui — permite que Claude explique o que foi encontrado)
                        continue

                    # Sem approval — monta resultados normalmente
                    tool_result_content = []
                    for tool_block, result in zip(tool_blocks, tool_results):
                        tool_result_content.append({
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })

                    messages.append({"role": "user", "content": tool_result_content})
                    continue  # próximo round

                # Claude gerou resposta final — streaming
                async with self.client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield StreamEvent(
                            agent=AgentName.CYBERT,
                            type=EventType.MESSAGE,
                            content=text,
                        )

                yield StreamEvent(agent=AgentName.CYBERT, type=EventType.COMPLETE, content="")
                return

            # Limite de rounds atingido
            yield StreamEvent(
                agent=AgentName.CYBERT,
                type=EventType.MESSAGE,
                content="⚠️ Auditoria atingiu o limite de verificações. Relatório parcial acima.",
            )
            yield StreamEvent(agent=AgentName.CYBERT, type=EventType.COMPLETE, content="")

        except anthropic.APIConnectionError as e:
            log.error("CyberT: falha de conexão com API Claude", error=str(e))
            yield StreamEvent(
                agent=AgentName.CYBERT,
                type=EventType.ERROR,
                content="❌ Não foi possível conectar à API Claude.",
            )
            yield StreamEvent(agent=AgentName.CYBERT, type=EventType.COMPLETE, content="")

        except anthropic.RateLimitError:
            yield StreamEvent(
                agent=AgentName.CYBERT,
                type=EventType.ERROR,
                content="⚠️ Rate limit da API Claude atingido. Tente novamente em instantes.",
            )
            yield StreamEvent(agent=AgentName.CYBERT, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error("CyberT: erro inesperado", error=str(e), exc_info=True)
            yield StreamEvent(
                agent=AgentName.CYBERT,
                type=EventType.ERROR,
                content=f"❌ Erro interno no CyberT: {str(e)}",
            )
            yield StreamEvent(agent=AgentName.CYBERT, type=EventType.COMPLETE, content="")


def _check_for_approval_request(
    tool_blocks: list,
    tool_results: list,
) -> StreamEvent | None:
    """
    Verifica se alguma tool retornou approval_required=True.
    Retorna um StreamEvent APPROVAL_REQUEST se encontrado, None caso contrário.
    """
    for tool_block, result in zip(tool_blocks, tool_results):
        if tool_block.name == "request_pentest_authorization":
            if isinstance(result, dict) and result.get("approval_required"):
                return StreamEvent(
                    agent=AgentName.CYBERT,
                    type=EventType.APPROVAL_REQUEST,
                    content=(
                        f"🔐 CyberT solicita autorização para Zerocool confirmar vulnerabilidade:\n"
                        f"**Alvo**: `{result.get('target', 'N/A')}`\n"
                        f"**Vulnerabilidade**: {result.get('vulnerability', 'N/A')}\n"
                        f"**Severidade**: {result.get('severity', 'N/A')}\n\n"
                        f"Aguardando aprovação do Adelmo..."
                    ),
                    metadata=result,
                )
    return None


def _describe_tool_action(tool_name: str, tool_input: dict) -> str:
    """Gera mensagem legível descrevendo a tool de segurança em execução."""
    descriptions = {
        "audit_rbac": lambda i: (
            f"🔑 Auditando permissões RBAC"
            + (f" no namespace `{i['namespace']}`" if i.get("namespace") else " em todo o cluster")
        ),
        "check_pod_security": lambda i: (
            f"🛡️ Verificando contextos de segurança dos pods"
            + (f" em `{i['namespace']}`" if i.get("namespace") else "")
        ),
        "scan_exposed_secrets": lambda i: (
            f"🔍 Varrendo segredos expostos em env vars e ConfigMaps"
            + (f" no namespace `{i['namespace']}`" if i.get("namespace") else "")
        ),
        "check_network_policies": lambda i: (
            "🌐 Identificando pods sem NetworkPolicy (exposição de rede)..."
        ),
        "audit_image_security": lambda i: (
            f"📦 Auditando imagens dos containers"
            + (f" em `{i['namespace']}`" if i.get("namespace") else "")
            + " (tags :latest, digest ausente)..."
        ),
        "check_service_exposure": lambda i: (
            f"🔓 Auditando serviços expostos via NodePort/LoadBalancer"
            + (f" em `{i['namespace']}`" if i.get("namespace") else "")
        ),
        "request_pentest_authorization": lambda i: (
            f"📋 Solicitando autorização de pentest para: `{i.get('target', 'N/A')}`"
            + f" — Vulnerabilidade: {i.get('vulnerability', 'N/A')}"
        ),
    }
    fn = descriptions.get(tool_name)
    return fn(tool_input) if fn else f"🔧 Executando verificação: {tool_name}"
