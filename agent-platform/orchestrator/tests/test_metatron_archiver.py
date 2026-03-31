"""
Testes unitários para MetatronArchiver.

Cobre:
- _safe_filename: caracteres especiais, extensão .md
- _build_markdown: frontmatter, campos esperados, cvss_score opcional
- _handle_archive: arquivo gravado no FileStorage correto
- _handle_archive: StorageError é capturada sem propagar
- _handle_archive: payload parcial (campos ausentes) não quebra
- register(): assinatura NATS registrada corretamente
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import messaging.metatron_archiver as archiver_module
from messaging.metatron_archiver import (
    _ARCHIVE_SESSION,
    _build_markdown,
    _handle_archive,
    _safe_filename,
    metatron_archiver,
)
from storage.file_storage import StorageError


# ─── _safe_filename ───────────────────────────────────────────────────────────

def test_safe_filename_basic():
    assert _safe_filename("PENTEST-ABC123-20260331") == "PENTEST-ABC123-20260331.md"


def test_safe_filename_replaces_special_chars():
    result = _safe_filename("PENTEST ABC/123")
    assert " " not in result
    assert "/" not in result
    assert result.endswith(".md")


def test_safe_filename_allows_alphanum_hyphen_underscore():
    result = _safe_filename("my-report_v1")
    assert result == "my-report_v1.md"


# ─── _build_markdown ──────────────────────────────────────────────────────────

def test_build_markdown_contains_frontmatter():
    payload = {
        "archive_ref": "PENTEST-XYZ-001",
        "request_id": "req-001",
        "vulnerability": "RBAC Wildcard",
        "severity": "critical",
        "cvss_score": 9.9,
        "report_content": "## Evidências",
        "archived_by": "zerocool",
        "timestamp": "2026-03-31T10:00:00Z",
    }
    md = _build_markdown(payload)
    assert "---" in md
    assert "archive_ref: PENTEST-XYZ-001" in md
    assert "request_id: req-001" in md
    assert "severity: critical" in md


def test_build_markdown_contains_report_content():
    payload = {
        "archive_ref": "REF-001",
        "report_content": "## Detalhes do exploit",
        "vulnerability": "SQL Injection",
        "severity": "high",
    }
    md = _build_markdown(payload)
    assert "## Detalhes do exploit" in md


def test_build_markdown_cvss_line_present_when_score_provided():
    payload = {"cvss_score": 7.5, "archive_ref": "R", "vulnerability": "V", "severity": "high"}
    md = _build_markdown(payload)
    assert "**CVSS Score:** 7.5" in md


def test_build_markdown_cvss_line_absent_when_none():
    payload = {"cvss_score": None, "archive_ref": "R", "vulnerability": "V", "severity": "high"}
    md = _build_markdown(payload)
    assert "**CVSS Score:**" not in md


def test_build_markdown_severity_uppercased():
    payload = {"severity": "low", "archive_ref": "R", "vulnerability": "V"}
    md = _build_markdown(payload)
    assert "**Severidade:** LOW" in md


# ─── _handle_archive ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_archive_writes_to_correct_session(tmp_path, monkeypatch):
    """Arquivo deve ser gravado no session_id _ARCHIVE_SESSION."""
    from storage.file_storage import FileStorage

    fs = FileStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(archiver_module, "_file_storage", fs)

    payload = {
        "archive_ref": "PENTEST-ABCDEF-20260331",
        "request_id": "req-test",
        "vulnerability": "RBAC Wildcard",
        "severity": "critical",
        "cvss_score": 9.9,
        "report_content": "## Evidências detalhadas",
        "archived_by": "zerocool",
        "timestamp": "2026-03-31T12:00:00Z",
    }

    await _handle_archive(payload)

    files = await fs.list_files(_ARCHIVE_SESSION)
    assert len(files) == 1
    assert files[0].filename == "PENTEST-ABCDEF-20260331.md"


@pytest.mark.asyncio
async def test_handle_archive_file_contains_frontmatter(tmp_path, monkeypatch):
    from storage.file_storage import FileStorage

    fs = FileStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(archiver_module, "_file_storage", fs)

    payload = {
        "archive_ref": "PENTEST-FRONT-20260331",
        "request_id": "req-fm",
        "vulnerability": "XSS",
        "severity": "medium",
        "report_content": "conteúdo do relatório",
        "timestamp": "2026-03-31T13:00:00Z",
    }

    await _handle_archive(payload)

    content = await fs.read_file(_ARCHIVE_SESSION, "PENTEST-FRONT-20260331.md")
    assert "archive_ref: PENTEST-FRONT-20260331" in content
    assert "XSS" in content


@pytest.mark.asyncio
async def test_handle_archive_storage_error_does_not_propagate(monkeypatch):
    """StorageError deve ser capturada sem propagar exceção."""
    mock_fs = MagicMock()
    mock_fs.write_file = AsyncMock(side_effect=StorageError("disco cheio"))
    monkeypatch.setattr(archiver_module, "_file_storage", mock_fs)

    payload = {
        "archive_ref": "PENTEST-ERR-001",
        "vulnerability": "Test",
        "severity": "low",
        "report_content": "conteúdo",
    }

    # Não deve levantar exceção
    await _handle_archive(payload)


@pytest.mark.asyncio
async def test_handle_archive_partial_payload_uses_defaults(tmp_path, monkeypatch):
    """Payload sem campos opcionais deve usar defaults e não quebrar."""
    from storage.file_storage import FileStorage

    fs = FileStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(archiver_module, "_file_storage", fs)

    # Apenas archive_ref obrigatório na prática
    payload = {"archive_ref": "PENTEST-MIN-001"}

    await _handle_archive(payload)

    files = await fs.list_files(_ARCHIVE_SESSION)
    assert len(files) == 1


@pytest.mark.asyncio
async def test_handle_archive_missing_archive_ref_uses_unknown(tmp_path, monkeypatch):
    """Sem archive_ref → usa 'UNKNOWN' como fallback."""
    from storage.file_storage import FileStorage

    fs = FileStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(archiver_module, "_file_storage", fs)

    await _handle_archive({})

    files = await fs.list_files(_ARCHIVE_SESSION)
    assert len(files) == 1
    assert "UNKNOWN" in files[0].filename


# ─── register() ──────────────────────────────────────────────────────────────

def test_register_subscribes_to_metatron_archive(monkeypatch):
    """register() deve chamar nats_bus.subscribe com o tópico correto."""
    mock_nats = MagicMock()
    monkeypatch.setattr(archiver_module, "nats_bus", mock_nats)

    from messaging.topics import Topics
    metatron_archiver.register()

    mock_nats.subscribe.assert_called_once_with(Topics.METATRON_ARCHIVE, _handle_archive)
