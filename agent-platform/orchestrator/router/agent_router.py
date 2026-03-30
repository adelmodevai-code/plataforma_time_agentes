"""
Agent Router — decide qual(is) agente(s) acionar baseado na mensagem do usuário.

Arquitetura de papéis:
- Beholder  → ponto de entrada padrão, sentinela, coordenador
- Metatron  → documentação passiva, acionado apenas quando explicitamente pedido
- LogicX    → análise e correlação (Fase 3+)
- Vops      → operações k8s (Fase 3+)
- CyberT    → segurança e auditoria (Fase 4)
- Zerocool  → pentesting autorizado por Adelmo (Fase 4)

Memória vetorial (Qdrant):
- Antes de rotear: busca memórias relevantes e injeta no request
- Após a resposta: armazena a troca no Qdrant para uso futuro
"""
from __future__ import annotations

import asyncio
import structlog
from typing import AsyncIterator

from models.messages import (
    AgentName,
    ConversationMessage,
    EventType,
    InboundRequest,
    MessageType,
    StreamEvent,
)
from memory.redis_client import memory
from memory.qdrant_memory import vector_memory

log = structlog.get_logger(__name__)


def _get_agent(name: AgentName):
    """Importação lazy de agentes — carrega apenas os ativos."""
    if name == AgentName.BEHOLDER:
        from agents.beholder.agent import BeholderAgent
        return BeholderAgent()
    if name == AgentName.METATRON:
        from agents.metatron.agent import MetatronAgent
        return MetatronAgent()
    if name == AgentName.LOGICX:
        from agents.logicx.agent import LogicXAgent
        return LogicXAgent()
    if name == AgentName.VOPS:
        from agents.vops.agent import VopsAgent
        return VopsAgent()
    if name == AgentName.CYBERT:
        from agents.cybert.agent import CyberTAgent
        return CyberTAgent()
    if name == AgentName.ZEROCOOL:
        from agents.zerocool.agent import ZerocoolAgent
        return ZerocoolAgent()
    raise ValueError(f"Agente {name} não implementado.")


class AgentRouter:
    """
    Roteador central com memória vetorial integrada.

    Fluxo por mensagem:
    1. Busca memórias relevantes no Qdrant (async, não bloqueia)
    2. Seleciona agente por palavras-chave
    3. Injeta memórias no request como contexto adicional
    4. Executa agente com streaming
    5. Armazena: pergunta do usuário + resposta do agente no Qdrant
    """

    ACTIVE_AGENTS = {
        AgentName.BEHOLDER,
        AgentName.METATRON,
        AgentName.LOGICX,
        AgentName.VOPS,
        AgentName.CYBERT,
        AgentName.ZEROCOOL,
    }

    METATRON_KEYWORDS = {
        "documente", "documentar", "registre", "registrar",
        "arquive", "arquivar", "relatório", "gere um relatório",
        "anote", "anotar", "salve isso", "grave isso",
        "escreva um resumo", "crie um relatório", "histórico de decisões",
        "metatron",
    }

    LOGICX_KEYWORDS = [
        "analise", "analisar", "correlacionar", "causa raiz", "por que está",
        "o que causou", "diagnosticar", "investigar", "anomalia", "incidente",
        "degradação", "lento", "latência alta", "erros aumentando", "logicx",
        "recomendar ação", "o que fazer", "plano de remediação",
    ]

    VOPS_KEYWORDS = [
        "deploy", "escalar", "scale", "restart", "reiniciar", "rollback",
        "pod", "deployment", "namespace", "k8s", "kubernetes", "kubectl",
        "helm", "rollout", "réplicas", "replicas", "statefulset", "logs do pod",
        "deletar pod", "vops", "aumentar réplicas", "diminuir réplicas",
    ]

    CYBERT_KEYWORDS = [
        "vulnerabilidade", "vulnerabilidades", "cve", "cwe", "exploit",
        "auditoria", "auditoria de segurança", "scan", "segurança",
        "rbac", "network policy", "segredo exposto", "secret exposto",
        "imagem insegura", "pod privilegiado", "privilégio excessivo",
        "permissão excessiva", "nodeport exposto", "loadbalancer exposto",
        "pentest", "cybert", "risco de segurança",
    ]

    ZEROCOOL_KEYWORDS = [
        "confirmar vulnerabilidade", "teste de invasão", "testar vulnerabilidade",
        "zerocool", "executar pentest", "confirmar exploit",
    ]

    async def route(self, request: InboundRequest) -> AsyncIterator[StreamEvent]:
        """Roteia a requisição com memória vetorial integrada."""
        log.info(
            "Roteando mensagem",
            session_id=request.session_id,
            message_type=request.type,
            content_preview=request.content[:80],
        )

        # Aprovação/negação para Zerocool
        if request.type in (MessageType.APPROVAL, MessageType.DENIAL):
            async for event in self._handle_approval(request):
                yield event
            return

        # Seleciona agente
        agent_name = await self._select_agent(request)

        if agent_name not in self.ACTIVE_AGENTS:
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.MESSAGE,
                content=(
                    f"👁️ O agente **{agent_name.value}** ainda não está ativo. "
                    f"Posso ajudar com observabilidade e status do ambiente agora."
                ),
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
            return

        # Busca memórias relevantes no Qdrant (em paralelo com carregamento do histórico)
        memories_task = asyncio.create_task(
            vector_memory.search(
                query=request.content,
                agent=agent_name.value,
                top_k=5,
                score_threshold=0.60,
            )
        )

        # Salva mensagem do usuário no Redis
        await memory.append_message(
            request.session_id,
            ConversationMessage(role="user", content=request.content),
        )

        # Armazena também no Qdrant (sem esperar — fire and forget)
        asyncio.create_task(
            vector_memory.store(
                agent=agent_name.value,
                session_id=request.session_id,
                content=request.content,
                role="user",
            )
        )

        # Carrega histórico Redis
        history = await memory.get_history(request.session_id)

        # Aguarda memórias vetoriais
        relevant_memories = await memories_task

        # Injeta memórias no request se encontradas
        enriched_request = _enrich_request_with_memories(request, relevant_memories)

        # Instancia e executa agente
        agent = _get_agent(agent_name)

        full_response = ""
        async for event in agent.run(enriched_request, history):
            if event.type == EventType.MESSAGE:
                full_response += event.content
            yield event

        # Salva resposta no Redis
        if full_response:
            await memory.append_message(
                request.session_id,
                ConversationMessage(
                    role="assistant",
                    agent=agent_name,
                    content=full_response,
                ),
            )

            # Armazena resposta no Qdrant (fire and forget)
            asyncio.create_task(
                vector_memory.store(
                    agent=agent_name.value,
                    session_id=request.session_id,
                    content=full_response,
                    role="assistant",
                )
            )

    async def _select_agent(self, request: InboundRequest) -> AgentName:
        """Lógica de seleção de agente por palavras-chave."""
        content_lower = request.content.lower()

        if any(kw in content_lower for kw in self.METATRON_KEYWORDS):
            return AgentName.METATRON
        if any(kw in content_lower for kw in self.ZEROCOOL_KEYWORDS):
            return AgentName.ZEROCOOL
        if any(kw in content_lower for kw in self.CYBERT_KEYWORDS):
            return AgentName.CYBERT
        if any(kw in content_lower for kw in self.VOPS_KEYWORDS):
            return AgentName.VOPS
        if any(kw in content_lower for kw in self.LOGICX_KEYWORDS):
            return AgentName.LOGICX

        return AgentName.BEHOLDER

    async def _handle_approval(self, request: InboundRequest) -> AsyncIterator[StreamEvent]:
        """Processa aprovação/negação de pentest do Zerocool."""
        meta = request.metadata or {}
        request_id = meta.get("request_id", "")

        pending = await memory.get_approval_pending(request_id)
        if not pending:
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.ERROR,
                content="⚠️ Pedido de aprovação não encontrado ou expirado (TTL 1h).",
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
            return

        if request.type == MessageType.DENIAL:
            await memory.resolve_approval(request_id)
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.MESSAGE,
                content=(
                    f"❌ Pentest **negado** por Adelmo.\n"
                    f"Request ID `{request_id[:8]}...` descartado e registrado."
                ),
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
            return

        # APROVADO — executa Zerocool
        await memory.resolve_approval(request_id)

        yield StreamEvent(
            agent=AgentName.ZEROCOOL,
            type=EventType.ACTION,
            content=(
                f"✅ Autorização confirmada por Adelmo.\n"
                f"**Alvo**: `{pending.get('target', 'N/A')}`\n"
                f"**Vulnerabilidade**: {pending.get('vulnerability', 'N/A')}\n"
                f"**Request ID**: `{request_id[:8]}...`"
            ),
        )

        zerocool_request = InboundRequest(
            session_id=request.session_id,
            content=(
                f"Confirme a seguinte vulnerabilidade e gere o relatório completo:\n"
                f"- Alvo: {pending.get('target', 'N/A')}\n"
                f"- Vulnerabilidade: {pending.get('vulnerability', 'N/A')}\n"
                f"- Severidade: {pending.get('severity', 'N/A')}\n"
                f"- Contexto adicional: {pending.get('description', '')}\n\n"
                f"Request ID autorizado: {request_id}"
            ),
            type=MessageType.MESSAGE,
            metadata={"request_id": request_id, **pending},
        )

        history = await memory.get_history(request.session_id)
        agent = _get_agent(AgentName.ZEROCOOL)

        full_response = ""
        async for event in agent.run(zerocool_request, history):
            if event.type == EventType.MESSAGE:
                full_response += event.content
            yield event

        if full_response:
            await memory.append_message(
                request.session_id,
                ConversationMessage(
                    role="assistant",
                    agent=AgentName.ZEROCOOL,
                    content=full_response,
                ),
            )
            asyncio.create_task(
                vector_memory.store(
                    agent=AgentName.ZEROCOOL.value,
                    session_id=request.session_id,
                    content=full_response,
                    role="assistant",
                    metadata={"request_id": request_id, "type": "pentest_result"},
                )
            )


# ─────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────

def _enrich_request_with_memories(
    request: InboundRequest,
    memories: list[dict],
) -> InboundRequest:
    """
    Injeta memórias relevantes do Qdrant no conteúdo do request.
    O agente verá as memórias como contexto adicional antes da pergunta.
    Se não houver memórias relevantes, retorna o request original.
    """
    if not memories:
        return request

    memory_context = vector_memory.format_for_prompt(memories, max_memories=4)
    if not memory_context:
        return request

    enriched_content = (
        f"{memory_context}\n\n"
        f"---\n"
        f"**Mensagem atual:**\n{request.content}"
    )

    return InboundRequest(
        session_id=request.session_id,
        content=enriched_content,
        type=request.type,
        metadata=request.metadata,
    )
