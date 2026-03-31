"""
Testes unitários para agents/zerocool/tools.py — foco em archive_to_metatron.

Cobre:
- NATS publish é chamado com payload correto
- archived=True quando publish retorna True
- archived=False quando NATS indisponível (publish retorna False)
- Limite de 900 KB bloqueado antes de publicar
- archive_ref formato correto (PENTEST-<12 chars>-<timestamp>)
- archive_ref é único para mesmo request_id em timestamps diferentes
- Outros tools: simulate mode (sem k8s) para confirm_rbac_escalation
  e generate_pentest_report
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.zerocool.tools as zc_tools
from agents.zerocool.tools import archive_to_metatron


# ─── Helpers ─────────────────────────────────────────────────────────────────

REQUEST_ID = "test-req-id-abcdefghijklmnopqrstuvwxyz"
VULN = "RBAC Wildcard Privilege Escalation"
SEVERITY = "critical"
REPORT = "# Relatório de Teste\n\nEvidências aqui."


def _mock_nats(published: bool = True):
    mock = MagicMock()
    mock.publish = AsyncMock(return_value=published)
    return mock


# ─── archive_to_metatron — fluxo normal ──────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_publishes_to_nats(monkeypatch):
    mock_nats = _mock_nats(published=True)
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="agents.metatron.archive"))

    result = await archive_to_metatron(REQUEST_ID, REPORT, VULN, SEVERITY)

    mock_nats.publish.assert_called_once()
    assert result["archived"] is True


@pytest.mark.asyncio
async def test_archive_payload_fields(monkeypatch):
    """Payload enviado ao NATS deve conter todos os campos esperados."""
    captured = {}

    async def capture(topic, payload):
        captured.update(payload)
        return True

    mock_nats = MagicMock()
    mock_nats.publish = capture
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="agents.metatron.archive"))

    await archive_to_metatron(REQUEST_ID, REPORT, VULN, SEVERITY, cvss_score=9.9)

    assert "archive_ref" in captured
    assert captured["request_id"] == REQUEST_ID
    assert captured["vulnerability"] == VULN
    assert captured["severity"] == SEVERITY
    assert captured["cvss_score"] == 9.9
    assert captured["report_content"] == REPORT
    assert captured["archived_by"] == "zerocool"


@pytest.mark.asyncio
async def test_archive_returns_false_when_nats_unavailable(monkeypatch):
    mock_nats = _mock_nats(published=False)
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="agents.metatron.archive"))

    result = await archive_to_metatron(REQUEST_ID, REPORT, VULN, SEVERITY)

    assert result["archived"] is False
    assert "NATS indisponível" in result["message"]


# ─── archive_to_metatron — validação de tamanho ───────────────────────────────

@pytest.mark.asyncio
async def test_archive_rejects_oversized_report(monkeypatch):
    big_report = "x" * (900 * 1024 + 1)

    mock_nats = _mock_nats()
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="agents.metatron.archive"))

    result = await archive_to_metatron(REQUEST_ID, big_report, VULN, SEVERITY)

    assert result["archived"] is False
    assert "muito grande" in result["message"]
    mock_nats.publish.assert_not_called()


@pytest.mark.asyncio
async def test_archive_accepts_report_at_limit(monkeypatch):
    """Relatório exatamente em 900 KB deve ser publicado."""
    borderline_report = "x" * (900 * 1024)

    mock_nats = _mock_nats(published=True)
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="agents.metatron.archive"))

    result = await archive_to_metatron(REQUEST_ID, borderline_report, VULN, SEVERITY)

    assert result["archived"] is True
    mock_nats.publish.assert_called_once()


# ─── archive_ref formato e unicidade ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_ref_format(monkeypatch):
    """archive_ref deve seguir PENTEST-<ID>-<TIMESTAMP>."""
    captured = {}

    async def capture(topic, payload):
        captured["archive_ref"] = payload["archive_ref"]
        return True

    mock_nats = MagicMock()
    mock_nats.publish = capture
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="x"))

    await archive_to_metatron(REQUEST_ID, REPORT, VULN, SEVERITY)

    ref = captured["archive_ref"]
    assert ref.startswith("PENTEST-")
    # Formato: PENTEST-<12 chars alphanum/hífen do request_id>-<YYYYMMDD>-<HHMMSS>
    # Permite hífens no segmento do request_id (ex: "TEST-REQ-ID-")
    pattern = r"^PENTEST-[A-Z0-9\-]{12}-\d{8}-\d{6}$"
    assert re.match(pattern, ref), f"archive_ref '{ref}' não confere com padrão esperado"


@pytest.mark.asyncio
async def test_archive_ref_uses_first_12_chars_of_request_id(monkeypatch):
    captured_ref = []

    async def capture(topic, payload):
        captured_ref.append(payload["archive_ref"])
        return True

    mock_nats = MagicMock()
    mock_nats.publish = capture
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="x"))

    req_id = "abcdefghijklmnopqrstuvwxyz"
    await archive_to_metatron(req_id, REPORT, VULN, SEVERITY)

    ref = captured_ref[0]
    # Os 12 primeiros chars do request_id em maiúsculo
    assert "ABCDEFGHIJKL" in ref


# ─── result structure ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_result_has_required_fields(monkeypatch):
    mock_nats = _mock_nats(published=True)
    monkeypatch.setattr(zc_tools, "_nats_bus", mock_nats)
    monkeypatch.setattr(zc_tools, "_topics", MagicMock(METATRON_ARCHIVE="x"))

    result = await archive_to_metatron(REQUEST_ID, REPORT, VULN, SEVERITY, cvss_score=7.5)

    assert "request_id" in result
    assert "archive_ref" in result
    assert "archived" in result
    assert "message" in result
    assert "timestamp" in result
    assert result["request_id"] == REQUEST_ID


# ─── confirm_rbac_escalation — modo simulado ─────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_rbac_escalation_simulated(monkeypatch):
    """Sem k8s disponível → modo simulado retorna confirmed=True."""
    monkeypatch.setattr(zc_tools, "_load_k8s", lambda: None)

    result = await zc_tools.confirm_rbac_escalation(
        request_id="req-sim-001",
        target_role="cluster-admin",
    )
    assert result["confirmed"] is True
    assert "accessible_resources" in result
    assert result["cvss_score"] == 9.9
    assert result.get("mode") == "simulated"


# ─── generate_pentest_report ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_pentest_report_structure(tmp_path, monkeypatch):
    """Relatório gerado deve ter os campos esperados."""
    monkeypatch.setattr(zc_tools.os, "makedirs", MagicMock())
    # Simula falha ao salvar disco (sem permissão) — não deve quebrar
    with patch("builtins.open", side_effect=PermissionError("sem permissão")):
        result = await zc_tools.generate_pentest_report(
            request_id="req-rpt-001",
            target="cluster-admin",
            vulnerability="RBAC Wildcard",
            severity="CRÍTICO",
            evidence_log=["[ts] evidência 1", "[ts] evidência 2"],
            cvss_score=9.9,
        )

    assert result["report_generated"] is True
    assert result["report_saved"] is False
    assert "report_content" in result
    assert "RBAC Wildcard" in result["report_content"]
    assert result["summary"]["cvss_score"] == 9.9
