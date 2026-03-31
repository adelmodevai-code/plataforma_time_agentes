"""
Testes unitários para HttpAgentProxy.

Cobre:
- SSE válido: eventos parseados e gerados corretamente
- [DONE] sentinel para o stream
- ConnectError → StreamEvent(ERROR) + COMPLETE
- HTTPStatusError → StreamEvent(ERROR) + COMPLETE
- Linhas SSE malformadas são ignoradas (sem crash)
- Linhas não-data (comments, empty) são ignoradas
- Exceção genérica → StreamEvent(ERROR) + COMPLETE
"""
from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agents.http_proxy import HttpAgentProxy
from models.messages import AgentName, EventType, InboundRequest, MessageType, StreamEvent


def _make_proxy(base_url: str = "http://cybert:8004") -> HttpAgentProxy:
    return HttpAgentProxy(base_url, AgentName.CYBERT.value)


def _req() -> InboundRequest:
    return InboundRequest(
        message_id="m1",
        session_id="s1",
        content="analise segurança",
        type=MessageType.USER_MESSAGE,
    )


def _sse_lines(*events: dict) -> list[str]:
    """Gera lista de linhas SSE a partir de dicts de StreamEvent."""
    lines = []
    for ev in events:
        lines.append(f"data: {json.dumps(ev)}")
    lines.append("data: [DONE]")
    return lines


async def _async_iter(items):
    for item in items:
        yield item


# ─── parsing SSE correto ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_yields_message_events():
    proxy = _make_proxy()
    event_data = {
        "agent": "CyberT",
        "type": "message",
        "content": "Analisando vulnerabilidades...",
        "metadata": None,
        "timestamp": "2026-03-31T00:00:00Z",
    }
    lines = _sse_lines(event_data)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = MagicMock(return_value=_async_iter(lines))

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 1
    assert events[0].type == EventType.MESSAGE
    assert events[0].content == "Analisando vulnerabilidades..."
    assert events[0].agent == AgentName.CYBERT


@pytest.mark.asyncio
async def test_proxy_stops_at_done_sentinel():
    proxy = _make_proxy()
    lines = [
        f'data: {json.dumps({"agent": "CyberT", "type": "message", "content": "ok", "metadata": None, "timestamp": "2026-03-31T00:00:00Z"})}',
        "data: [DONE]",
        f'data: {json.dumps({"agent": "CyberT", "type": "message", "content": "não deve aparecer", "metadata": None, "timestamp": "2026-03-31T00:00:00Z"})}',
    ]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = MagicMock(return_value=_async_iter(lines))

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 1
    assert events[0].content == "ok"


@pytest.mark.asyncio
async def test_proxy_ignores_non_data_lines():
    proxy = _make_proxy()
    event_data = {"agent": "CyberT", "type": "complete", "content": "", "metadata": None, "timestamp": "2026-03-31T00:00:00Z"}
    lines = [
        "",                          # linha vazia
        ": keep-alive",              # comment SSE
        "event: message",            # event field (ignorado)
        f"data: {json.dumps(event_data)}",
        "data: [DONE]",
    ]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = MagicMock(return_value=_async_iter(lines))

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 1
    assert events[0].type == EventType.COMPLETE


@pytest.mark.asyncio
async def test_proxy_skips_malformed_json():
    proxy = _make_proxy()
    good_event = {"agent": "CyberT", "type": "message", "content": "válido", "metadata": None, "timestamp": "2026-03-31T00:00:00Z"}
    lines = [
        "data: {invalid json!!!}",
        f"data: {json.dumps(good_event)}",
        "data: [DONE]",
    ]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = MagicMock(return_value=_async_iter(lines))

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 1
    assert events[0].content == "válido"


# ─── error handling ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_proxy_connect_error_yields_error_and_complete():
    proxy = _make_proxy()

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 2
    assert events[0].type == EventType.ERROR
    assert "indisponível" in events[0].content
    assert events[1].type == EventType.COMPLETE


@pytest.mark.asyncio
async def test_proxy_http_status_error_yields_error_and_complete():
    proxy = _make_proxy()

    mock_response_obj = MagicMock()
    mock_response_obj.status_code = 503

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(
        side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=mock_response_obj)
    )
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 2
    assert events[0].type == EventType.ERROR
    assert "503" in events[0].content
    assert events[1].type == EventType.COMPLETE


@pytest.mark.asyncio
async def test_proxy_generic_exception_yields_error_and_complete():
    proxy = _make_proxy()

    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("boom"))
    mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.http_proxy.httpx.AsyncClient", return_value=mock_client_ctx):
        events = [e async for e in proxy.run(_req(), [])]

    assert len(events) == 2
    assert events[0].type == EventType.ERROR
    assert "boom" in events[0].content
    assert events[1].type == EventType.COMPLETE


# ─── base_url normalização ────────────────────────────────────────────────────

def test_proxy_strips_trailing_slash():
    proxy = HttpAgentProxy("http://cybert:8004/", AgentName.CYBERT.value)
    assert proxy._base_url == "http://cybert:8004"


def test_proxy_agent_enum():
    proxy = HttpAgentProxy("http://zerocool:8005", AgentName.ZEROCOOL.value)
    assert proxy._agent_enum == AgentName.ZEROCOOL
