"""
Agent Router — decide qual(is) agente(s) acionar baseado na mensagem do usuário.

Arquitetura de papéis:
- Beholder  → ponto de entrada padrão, sentinela, coordenador
- Metatron  → documentação passiva, acionado apenas quando explicitamente pedido
- LogicX    → análise e correlação (Fase 3+)
- Vops      → operações k8s (Fase 3+)
- CyberT    → segurança (Fase 4+)
- Zerocool  → pentesting autorizado (Fase 4+)
"""
from __future__ import annotations

import structlog
from typing import AsyncIterator

from models.messages import (
    AgentName,
    EventType,
    InboundRequest,
    MessageType,
    StreamEvent,
)
from memory.redis_client import memory

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
    raise ValueError(f"Agente {name} ainda não implementado nesta fase.")


class AgentRouter:
    """
    Roteador central. Recebe a requisição do Gateway e:
    1. Determina qual agente deve responder
    2. Carrega histórico da sessão
    3. Faz streaming dos eventos de volta

    Regra de roteamento:
    - Beholder é o DEFAULT — responde tudo relacionado ao ambiente, cluster, métricas,
      status, saúde do sistema e perguntas gerais.
    - Metatron é PASSIVO — acionado apenas quando o usuário pede explicitamente
      para documentar, registrar, arquivar ou gerar relatório.
    - Demais agentes: offline (Fases 2-4).
    """

    # Fase 3: Beholder + Metatron + LogicX + Vops
    ACTIVE_AGENTS = {AgentName.BEHOLDER, AgentName.METATRON, AgentName.LOGICX, AgentName.VOPS}

    # Palavras-chave que roteiam para Metatron (documentação explícita)
    METATRON_KEYWORDS = {
        "documente", "documentar", "registre", "registrar",
        "arquive", "arquivar", "relatório", "gere um relatório",
        "anote", "anotar", "salve isso", "grave isso",
        "escreva um resumo", "crie um relatório", "histórico de decisões",
        "metatron",
    }

    async def route(self, request: InboundRequest) -> AsyncIterator[StreamEvent]:
        """Roteia a requisição e faz yield de StreamEvents."""
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
                    f"Será ativado em uma fase futura. "
                    f"Posso ajudar com observabilidade e status do ambiente agora."
                ),
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
            return

        # Salva mensagem do usuário no histórico
        from models.messages import ConversationMessage
        await memory.append_message(
            request.session_id,
            ConversationMessage(role="user", content=request.content),
        )

        # Carrega histórico
        history = await memory.get_history(request.session_id)

        # Instancia e executa agente
        agent = _get_agent(agent_name)

        full_response = ""
        async for event in agent.run(request, history):
            if event.type == EventType.MESSAGE:
                full_response += event.content
            yield event

        # Salva resposta do agente no histórico
        if full_response:
            await memory.append_message(
                request.session_id,
                ConversationMessage(
                    role="assistant",
                    agent=agent_name,
                    content=full_response,
                ),
            )

    async def _select_agent(self, request: InboundRequest) -> AgentName:
        """
        Lógica de seleção de agente.

        - Metatron: apenas quando documentação é explicitamente pedida
        - Vops/CyberT/Zerocool/LogicX: quando ativos (Fases futuras)
        - Beholder: DEFAULT para tudo mais
        """
        content_lower = request.content.lower()

        # Metatron apenas se documentação for pedida explicitamente
        if any(kw in content_lower for kw in self.METATRON_KEYWORDS):
            return AgentName.METATRON

        # LogicX — análise, correlação, causa raiz
        logicx_keywords = [
            "analise", "analisar", "correlacionar", "causa raiz", "por que está",
            "o que causou", "diagnosticar", "investigar", "anomalia", "incidente",
            "degradação", "lento", "latência alta", "erros aumentando", "logicx",
            "recomendar ação", "o que fazer", "plano de remediação",
        ]
        if any(kw in content_lower for kw in logicx_keywords):
            return AgentName.LOGICX

        # Vops — operações k8s
        vops_keywords = [
            "deploy", "escalar", "scale", "restart", "reiniciar", "rollback",
            "pod", "deployment", "namespace", "k8s", "kubernetes", "kubectl",
            "helm", "rollout", "réplicas", "replicas", "statefulset", "logs do pod",
            "deletar pod", "vops", "aumentar réplicas", "diminuir réplicas",
        ]
        if any(kw in content_lower for kw in vops_keywords):
            return AgentName.VOPS

        # Agentes ainda offline (Fase 4)
        future_keywords = {
            AgentName.CYBERT:   ["vulnerabilidade", "cve", "exploit", "auditoria", "scan", "firewall", "cybert"],
            AgentName.ZEROCOOL: ["pentest", "teste de invasão", "confirmar vulnerabilidade", "zerocool"],
        }
        for agent, kws in future_keywords.items():
            if any(kw in content_lower for kw in kws):
                return AgentName.BEHOLDER  # intercepta e informa

        # DEFAULT: Beholder responde tudo
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
                content="⚠️ Pedido de aprovação não encontrado ou expirado.",
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
            return

        if request.type == MessageType.APPROVAL:
            await memory.resolve_approval(request_id)
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.ACTION,
                content=f"✅ Autorização recebida, Adelmo. Iniciando pentest em **{pending['target']}**...",
                metadata=pending,
            )
            yield StreamEvent(
                agent=AgentName.ZEROCOOL,
                type=EventType.MESSAGE,
                content="Zerocool será ativado na Fase 4. O pedido foi registrado e será executado quando estiver online.",
            )
        else:
            await memory.resolve_approval(request_id)
            yield StreamEvent(
                agent=AgentName.BEHOLDER,
                type=EventType.MESSAGE,
                content="❌ Pentest negado por Adelmo. Pedido descartado e registrado no Metatron.",
            )

        yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
