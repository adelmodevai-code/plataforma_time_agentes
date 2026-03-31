"""
Zerocool Agent — White Hat Pentester.
Confirma vulnerabilidades identificadas pelo CyberT com evidências técnicas controladas.
EXIGE request_id aprovado pelo Adelmo antes de executar qualquer ação ofensiva.
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
from agents.zerocool.prompts import SYSTEM_PROMPT, build_history_context
from agents.zerocool.tools import TOOL_DEFINITIONS, execute_tool

log = structlog.get_logger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOOL_ROUNDS = 6  # pentest pode ter múltiplas fases: confirm → poc → report → archive


class ZerocoolAgent:
    """
    Agente Zerocool com tool use para pentesting ético.

    Gate de segurança:
    - Verifica se a mensagem contém um request_id aprovado antes de rodar
    - Se não houver aprovação, recusa educadamente e lembra do processo
    - Cada ação gera evidência rastreável com request_id
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
        Fluxo do Zerocool:
        1. Verifica se há request_id aprovado na mensagem/metadata
        2. Se não houver → responde sem usar tools (explicação do processo)
        3. Se houver → executa tool use loop com todas as tools de pentest
        4. Cada tool emite ACTION event com descrição do teste em andamento
        5. Gera relatório final e arquiva no Metatron
        """
        log.info("Zerocool processando", session_id=request.session_id)

        yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.TYPING, content="")

        # Verifica autorização via metadata do request
        request_id = _extract_request_id(request)
        approved = request_id is not None

        messages = build_history_context(history)

        if approved:
            # Injeta o request_id na mensagem para que Claude saiba que está autorizado
            augmented_content = (
                f"{request.content}\n\n"
                f"[AUTORIZAÇÃO CONFIRMADA — Request ID: `{request_id}` aprovado por Adelmo]"
            )
            messages.append({"role": "user", "content": augmented_content})

            # Notifica UI que o pentest foi autorizado
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.ACTION,
                content=f"🔓 Autorização confirmada — Request ID: `{request_id}` | Iniciando pentest controlado...",
            )
        else:
            messages.append({"role": "user", "content": request.content})

        try:
            # Se não aprovado, roda sem tools para Claude explicar o processo
            tools_to_use = TOOL_DEFINITIONS if approved else []

            for round_num in range(MAX_TOOL_ROUNDS):
                response = await self.client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools_to_use if tools_to_use else anthropic.NOT_GIVEN,
                    messages=messages,
                )

                if response.stop_reason == "tool_use" and approved:
                    tool_blocks = [b for b in response.content if b.type == "tool_use"]

                    # Notifica UI sobre cada teste em execução
                    for tool_block in tool_blocks:
                        action_msg = _describe_tool_action(
                            tool_block.name, tool_block.input, request_id or ""
                        )
                        yield StreamEvent(
                            agent=AgentName.ZEROCOOL,
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

                    # Monta resultados
                    tool_result_content = []
                    for tool_block, result in zip(tool_blocks, tool_results):
                        # Se o relatório foi gerado, notifica
                        if tool_block.name == "generate_pentest_report":
                            if isinstance(result, dict) and result.get("report_generated"):
                                yield StreamEvent(
                                    agent=AgentName.ZEROCOOL,
                                    type=EventType.ACTION,
                                    content=(
                                        f"📄 Relatório gerado: `{result.get('report_filename', 'pentest.md')}` "
                                        f"| {result.get('summary', {}).get('evidence_count', 0)} evidências coletadas"
                                    ),
                                )

                        # Se arquivou no Metatron, notifica
                        if tool_block.name == "archive_to_metatron":
                            if isinstance(result, dict) and result.get("archived"):
                                yield StreamEvent(
                                    agent=AgentName.ZEROCOOL,
                                    type=EventType.ACTION,
                                    content=(
                                        f"🗄️ Arquivado no Metatron: `{result.get('archive_ref', 'N/A')}`"
                                    ),
                                )

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
                    tools=tools_to_use if tools_to_use else anthropic.NOT_GIVEN,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield StreamEvent(
                            agent=AgentName.ZEROCOOL,
                            type=EventType.MESSAGE,
                            content=text,
                        )

                yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.COMPLETE, content="")
                return

            # Limite de rounds
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.MESSAGE,
                content="⚠️ Limite de rounds de pentest atingido. Relatório parcial acima.",
            )
            yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.COMPLETE, content="")

        except anthropic.APIConnectionError as e:
            log.error("Zerocool: falha de conexão", error=str(e))
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.ERROR,
                content="❌ Não foi possível conectar à API Claude.",
            )
            yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.COMPLETE, content="")

        except anthropic.RateLimitError:
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.ERROR,
                content="⚠️ Rate limit da API Claude atingido. Tente novamente em instantes.",
            )
            yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.COMPLETE, content="")

        except anthropic.APIStatusError as e:
            is_overloaded = (
                e.status_code == 529
                or (isinstance(getattr(e, "body", None), dict) and e.body.get("error", {}).get("type") == "overloaded_error")
            )
            msg = (
                "⚠️ API Claude sobrecarregada. Aguarde alguns segundos e tente novamente."
                if is_overloaded
                else f"❌ Erro na API Claude (HTTP {e.status_code}): {e.message}"
            )
            log.warning("Zerocool: erro de status da API", status=e.status_code, overloaded=is_overloaded)
            yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.ERROR, content=msg)
            yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error("Zerocool: erro inesperado", error=str(e), exc_info=True)
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.ERROR,
                content=f"❌ Erro interno no Zerocool: {str(e)}",
            )
            yield StreamEvent(agent=AgentName.ZEROCOOL, type=EventType.COMPLETE, content="")


def _extract_request_id(request: InboundRequest) -> str | None:
    """
    Extrai o request_id de aprovação do request.
    O request_id pode estar em:
    - request.metadata["request_id"] (enviado pelo UI após aprovação do Adelmo)
    - request.content com padrão "[APROVADO: <uuid>]"
    """
    # Verifica metadata primeiro (preferencial — enviado pelo orchestrator)
    if request.metadata and request.metadata.get("request_id"):
        return str(request.metadata["request_id"])

    # Fallback: busca no conteúdo textual
    import re
    pattern = r"\[APROVADO[:\s]+([a-f0-9\-]{36})\]"
    match = re.search(pattern, request.content, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def _describe_tool_action(tool_name: str, tool_input: dict, request_id: str) -> str:
    """Gera mensagem legível descrevendo o teste em execução."""
    descriptions = {
        "confirm_rbac_escalation": lambda i: (
            f"🔑 Confirmando escalonamento via ClusterRole `{i.get('target_role', 'N/A')}`"
        ),
        "test_secret_exposure": lambda i: (
            f"🔍 Testando exposição do Secret `{i.get('secret_name', 'N/A')}` "
            f"em `{i.get('namespace', 'default')}`"
        ),
        "scan_network_reachability": lambda i: (
            f"🌐 Escaneando alcançabilidade: `{i.get('source_namespace', '?')}` → "
            f"`{i.get('target_namespace', '?')}`"
        ),
        "check_api_server_exposure": lambda i: (
            "🔓 Verificando exposição do kube-apiserver..."
        ),
        "generate_pentest_report": lambda i: (
            f"📋 Gerando relatório de pentest para: {i.get('vulnerability', 'N/A')}"
        ),
        "generate_proof_of_concept": lambda i: (
            f"⚗️ Criando PoC para: {i.get('vulnerability_type', 'N/A')} "
            f"em `{i.get('target', 'N/A')}`"
        ),
        "archive_to_metatron": lambda i: (
            "🗄️ Arquivando relatório no Metatron..."
        ),
    }
    fn = descriptions.get(tool_name)
    base = fn(tool_input) if fn else f"🔧 Executando: {tool_name}"
    return f"{base} | `{request_id[:8]}...`"
