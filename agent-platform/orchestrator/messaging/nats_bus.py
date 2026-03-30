"""
NATSBus — barramento de mensagens assíncronas entre agentes.

Responsabilidades:
- Publish: qualquer agente publica eventos (fire-and-forget)
- Subscribe: orchestrator e agentes assinam tópicos para reagir
- Degradação graciosa: se NATS não disponível, loga e continua

Uso:
    from messaging.nats_bus import nats_bus
    from messaging.topics import Topics

    # Publicar
    await nats_bus.publish(Topics.AGENT_DELEGATE, {"session_id": ..., "to": "Vops", ...})

    # Subscrever (registra handler antes de connect())
    nats_bus.subscribe(Topics.AGENT_DELEGATE, my_handler)

    # Lifecycle (no lifespan do FastAPI)
    await nats_bus.connect()
    await nats_bus.disconnect()
"""
from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")

# Handler: recebe o payload decodificado (dict)
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


class NATSBus:
    """
    Singleton de barramento NATS.
    Suporta publish/subscribe com degradação graciosa.
    """

    def __init__(self):
        self._nc = None                             # nats.aio.client.Client
        self._available = False
        self._pending_subscriptions: list[tuple[str, MessageHandler]] = []
        self._active_subscriptions: list[Any] = []

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """
        Registra um handler para um tópico.
        Pode ser chamado antes de connect() — será aplicado na conexão.
        """
        self._pending_subscriptions.append((topic, handler))
        log.debug("NATS: handler registrado.", topic=topic)

    async def connect(self) -> None:
        """Conecta ao NATS e ativa as subscrições pendentes."""
        try:
            import nats

            self._nc = await nats.connect(
                NATS_URL,
                name="agent-platform-orchestrator",
                reconnect_time_wait=2,
                max_reconnect_attempts=5,
                error_cb=self._on_error,
                disconnected_cb=self._on_disconnect,
                reconnected_cb=self._on_reconnect,
            )
            self._available = True
            log.info("NATS conectado.", url=NATS_URL)

            # Ativa subscrições que foram registradas antes do connect
            for topic, handler in self._pending_subscriptions:
                await self._subscribe(topic, handler)

        except ImportError:
            log.error("nats-py não instalado. Mensageria NATS desativada.")
        except Exception as e:
            log.warning("NATS não disponível — mensageria desativada.", error=str(e))

    async def disconnect(self) -> None:
        """Drena mensagens pendentes e fecha conexão."""
        if self._nc and self._available:
            try:
                await self._nc.drain()
            except Exception:
                pass
        self._available = False
        log.info("NATS desconectado.")

    @property
    def available(self) -> bool:
        return self._available and self._nc is not None

    # ─────────────────────────────────────────────────────────────
    # publish
    # ─────────────────────────────────────────────────────────────

    async def publish(self, topic: str, payload: dict[str, Any]) -> bool:
        """
        Publica mensagem em um tópico NATS.

        Args:
            topic:   Tópico de destino (use Topics.*)
            payload: Dicionário serializável como JSON

        Returns:
            True se publicado, False se NATS não disponível.
        """
        if not self.available:
            log.debug("NATS offline — publish ignorado.", topic=topic)
            return False

        try:
            data = json.dumps(payload, ensure_ascii=False, default=str).encode()
            await self._nc.publish(topic, data)
            log.debug("NATS: mensagem publicada.", topic=topic, bytes=len(data))
            return True
        except Exception as e:
            log.error("NATS: falha ao publicar.", topic=topic, error=str(e))
            return False

    # ─────────────────────────────────────────────────────────────
    # internal subscribe
    # ─────────────────────────────────────────────────────────────

    async def _subscribe(self, topic: str, handler: MessageHandler) -> None:
        """Cria subscrição real no NATS."""
        if not self.available:
            return

        async def _wrapper(msg):
            try:
                payload = json.loads(msg.data.decode())
                await handler(payload)
            except json.JSONDecodeError as e:
                log.error("NATS: payload inválido.", topic=topic, error=str(e))
            except Exception as e:
                log.error("NATS: erro no handler.", topic=topic, error=str(e))

        sub = await self._nc.subscribe(topic, cb=_wrapper)
        self._active_subscriptions.append(sub)
        log.info("NATS: subscrito.", topic=topic)

    # ─────────────────────────────────────────────────────────────
    # callbacks de conexão
    # ─────────────────────────────────────────────────────────────

    async def _on_error(self, e):
        log.error("NATS: erro de conexão.", error=str(e))

    async def _on_disconnect(self):
        self._available = False
        log.warning("NATS: desconectado.")

    async def _on_reconnect(self):
        self._available = True
        log.info("NATS: reconectado.")


# Singleton global
nats_bus = NATSBus()
