"""
Testes unitários para AlertBroadcaster.

Cobre:
- _fingerprint: determinismo e unicidade
- _check_and_broadcast: deduplicação, publish em novo alerta, remoção ao resolver
- Erro do Prometheus é ignorado graciosamente
- start() é idempotente
- stop() limpa _seen e cancela task
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from messaging.alert_broadcaster import AlertBroadcaster, _fingerprint


# ─── _fingerprint ────────────────────────────────────────────────────────────

def test_fingerprint_deterministic():
    alert = {"name": "HighCPU", "labels": {"namespace": "prod", "pod": "app-1"}}
    assert _fingerprint(alert) == _fingerprint(alert)


def test_fingerprint_differs_by_name():
    a = {"name": "AlertA", "labels": {}}
    b = {"name": "AlertB", "labels": {}}
    assert _fingerprint(a) != _fingerprint(b)


def test_fingerprint_differs_by_labels():
    a = {"name": "X", "labels": {"env": "prod"}}
    b = {"name": "X", "labels": {"env": "staging"}}
    assert _fingerprint(a) != _fingerprint(b)


def test_fingerprint_label_order_invariant():
    """Labels em ordem diferente devem gerar o mesmo fingerprint."""
    a = {"name": "X", "labels": {"z": "1", "a": "2"}}
    b = {"name": "X", "labels": {"a": "2", "z": "1"}}
    assert _fingerprint(a) == _fingerprint(b)


def test_fingerprint_length():
    alert = {"name": "Test", "labels": {}}
    assert len(_fingerprint(alert)) == 16


# ─── _check_and_broadcast ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_alert_is_published():
    """Um alerta firing novo deve ser publicado e adicionado a _seen."""
    broadcaster = AlertBroadcaster()
    alert = {"name": "HighMem", "state": "firing", "labels": {}, "severity": "critical"}

    mock_publish = AsyncMock(return_value=True)

    with (
        patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
            return_value={"alerts": [alert]}
        )),
        patch("messaging.alert_broadcaster.nats_bus") as mock_nats,
    ):
        mock_nats.publish = mock_publish
        await broadcaster._check_and_broadcast()

    mock_publish.assert_called_once()
    assert len(broadcaster._seen) == 1


@pytest.mark.asyncio
async def test_duplicate_alert_not_republished():
    """Um alerta já em _seen não deve ser republicado."""
    broadcaster = AlertBroadcaster()
    alert = {"name": "HighMem", "state": "firing", "labels": {}, "severity": "critical"}
    fp = _fingerprint(alert)
    broadcaster._seen.add(fp)

    mock_publish = AsyncMock(return_value=True)

    with (
        patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
            return_value={"alerts": [alert]}
        )),
        patch("messaging.alert_broadcaster.nats_bus") as mock_nats,
    ):
        mock_nats.publish = mock_publish
        await broadcaster._check_and_broadcast()

    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_resolved_alert_removed_from_seen():
    """Alerta que sumiu da lista deve ser removido de _seen."""
    broadcaster = AlertBroadcaster()
    alert = {"name": "HighMem", "state": "firing", "labels": {}, "severity": "critical"}
    fp = _fingerprint(alert)
    broadcaster._seen.add(fp)

    with (
        patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
            return_value={"alerts": []}  # alerta resolvido — não aparece mais
        )),
        patch("messaging.alert_broadcaster.nats_bus"),
    ):
        await broadcaster._check_and_broadcast()

    assert fp not in broadcaster._seen


@pytest.mark.asyncio
async def test_prometheus_error_skipped():
    """Se list_active_alerts retornar 'error', o ciclo é ignorado sem exceção."""
    broadcaster = AlertBroadcaster()

    with patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
        return_value={"error": "connection refused"}
    )):
        # Não deve lançar exceção
        await broadcaster._check_and_broadcast()

    assert len(broadcaster._seen) == 0


@pytest.mark.asyncio
async def test_only_firing_alerts_published():
    """Apenas alertas com state=='firing' devem ser publicados."""
    broadcaster = AlertBroadcaster()
    alerts = [
        {"name": "Firing", "state": "firing", "labels": {}, "severity": "high"},
        {"name": "Pending", "state": "pending", "labels": {}, "severity": "low"},
        {"name": "Inactive", "state": "inactive", "labels": {}, "severity": "none"},
    ]

    mock_publish = AsyncMock(return_value=True)

    with (
        patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
            return_value={"alerts": alerts}
        )),
        patch("messaging.alert_broadcaster.nats_bus") as mock_nats,
    ):
        mock_nats.publish = mock_publish
        await broadcaster._check_and_broadcast()

    assert mock_publish.call_count == 1  # só "Firing"


# ─── start() idempotência ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_idempotent():
    """Chamar start() duas vezes não cria duas tasks."""
    broadcaster = AlertBroadcaster()

    with patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
        return_value={"alerts": []}
    )):
        broadcaster.start()
        task_first = broadcaster._task
        broadcaster.start()  # segunda chamada deve ser ignorada
        task_second = broadcaster._task

    assert task_first is task_second
    await broadcaster.stop()


@pytest.mark.asyncio
async def test_start_creates_background_task():
    broadcaster = AlertBroadcaster()

    with patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
        return_value={"alerts": []}
    )):
        broadcaster.start()
        assert broadcaster._task is not None
        assert not broadcaster._task.done()
        await broadcaster.stop()


# ─── stop() limpeza de estado ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_clears_seen():
    """stop() deve zerar _seen para permitir re-publicação após restart."""
    broadcaster = AlertBroadcaster()
    broadcaster._seen.add("some-fingerprint")

    with patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
        return_value={"alerts": []}
    )):
        broadcaster.start()
        await broadcaster.stop()

    assert len(broadcaster._seen) == 0


@pytest.mark.asyncio
async def test_stop_cancels_task():
    broadcaster = AlertBroadcaster()

    with patch("messaging.alert_broadcaster.list_active_alerts", new=AsyncMock(
        return_value={"alerts": []}
    )):
        broadcaster.start()
        task = broadcaster._task
        await broadcaster.stop()

    assert task.done()
    assert broadcaster._task is None


@pytest.mark.asyncio
async def test_stop_idempotent_when_not_started():
    """stop() sem start() não deve levantar exceção."""
    broadcaster = AlertBroadcaster()
    await broadcaster.stop()  # deve ser silencioso


# ─── _publish payload ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_payload_fields():
    """Payload publicado deve conter campos obrigatórios."""
    broadcaster = AlertBroadcaster()
    alert = {
        "name": "DiskFull",
        "state": "firing",
        "labels": {"node": "node-1"},
        "severity": "critical",
        "summary": "Disco cheio",
    }

    captured_payload: dict = {}

    async def capture_publish(topic, payload):
        captured_payload.update(payload)
        return True

    with patch("messaging.alert_broadcaster.nats_bus") as mock_nats:
        mock_nats.publish = capture_publish
        await broadcaster._publish(alert)

    assert captured_payload["alert_name"] == "DiskFull"
    assert captured_payload["severity"] == "critical"
    assert captured_payload["summary"] == "Disco cheio"
    assert captured_payload["source"] == "beholder-poller"
    assert "timestamp" in captured_payload
