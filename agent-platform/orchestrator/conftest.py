"""
Configuração global do pytest para o orchestrator.

Problema resolvido:
  Docker combina orchestrator/ e agents/ em /app/:
    COPY orchestrator/ .        → /app/agents/http_proxy.py
    COPY agents/ /app/agents/   → /app/agents/beholder/, /app/agents/zerocool/, ...

  Localmente, orchestrator/agents/ (que só tem http_proxy.py) sombrea
  agent-platform/agents/ (que tem todos os agentes reais).

  Solução: importar `agents` de orchestrator/ e estender seu __path__ para
  incluir agent-platform/agents/, replicando o merge que o Docker faz.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── sys.path + agents.__path__ fix ──────────────────────────────────────────
_ORCHESTRATOR_ROOT = Path(__file__).parent          # orchestrator/
_AGENT_PLATFORM_ROOT = _ORCHESTRATOR_ROOT.parent    # agent-platform/

# Garante que agent-platform/ esteja no sys.path (para outros pacotes de nível raiz)
if str(_AGENT_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_PLATFORM_ROOT))

# Importa o pacote `agents` como Python o resolve (orchestrator/agents/)
# e estende seu __path__ com agent-platform/agents/ — igual ao merge do Docker.
import agents as _agents_pkg  # noqa: E402  (import after sys.path manipulation)
_extra_agents = str(_AGENT_PLATFORM_ROOT / "agents")
if _extra_agents not in _agents_pkg.__path__:
    _agents_pkg.__path__.append(_extra_agents)


# ─── Fixtures compartilhadas ─────────────────────────────────────────────────

@pytest.fixture
def sample_request():
    """InboundRequest mínimo para testes."""
    from models.messages import InboundRequest, MessageType
    return InboundRequest(
        message_id="test-msg-001",
        session_id="test-session-001",
        content="Olá, preciso de ajuda",
        type=MessageType.USER_MESSAGE,
    )


@pytest.fixture
def mock_nats(monkeypatch):
    """
    Mock do nats_bus singleton.
    Retorna o mock para que os testes possam inspecionar chamadas.
    """
    import messaging.nats_bus as nats_module
    mock = MagicMock()
    mock.publish = AsyncMock(return_value=True)
    mock.subscribe = MagicMock()
    monkeypatch.setattr(nats_module, "nats_bus", mock)
    return mock


@pytest.fixture
def mock_vector_memory(monkeypatch):
    """Mock do vector_memory para isolar testes do Qdrant."""
    import router.agent_router as router_module
    mock = MagicMock()
    mock.search = AsyncMock(return_value=[])
    mock.store = AsyncMock()
    mock.format_for_prompt = MagicMock(return_value="")
    monkeypatch.setattr(router_module, "vector_memory", mock)
    return mock


@pytest.fixture
def mock_redis_memory(monkeypatch):
    """Mock do memory (Redis) para isolar testes."""
    import router.agent_router as router_module
    mock = MagicMock()
    mock.append_message = AsyncMock()
    mock.get_history = AsyncMock(return_value=[])
    mock.get_approval_pending = AsyncMock(return_value=None)
    mock.resolve_approval = AsyncMock()
    monkeypatch.setattr(router_module, "memory", mock)
    return mock


@pytest.fixture
def tmp_storage(tmp_path):
    """FileStorage isolado com diretório temporário."""
    from storage.file_storage import FileStorage
    return FileStorage(base_dir=str(tmp_path))
