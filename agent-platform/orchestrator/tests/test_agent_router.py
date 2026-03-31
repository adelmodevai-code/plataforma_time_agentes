"""
Testes unitários para AgentRouter._select_agent e _get_agent.

Estratégia:
- Testa a lógica de seleção de agente por keyword e por nome direto
- Testa que _get_agent retorna HttpAgentProxy quando URLs estão configuradas
- Testa fallback embutido quando URLs estão vazias
- Não chama route() completo (exigiria Redis + Qdrant reais)
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.messages import AgentName, InboundRequest, MessageType
from router.agent_router import AgentRouter


def _req(content: str) -> InboundRequest:
    return InboundRequest(
        message_id="x",
        session_id="s",
        content=content,
        type=MessageType.USER_MESSAGE,
    )


# ─── _select_agent — nome direto ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_select_agent_direct_logicx():
    router = AgentRouter()
    result = await router._select_agent(_req("LogicX, analise o pod"))
    assert result == AgentName.LOGICX


@pytest.mark.asyncio
async def test_select_agent_direct_vops():
    router = AgentRouter()
    result = await router._select_agent(_req("vops, escale o deployment"))
    assert result == AgentName.VOPS


@pytest.mark.asyncio
async def test_select_agent_direct_cybert():
    router = AgentRouter()
    result = await router._select_agent(_req("CyberT, verifique as vulns"))
    assert result == AgentName.CYBERT


@pytest.mark.asyncio
async def test_select_agent_direct_zerocool():
    router = AgentRouter()
    result = await router._select_agent(_req("zerocool, confirme o exploit"))
    assert result == AgentName.ZEROCOOL


@pytest.mark.asyncio
async def test_select_agent_direct_metatron():
    router = AgentRouter()
    result = await router._select_agent(_req("metatron, registre isso"))
    assert result == AgentName.METATRON


@pytest.mark.asyncio
async def test_select_agent_direct_beholder():
    router = AgentRouter()
    result = await router._select_agent(_req("beholder, qual o status"))
    assert result == AgentName.BEHOLDER


# ─── _select_agent — keywords de domínio ─────────────────────────────────────

@pytest.mark.asyncio
async def test_select_agent_keyword_metatron_documentar():
    router = AgentRouter()
    result = await router._select_agent(_req("pode documentar este incidente?"))
    assert result == AgentName.METATRON


@pytest.mark.asyncio
async def test_select_agent_keyword_metatron_relatorio():
    router = AgentRouter()
    result = await router._select_agent(_req("crie um relatório de status"))
    assert result == AgentName.METATRON


@pytest.mark.asyncio
async def test_select_agent_keyword_vops_deploy():
    router = AgentRouter()
    result = await router._select_agent(_req("faça o deploy da versão 2.0"))
    assert result == AgentName.VOPS


@pytest.mark.asyncio
async def test_select_agent_keyword_vops_pod():
    router = AgentRouter()
    result = await router._select_agent(_req("o pod está crashando"))
    assert result == AgentName.VOPS


@pytest.mark.asyncio
async def test_select_agent_keyword_cybert_vulnerabilidade():
    router = AgentRouter()
    result = await router._select_agent(_req("existem vulnerabilidades no cluster?"))
    assert result == AgentName.CYBERT


@pytest.mark.asyncio
async def test_select_agent_keyword_cybert_cve():
    router = AgentRouter()
    result = await router._select_agent(_req("verifique o cve-2024-1234"))
    assert result == AgentName.CYBERT


@pytest.mark.asyncio
async def test_select_agent_keyword_zerocool_pentest():
    router = AgentRouter()
    result = await router._select_agent(_req("executar pentest no ambiente"))
    assert result == AgentName.ZEROCOOL


@pytest.mark.asyncio
async def test_select_agent_keyword_logicx_analise():
    router = AgentRouter()
    result = await router._select_agent(_req("analise a causa raiz do problema"))
    assert result == AgentName.LOGICX


@pytest.mark.asyncio
async def test_select_agent_default_beholder():
    """Mensagem genérica sem keywords → Beholder."""
    router = AgentRouter()
    result = await router._select_agent(_req("qual é o status do ambiente?"))
    assert result == AgentName.BEHOLDER


# ─── _select_agent — precedência de keywords ─────────────────────────────────

@pytest.mark.asyncio
async def test_select_agent_direct_name_takes_precedence():
    """Nome direto deve ter prioridade sobre keyword de domínio."""
    router = AgentRouter()
    # "logicx" é nome direto, mas também tem "deploy" que seria Vops
    result = await router._select_agent(_req("logicx, faça o deploy"))
    assert result == AgentName.LOGICX


@pytest.mark.asyncio
async def test_select_agent_zerocool_before_cybert():
    """Zerocool keywords verificadas antes de CyberT na lógica."""
    router = AgentRouter()
    result = await router._select_agent(_req("confirmar vulnerabilidade no cluster"))
    assert result == AgentName.ZEROCOOL


# ─── _get_agent — proxy HTTP vs embutido ─────────────────────────────────────

def test_get_agent_cybert_embedded_when_no_url():
    """Sem CYBERT_URL → importa agente embutido (não é HttpAgentProxy)."""
    import router.agent_router as router_module
    from agents.http_proxy import HttpAgentProxy
    original = router_module._CYBERT_URL
    try:
        router_module._CYBERT_URL = ""
        with patch("agents.cybert.agent.CyberTAgent.__init__", return_value=None):
            from router.agent_router import _get_agent
            agent = _get_agent(AgentName.CYBERT)
            assert not isinstance(agent, HttpAgentProxy)
    finally:
        router_module._CYBERT_URL = original


def test_get_agent_cybert_proxy_when_url_set():
    """Com CYBERT_URL → retorna HttpAgentProxy."""
    import router.agent_router as router_module
    original = router_module._CYBERT_URL
    try:
        router_module._CYBERT_URL = "http://cybert:8004"
        from router.agent_router import _get_agent
        from agents.http_proxy import HttpAgentProxy
        agent = _get_agent(AgentName.CYBERT)
        assert isinstance(agent, HttpAgentProxy)
        assert agent._base_url == "http://cybert:8004"
    finally:
        router_module._CYBERT_URL = original


def test_get_agent_zerocool_proxy_when_url_set():
    """Com ZEROCOOL_URL → retorna HttpAgentProxy."""
    import router.agent_router as router_module
    original = router_module._ZEROCOOL_URL
    try:
        router_module._ZEROCOOL_URL = "http://zerocool:8005"
        from router.agent_router import _get_agent
        from agents.http_proxy import HttpAgentProxy
        agent = _get_agent(AgentName.ZEROCOOL)
        assert isinstance(agent, HttpAgentProxy)
        assert agent._base_url == "http://zerocool:8005"
    finally:
        router_module._ZEROCOOL_URL = original


def test_get_agent_zerocool_embedded_when_no_url():
    """Sem ZEROCOOL_URL → importa agente embutido (não é HttpAgentProxy)."""
    import router.agent_router as router_module
    from agents.http_proxy import HttpAgentProxy
    original = router_module._ZEROCOOL_URL
    try:
        router_module._ZEROCOOL_URL = ""
        with patch("agents.zerocool.agent.ZerocoolAgent.__init__", return_value=None):
            from router.agent_router import _get_agent
            agent = _get_agent(AgentName.ZEROCOOL)
            assert not isinstance(agent, HttpAgentProxy)
    finally:
        router_module._ZEROCOOL_URL = original


# ─── _enrich_request_with_memories ───────────────────────────────────────────

def test_enrich_request_no_memories(sample_request):
    """Sem memórias → retorna request original (mesma instância)."""
    from router.agent_router import _enrich_request_with_memories
    result = _enrich_request_with_memories(sample_request, [])
    assert result is sample_request


def test_enrich_request_with_memories(sample_request, monkeypatch):
    """Com memórias → conteúdo enriquecido inclui o original."""
    import router.agent_router as router_module
    mock_vm = MagicMock()
    mock_vm.format_for_prompt = MagicMock(return_value="[Memória relevante]")
    monkeypatch.setattr(router_module, "vector_memory", mock_vm)

    from router.agent_router import _enrich_request_with_memories
    memories = [{"content": "algo relevante", "score": 0.8}]
    result = _enrich_request_with_memories(sample_request, memories)

    assert result is not sample_request
    assert "Memória relevante" in result.content
    assert sample_request.content in result.content
    assert result.session_id == sample_request.session_id
