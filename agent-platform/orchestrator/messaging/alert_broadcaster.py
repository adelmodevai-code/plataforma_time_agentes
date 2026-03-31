"""
AlertBroadcaster — loop proativo do Beholder para alertas Prometheus.

Responsabilidades:
- Polls list_active_alerts a cada ALERT_POLL_INTERVAL segundos
- Publica alertas firing novos em agents.beholder.alert via NATS
- Deduplicação por fingerprint (alertname + labels): não republica enquanto ativo
- Degrada graciosamente se Prometheus ou NATS estiverem offline

Uso:
    from messaging.alert_broadcaster import alert_broadcaster

    alert_broadcaster.start()   # no lifespan do FastAPI
    await alert_broadcaster.stop()
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import structlog

from agents.beholder.tools import list_active_alerts
from messaging.nats_bus import nats_bus
from messaging.topics import Topics

log = structlog.get_logger(__name__)

POLL_INTERVAL = int(os.getenv("ALERT_POLL_INTERVAL", "60"))  # segundos


def _fingerprint(alert: dict[str, Any]) -> str:
    """Fingerprint único: SHA-256(alertname + labels sorted)[:16]."""
    key = json.dumps(
        {
            "name": alert.get("name", ""),
            "labels": dict(sorted(alert.get("labels", {}).items())),
        },
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class AlertBroadcaster:
    """
    Loop de polling que detecta alertas firing no Prometheus e publica no NATS.

    Ciclo de vida:
        start() → cria asyncio.Task em background
        stop()  → cancela a task graciosamente
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._seen: set[str] = set()  # fingerprints ativos já publicados

    # ─── lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        """Inicia o loop de polling em background. Idempotente — ignora se já ativo."""
        if self._task is not None and not self._task.done():
            log.warning("AlertBroadcaster já está em execução — start() ignorado.")
            return
        self._task = asyncio.create_task(
            self._poll_loop(), name="beholder-alert-broadcaster"
        )
        log.info("AlertBroadcaster iniciado.", interval_seconds=POLL_INTERVAL)

    async def stop(self) -> None:
        """Cancela o loop de polling e limpa o estado interno."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._seen.clear()  # reseta deduplicação para o próximo start()
        log.info("AlertBroadcaster encerrado.")

    # ─── loop principal ───────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._check_and_broadcast()
                await asyncio.sleep(POLL_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("AlertBroadcaster: erro no ciclo.", error=str(e))
                await asyncio.sleep(POLL_INTERVAL)

    async def _check_and_broadcast(self) -> None:
        """Consulta alertas, publica novos e limpa os resolvidos."""
        result = await list_active_alerts()

        if "error" in result:
            log.debug(
                "AlertBroadcaster: Prometheus indisponível — ciclo ignorado.",
                error=result["error"],
            )
            return

        alerts_firing = [
            a for a in result.get("alerts", []) if a.get("state") == "firing"
        ]
        current_fps: set[str] = set()

        for alert in alerts_firing:
            fp = _fingerprint(alert)
            current_fps.add(fp)

            if fp not in self._seen:
                await self._publish(alert)
                self._seen.add(fp)
                log.info(
                    "AlertBroadcaster: novo alerta publicado.",
                    alert=alert.get("name"),
                    severity=alert.get("severity"),
                )

        # Remove fingerprints de alertas já resolvidos
        resolved = self._seen - current_fps
        if resolved:
            self._seen -= resolved
            log.info("AlertBroadcaster: alertas resolvidos.", count=len(resolved))

    async def _publish(self, alert: dict[str, Any]) -> None:
        """Monta payload e publica no tópico BEHOLDER_ALERT."""
        payload: dict[str, Any] = {
            "alert_name": alert.get("name", "unknown"),
            "severity": alert.get("severity", "unknown"),
            "summary": alert.get("summary", ""),
            "labels": alert.get("labels", {}),
            "source": "beholder-poller",
            "session_id": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await nats_bus.publish(Topics.BEHOLDER_ALERT, payload)


# Singleton global
alert_broadcaster = AlertBroadcaster()
