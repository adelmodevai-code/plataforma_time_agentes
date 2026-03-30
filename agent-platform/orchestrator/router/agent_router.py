"""
Agent Router — decide qual(is) agente(s) acionar baseado na mensagem do usuário.

Arquitetura de papéis:
- Beholder  → ponto de entrada padrão, sentinela, coordenador
- Metatron  → documentação passiva, acionado apenas quando explicitamente pedido
- LogicX    → análise e correlação (Fase 3+)
- Vops      → operações k8s (Fase 3+)
- CyberT    → segurança e auditoria (Fase 4)
- Zerocool  → pentesting autorizado por Adelmo (Fase 4)
"""
from __future__ import annotations

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
    Roteador central. Recebe a requisição do Gateway e:
    1. Determina qual agente deve responder
    2. Carrega histórico da sessão
    3. Faz streaming dos eventos de volta

    Regras de roteamento:
    - Beholder  → DEFAULT, observabilidade, métricas, status do cluster
    - Metatron  → PASSIVO, documentação explicitamente pedida
    - LogicX    → análise, correlação, causa raiz, diagnóstico
    - Vops      → operações k8s (deploy, scale, restart, rollback)
    - CyberT    → segurança, auditoria, CVE, vulnerabilidades
    - Zerocool  → pentest autorizado (requer request_id aprovado pelo Adelmo)
    """

    # Fase 4: todos os agentes ativos
    ACTIVE_AGENTS = {
        AgentName.BEHOLDER,
        AgentName.METATRON,
        AgentName.LOGICX,
        AgentName.VOPS,
        AgentName.CYBERT,
        AgentName.ZEROCOOL,
    }

    # Palavras-chave por agente
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
                    f"Posso ajudar com observabilidade e status do ambiente agora."
                ),
            )
            yield StreamEvent(agent=AgentName.BEHOLDER, type=EventType.COMPLETE, content="")
            return

        # Salva mensagem do usuário no histórico
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
        Lógica de seleção de agente por palavras-chave.

        Precedência (ordem de verificação):
        1. Metatron   — documentação explícita
        2. Zerocool   — confirmação de pentest (palavras específicas)
        3. CyberT     — segurança, auditoria, vulnerabilidades
        4. Vops       — operações k8s
        5. LogicX     — análise e correlação
        6. Beholder   — DEFAULT
        """
        content_lower = request.content.lower()

        # 1. Metatron — documentação passiva
        if any(kw in content_lower for kw in self.METATRON_KEYWORDS):
            return AgentName.METATRON

        # 2. Zerocool — palavras muito específicas de pentest ativo
        if any(kw in content_lower for kw in self.ZEROCOOL_KEYWORDS):
            return AgentName.ZEROCOOL

        # 3. CyberT — segurança, CVE, auditoria
        if any(kw in content_lower for kw in self.CYBERT_KEYWORDS):
            return AgentName.CYBERT

        # 4. Vops — operações k8s
        if any(kw in content_lower for kw in self.VOPS_KEYWORDS):
            return AgentName.VOPS

        # 5. LogicX — análise e correlação
        if any(kw in content_lower for kw in self.LOGICX_KEYWORDS):
            return AgentName.LOGICX

        # 6. DEFAULT: Beholder
        return AgentName.BEHOLDER

    async def _handle_approval(self, request: InboundRequest) -> AsyncIterator[StreamEvent]:
        """
        Processa aprovação/negação de pentest do Zerocool.

        Fluxo de aprovação:
        1. Adelmo aprova no modal da UI
        2. UI envia MessageType.APPROVAL com metadata: {request_id, ...}
        3. Router verifica o pending no Redis
        4. Se aprovado → instancia Zerocool com request_id injetado no metadata
        5. Se negado → notifica e descarta
        """
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

        # APROVADO — executa Zerocool com request_id injetado
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

        # Cria um InboundRequest para o Zerocool com o request_id no metadata
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

        # Carrega histórico e executa Zerocool
        history = await memory.get_history(request.session_id)
        agent = _get_agent(AgentName.ZEROCOOL)

        full_response = ""
        async for event in agent.run(zerocool_request, history):
            if event.type == EventType.MESSAGE:
                full_response += event.content
            yield event

        # Salva resposta no histórico
        if full_response:
            await memory.append_message(
                request.session_id,
                ConversationMessage(
                    role="assistant",
                    agent=AgentName.ZEROCOOL,
                    content=full_response,
                ),
            )
