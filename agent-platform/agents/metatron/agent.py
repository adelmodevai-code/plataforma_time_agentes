"""
Metatron Agent — Documentação e Memória.
Usa a API Claude com streaming para respostas em tempo real.
"""
from __future__ import annotations

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
from agents.metatron.prompts import SYSTEM_PROMPT, build_history_context

log = structlog.get_logger(__name__)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")


class MetatronAgent:
    """
    Agente Metatron — usa Claude API com streaming.
    Cada instância é stateless; o estado fica no Redis (memory).
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
        """Processa a mensagem e faz yield de eventos de streaming."""

        log.info(
            "Metatron processando",
            session_id=request.session_id,
            content_preview=request.content[:80],
        )

        # Indica que está "digitando"
        yield StreamEvent(
            agent=AgentName.METATRON,
            type=EventType.TYPING,
            content="",
        )

        # Monta histórico de mensagens
        messages = build_history_context(history)
        # Adiciona a mensagem atual
        messages.append({"role": "user", "content": request.content})

        try:
            # Streaming com Claude API
            async with self.client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield StreamEvent(
                        agent=AgentName.METATRON,
                        type=EventType.MESSAGE,
                        content=text,
                    )

            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.COMPLETE,
                content="",
            )

        except anthropic.APIConnectionError as e:
            log.error("Falha de conexão com API Claude", error=str(e))
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.ERROR,
                content="❌ Não foi possível conectar à API Claude. Verifique a conexão.",
            )
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.COMPLETE,
                content="",
            )

        except anthropic.RateLimitError:
            log.warning("Rate limit atingido na API Claude")
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.ERROR,
                content="⚠️ Rate limit da API Claude atingido. Tente novamente em alguns segundos.",
            )
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.COMPLETE,
                content="",
            )

        except Exception as e:
            log.error("Erro inesperado no Metatron", error=str(e), exc_info=True)
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.ERROR,
                content=f"❌ Erro interno: {str(e)}",
            )
            yield StreamEvent(
                agent=AgentName.METATRON,
                type=EventType.COMPLETE,
                content="",
            )
