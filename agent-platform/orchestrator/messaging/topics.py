"""
Tópicos NATS da plataforma Agent Platform.

Convenção de nomenclatura:
    agents.<origem>.<destino>.<ação>

Todos os tópicos têm um schema de payload documentado abaixo.
"""
from __future__ import annotations


class Topics:
    # ─── Delegação entre agentes ──────────────────────────────────
    # Publicado por: LogicX, CyberT
    # Assinado por:  Orchestrator (dispatcher)
    # Payload: DelegationMessage
    AGENT_DELEGATE = "agents.delegate"

    # ─── Alertas críticos do Beholder ─────────────────────────────
    # Publicado por: Beholder (via tool alert)
    # Assinado por:  Todos os agentes (broadcast)
    # Payload: AlertMessage
    BEHOLDER_ALERT = "agents.beholder.alert"

    # ─── Arquivamento no Metatron ─────────────────────────────────
    # Publicado por: Zerocool, LogicX, Vops
    # Assinado por:  Metatron (ou Orchestrator que aciona Metatron)
    # Payload: ArchiveMessage
    METATRON_ARCHIVE = "agents.metatron.archive"

    # ─── Resultado de execução do Vops ───────────────────────────
    # Publicado por: Vops após completar operação
    # Assinado por:  LogicX, Orchestrator
    # Payload: VopsResultMessage
    VOPS_RESULT = "agents.vops.result"

    # ─── Eventos de sessão (telemetria) ──────────────────────────
    # Publicado por: Orchestrator
    # Assinado por:  Sistemas de observabilidade externos
    # Payload: SessionEvent
    SESSION_EVENT = "agents.session.event"
