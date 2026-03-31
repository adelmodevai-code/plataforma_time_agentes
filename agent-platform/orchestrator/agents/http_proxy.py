"""
HttpAgentProxy — proxy HTTP/SSE para agentes executando como microserviços K8s.

Implementa a mesma interface de `agent.run(request, history)` que os agentes
embutidos — o router não precisa saber se o agente é local ou remoto.

Uso:
    proxy = HttpAgentProxy(base_url="http://cybert-service:8004", agent_name="CyberT")
    async for event in proxy.run(request, history):
        yield event
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx
import structlog

from models.messages import AgentName, ConversationMessage, EventType, InboundRequest, StreamEvent

log = structlog.get_logger(__name__)

_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "120"))  # segundos


class HttpAgentProxy:
    """
    Proxy que encaminha chamadas de agente para um microserviço HTTP.

    O microserviço deve expor:
        POST /run  → aceita RunRequest JSON, responde SSE com StreamEvent
        GET  /health → health check
    """

    def __init__(self, base_url: str, agent_name: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_enum = AgentName(agent_name)

    async def run(
        self,
        request: InboundRequest,
        history: list[ConversationMessage],
    ) -> AsyncIterator[StreamEvent]:
        payload = {
            "request": request.model_dump(),
            "history": [h.model_dump() for h in history],
        }
        url = f"{self._base_url}/run"

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()

                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str == "[DONE]":
                            return

                        try:
                            data = json.loads(data_str)
                            yield StreamEvent(**data)
                        except (json.JSONDecodeError, TypeError, ValueError) as e:
                            log.warning(
                                "HttpProxy: evento SSE malformado — ignorado.",
                                agent=self._agent_enum.value,
                                error=str(e),
                                raw=data_str[:200],
                            )

        except httpx.ConnectError:
            log.error(
                "HttpProxy: microserviço indisponível.",
                agent=self._agent_enum.value,
                url=url,
            )
            yield StreamEvent(
                agent=self._agent_enum,
                type=EventType.ERROR,
                content=f"❌ {self._agent_enum.value} microserviço indisponível. Verifique o pod em k8s.",
            )
            yield StreamEvent(agent=self._agent_enum, type=EventType.COMPLETE, content="")

        except httpx.HTTPStatusError as e:
            log.error(
                "HttpProxy: resposta HTTP inesperada.",
                agent=self._agent_enum.value,
                status=e.response.status_code,
            )
            yield StreamEvent(
                agent=self._agent_enum,
                type=EventType.ERROR,
                content=f"❌ {self._agent_enum.value} retornou erro HTTP {e.response.status_code}.",
            )
            yield StreamEvent(agent=self._agent_enum, type=EventType.COMPLETE, content="")

        except Exception as e:
            log.error(
                "HttpProxy: erro inesperado.",
                agent=self._agent_enum.value,
                error=str(e),
                exc_info=True,
            )
            yield StreamEvent(
                agent=self._agent_enum,
                type=EventType.ERROR,
                content=f"❌ Erro ao contatar {self._agent_enum.value}: {str(e)}",
            )
            yield StreamEvent(agent=self._agent_enum, type=EventType.COMPLETE, content="")
