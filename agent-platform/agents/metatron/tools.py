"""
Tools do agente Metatron — escrita, leitura e listagem de arquivos.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from storage.file_storage import FileMetadata, StorageError, file_storage

log = structlog.get_logger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "write_file",
        "description": (
            "Cria ou sobrescreve um arquivo na sessão atual. "
            "Use para gerar documentação, configs, JSONs e artefatos de texto. "
            "Extensões permitidas: .md, .txt, .json"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Nome do arquivo com extensão. Use kebab-case. "
                        "Ex: 'relatorio-incidente-2024-01.md', 'config.json'"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Conteúdo completo do arquivo.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "create_report",
        "description": (
            "Gera um relatório estruturado em markdown e salva em disco. "
            "Use para relatórios de incidente, auditoria, análise técnica e decisões. "
            "Formata automaticamente com cabeçalho, data, seções e rodapé."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Título do relatório.",
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["heading", "content"],
                    },
                    "description": "Seções do relatório (heading + content em markdown).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags para categorização. Ex: ['incidente', 'k8s', 'oomkilled']",
                },
            },
            "required": ["title", "sections"],
        },
    },
    {
        "name": "append_to_file",
        "description": (
            "Adiciona conteúdo ao final de um arquivo existente. "
            "Use para logs contínuos, atualizações incrementais e anotações."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nome do arquivo existente.",
                },
                "content": {
                    "type": "string",
                    "description": "Conteúdo a adicionar ao final do arquivo.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "Lista todos os arquivos gerados pelo Metatron na sessão atual.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "read_file",
        "description": (
            "Lê o conteúdo de um arquivo existente na sessão. "
            "Use antes de atualizar ou referenciar um documento anterior."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nome do arquivo a ler.",
                },
            },
            "required": ["filename"],
        },
    },
]


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    """Executa uma tool do Metatron e retorna o resultado."""
    try:
        if tool_name == "write_file":
            return await _write_file(tool_input, session_id)
        if tool_name == "create_report":
            return await _create_report(tool_input, session_id)
        if tool_name == "append_to_file":
            return await _append_to_file(tool_input, session_id)
        if tool_name == "list_files":
            return await _list_files(session_id)
        if tool_name == "read_file":
            return await _read_file(tool_input, session_id)
        return {"error": f"Tool desconhecida: {tool_name}"}
    except StorageError as e:
        log.warning("StorageError na tool do Metatron", tool=tool_name, error=str(e))
        return {"error": str(e)}
    except Exception as e:
        log.error("Erro inesperado na tool do Metatron", tool=tool_name, error=str(e), exc_info=True)
        return {"error": f"Erro interno: {str(e)}"}


# ─── implementações ───────────────────────────────────────────────────────────

async def _write_file(inp: dict, session_id: str) -> dict:
    meta = await file_storage.write_file(
        session_id=session_id,
        filename=inp["filename"],
        content=inp["content"],
    )
    return _meta_to_result(meta, created=True)


async def _create_report(inp: dict, session_id: str) -> dict:
    title: str = inp["title"]
    sections: list[dict] = inp["sections"]
    tags: list[str] = inp.get("tags") or []

    now = datetime.now(timezone.utc)
    filename = _slugify_title(title, now) + ".md"
    content = _build_report_markdown(title, sections, tags, now)

    meta = await file_storage.write_file(
        session_id=session_id,
        filename=filename,
        content=content,
    )
    return _meta_to_result(meta, created=True)


async def _append_to_file(inp: dict, session_id: str) -> dict:
    meta = await file_storage.append_to_file(
        session_id=session_id,
        filename=inp["filename"],
        content=inp["content"],
    )
    return _meta_to_result(meta, created=False)


async def _list_files(session_id: str) -> dict:
    files = await file_storage.list_files(session_id)
    return {
        "files": [
            {
                "filename": f.filename,
                "size_bytes": f.size_bytes,
                "download_url": f.download_url,
                "created_at": f.created_at,
            }
            for f in files
        ],
        "total": len(files),
    }


async def _read_file(inp: dict, session_id: str) -> dict:
    content = await file_storage.read_file(
        session_id=session_id,
        filename=inp["filename"],
    )
    return {"filename": inp["filename"], "content": content}


# ─── helpers ─────────────────────────────────────────────────────────────────

def _meta_to_result(meta: FileMetadata, *, created: bool) -> dict:
    return {
        "success": True,
        "file_created": created,
        "filename": meta.filename,
        "download_url": meta.download_url,
        "size_bytes": meta.size_bytes,
        "message": (
            f"Arquivo {'criado' if created else 'atualizado'}: `{meta.filename}` "
            f"({meta.size_bytes} bytes) → {meta.download_url}"
        ),
    }


def _slugify_title(title: str, dt: datetime) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", title.lower())
    slug = re.sub(r"\s+", "-", slug.strip())[:50]
    date_str = dt.strftime("%Y-%m-%d")
    return f"relatorio-{slug}-{date_str}" if slug else f"relatorio-{date_str}"


def _build_report_markdown(
    title: str,
    sections: list[dict],
    tags: list[str],
    dt: datetime,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"**Data:** {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Autor:** Metatron (Agent Platform)  ",
    ]
    if tags:
        lines.append(f"**Tags:** {', '.join(f'`{t}`' for t in tags)}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    for section in sections:
        lines.append(f"## {section['heading']}")
        lines.append("")
        lines.append(section["content"])
        lines.append("")

    lines += [
        "---",
        "",
        f"*Gerado automaticamente pelo Metatron em {dt.isoformat()}*",
    ]
    return "\n".join(lines)
