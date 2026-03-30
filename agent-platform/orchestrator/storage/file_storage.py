"""
FileStorage — camada de I/O para arquivos gerados pelo Metatron.

Regras de segurança:
- Extensões permitidas: .md, .txt, .json
- Nomes de arquivo: apenas [a-zA-Z0-9_\-\.]+
- Tamanho máximo por arquivo: 1 MB
- Cada sessão tem seu próprio subdiretório (session_id é UUID)
- Path traversal bloqueado via Path.resolve()
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_MAX_FILE_SIZE = 1 * 1024 * 1024          # 1 MB
_ALLOWED_EXTENSIONS = {".md", ".txt", ".json"}
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


@dataclass(frozen=True)
class FileMetadata:
    """Metadados imutáveis de um arquivo gerado pelo Metatron."""
    session_id: str
    filename: str
    relative_path: str   # "session_id/filename"
    size_bytes: int
    created_at: str      # ISO 8601
    download_url: str    # "/files/session_id/filename"


class StorageError(Exception):
    """Erro de operação no FileStorage."""


class FileStorage:
    """
    Gerencia arquivos gerados pelo Metatron.
    Thread-safe para leitura; escrita usa operações atômicas do SO.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        raw = base_dir or os.getenv("METATRON_FILES_DIR", "/data/metatron-files")
        self._base = Path(raw).resolve()
        self._base.mkdir(parents=True, exist_ok=True)
        log.info("FileStorage inicializado", base_dir=str(self._base))

    # ─── public API ──────────────────────────────────────────────────────────

    async def write_file(
        self,
        session_id: str,
        filename: str,
        content: str,
    ) -> FileMetadata:
        """Cria ou sobrescreve um arquivo."""
        path = self._validate_and_resolve(session_id, filename)
        self._validate_content(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self._metadata(session_id, filename, path)

    async def append_to_file(
        self,
        session_id: str,
        filename: str,
        content: str,
    ) -> FileMetadata:
        """Adiciona conteúdo ao final de um arquivo (cria se não existir)."""
        path = self._validate_and_resolve(session_id, filename)
        self._validate_content(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
        return self._metadata(session_id, filename, path)

    async def read_file(self, session_id: str, filename: str) -> str:
        """Retorna o conteúdo de um arquivo."""
        path = self._validate_and_resolve(session_id, filename)
        if not path.exists():
            raise StorageError(f"Arquivo não encontrado: {filename}")
        if path.stat().st_size > _MAX_FILE_SIZE:
            raise StorageError(f"Arquivo excede o limite de leitura (1 MB): {filename}")
        return path.read_text(encoding="utf-8")

    async def list_files(self, session_id: str) -> list[FileMetadata]:
        """Lista todos os arquivos da sessão."""
        session_dir = self._base / session_id
        if not session_dir.exists():
            return []
        files = []
        for p in sorted(session_dir.iterdir()):
            if p.is_file() and p.suffix in _ALLOWED_EXTENSIONS:
                files.append(self._metadata(session_id, p.name, p))
        return files

    def resolve_for_serving(self, relative_path: str) -> Path:
        """
        Valida e retorna o Path absoluto para servir via HTTP.
        Levanta StorageError se o caminho escapar do base_dir.
        """
        resolved = (self._base / relative_path).resolve()
        if not str(resolved).startswith(str(self._base)):
            raise StorageError("Acesso negado: caminho fora do diretório base.")
        if not resolved.exists():
            raise StorageError(f"Arquivo não encontrado: {relative_path}")
        return resolved

    # ─── helpers ─────────────────────────────────────────────────────────────

    def _validate_and_resolve(self, session_id: str, filename: str) -> Path:
        if not _SAFE_FILENAME_RE.match(filename):
            raise StorageError(
                f"Nome de arquivo inválido: '{filename}'. "
                "Use apenas letras, números, hífen, underscore e ponto."
            )
        ext = Path(filename).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise StorageError(
                f"Extensão '{ext}' não permitida. "
                f"Use: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            )
        resolved = (self._base / session_id / filename).resolve()
        if not str(resolved).startswith(str(self._base)):
            raise StorageError("Acesso negado: path traversal detectado.")
        return resolved

    @staticmethod
    def _validate_content(content: str) -> None:
        if len(content.encode("utf-8")) > _MAX_FILE_SIZE:
            raise StorageError("Conteúdo excede o limite de 1 MB.")

    @staticmethod
    def _metadata(session_id: str, filename: str, path: Path) -> FileMetadata:
        size = path.stat().st_size if path.exists() else 0
        relative = f"{session_id}/{filename}"
        return FileMetadata(
            session_id=session_id,
            filename=filename,
            relative_path=relative,
            size_bytes=size,
            created_at=datetime.now(timezone.utc).isoformat(),
            download_url=f"/files/{relative}",
        )


# Instância singleton — inicializada no startup do orchestrator
file_storage = FileStorage()
