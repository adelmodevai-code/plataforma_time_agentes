"""
MetatronArchiver — subscriber NATS para agents.metatron.archive.

Responsabilidades:
- Assina Topics.METATRON_ARCHIVE
- Ao receber payload de Zerocool (ou LogicX/Vops): grava o relatório via FileStorage
- Todos os archives ficam em session_id fixo "pentest-archives"
- Degrada graciosamente: se FileStorage falhar, loga e não propaga exceção

Payload esperado (ArchiveMessage):
    {
      "archive_ref":    str,      # ex: "PENTEST-ABCD1234-20260331"
      "request_id":     str,
      "vulnerability":  str,
      "severity":       str,      # critical | high | medium | low
      "cvss_score":     float | null,
      "report_content": str,      # conteúdo markdown do relatório
      "archived_by":    str,      # ex: "zerocool"
      "session_id":     str | null,
      "timestamp":      str,      # ISO 8601
    }

Uso:
    from messaging.metatron_archiver import metatron_archiver
    metatron_archiver.register()   # chame ANTES de nats_bus.connect()
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import structlog

from messaging.nats_bus import nats_bus
from messaging.topics import Topics
from storage.file_storage import StorageError, file_storage as _file_storage

log = structlog.get_logger(__name__)

# Todos os arquivos de pentest vão para este "namespace" de sessão
_ARCHIVE_SESSION = "pentest-archives"


def _build_markdown(payload: dict[str, Any]) -> str:
    """Monta o arquivo .md do relatório com frontmatter de rastreabilidade."""
    archive_ref = payload.get("archive_ref", "UNKNOWN")
    request_id = payload.get("request_id", "")
    vulnerability = payload.get("vulnerability", "")
    severity = payload.get("severity", "")
    cvss = payload.get("cvss_score")
    archived_by = payload.get("archived_by", "zerocool")
    timestamp = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
    report_content = payload.get("report_content", "*(sem conteúdo)*")

    cvss_line = f"**CVSS Score:** {cvss}  \n" if cvss is not None else ""

    return (
        f"---\n"
        f"archive_ref: {archive_ref}\n"
        f"request_id: {request_id}\n"
        f"archived_at: {timestamp}\n"
        f"archived_by: {archived_by}\n"
        f"vulnerability: {vulnerability}\n"
        f"severity: {severity}\n"
        f"cvss_score: {cvss}\n"
        f"---\n\n"
        f"# {archive_ref}\n\n"
        f"**Vulnerabilidade:** {vulnerability}  \n"
        f"**Severidade:** {severity.upper()}  \n"
        f"{cvss_line}"
        f"**Arquivado por:** {archived_by}  \n"
        f"**Data:** {timestamp}  \n\n"
        f"---\n\n"
        f"{report_content}\n\n"
        f"---\n\n"
        f"*Arquivado automaticamente pelo Metatron via NATS em {timestamp}*\n"
    )


def _safe_filename(archive_ref: str) -> str:
    """Converte archive_ref em nome de arquivo seguro para FileStorage."""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "-", archive_ref)
    return f"{safe}.md"


async def _handle_archive(payload: dict[str, Any]) -> None:
    """Handler do subscriber — recebe payload e grava via FileStorage."""
    archive_ref = payload.get("archive_ref", "UNKNOWN")
    log.info("MetatronArchiver: recebendo arquivo.", archive_ref=archive_ref)

    try:
        filename = _safe_filename(archive_ref)
        content = _build_markdown(payload)

        meta = await _file_storage.write_file(
            session_id=_ARCHIVE_SESSION,
            filename=filename,
            content=content,
        )
        log.info(
            "MetatronArchiver: arquivo gravado com sucesso.",
            archive_ref=archive_ref,
            filename=meta.filename,
            download_url=meta.download_url,
            size_bytes=meta.size_bytes,
        )

    except StorageError as e:
        log.error(
            "MetatronArchiver: StorageError ao gravar arquivo.",
            archive_ref=archive_ref,
            error=str(e),
        )
    except Exception as e:
        log.error(
            "MetatronArchiver: erro inesperado.",
            archive_ref=archive_ref,
            error=str(e),
            exc_info=True,
        )


class MetatronArchiver:
    """
    Registra a subscrição NATS para agents.metatron.archive.
    Deve ser instanciado e registrado antes de nats_bus.connect().
    """

    def register(self) -> None:
        """Registra o handler no nats_bus (pode ser chamado antes do connect)."""
        nats_bus.subscribe(Topics.METATRON_ARCHIVE, _handle_archive)
        log.info("MetatronArchiver: subscriber registrado.", topic=Topics.METATRON_ARCHIVE)


# Singleton global
metatron_archiver = MetatronArchiver()
