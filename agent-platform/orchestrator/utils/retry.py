"""
Utilitário de retry com backoff exponencial para conexões de startup.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)

_DEFAULT_MAX_RETRIES = 30   # ~15 min de tentativas com cap em 30s
_DEFAULT_BASE_DELAY = 2.0   # segundos


async def connect_with_retry(
    fn: Callable[[], Awaitable[None]],
    name: str,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_BASE_DELAY,
) -> None:
    """
    Executa fn() com retry e backoff exponencial (cap em 30s).
    Lança exceção somente após max_retries tentativas consecutivas.

    Sequência de espera: 2s, 4s, 8s, 16s, 30s, 30s, 30s, ...
    Com max_retries=30: até ~15 minutos de retry antes de desistir.
    """
    for attempt in range(1, max_retries + 1):
        try:
            await fn()
            return
        except Exception as exc:
            if attempt == max_retries:
                log.error(
                    f"{name}: todas as tentativas falharam",
                    attempts=max_retries,
                    error=str(exc),
                )
                raise
            wait = min(base_delay * (2 ** (attempt - 1)), 30.0)
            log.warning(
                f"{name}: tentativa {attempt}/{max_retries} falhou — próxima em {wait:.0f}s",
                error=str(exc),
            )
            await asyncio.sleep(wait)
