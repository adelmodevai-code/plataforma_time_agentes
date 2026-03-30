"""
Módulo de embeddings para memória vetorial.
Usa fastembed (da Qdrant) com modelo BAAI/bge-small-en-v1.5.

Características:
- Roda completamente local (sem custo, sem API externa)
- Modelo leve: 384 dimensões, ~130MB, download automático no primeiro uso
- Suporte a batch e async via run_in_executor
- Cache singleton — modelo carregado uma única vez
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import List

import structlog

log = structlog.get_logger(__name__)

# Modelo padrão — pode ser sobrescrito via env
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIM = 384  # dimensão fixa do bge-small-en-v1.5


@lru_cache(maxsize=1)
def _get_embedding_model():
    """
    Carrega o modelo fastembed uma única vez (singleton via lru_cache).
    O primeiro acesso faz download automático do modelo (~130MB).
    """
    try:
        from fastembed import TextEmbedding
        log.info("Carregando modelo de embeddings...", model=EMBEDDING_MODEL)
        model = TextEmbedding(model_name=EMBEDDING_MODEL)
        log.info("Modelo de embeddings carregado.", model=EMBEDDING_MODEL)
        return model
    except ImportError:
        log.error("fastembed não instalado. Execute: pip install fastembed")
        return None
    except Exception as e:
        log.error("Falha ao carregar modelo de embeddings", error=str(e))
        return None


async def embed(text: str) -> List[float] | None:
    """
    Gera embedding para um único texto.
    Executa em thread pool para não bloquear o event loop.
    Retorna None se o modelo não estiver disponível.
    """
    return await embed_batch([text])
    # retorna só o primeiro


async def embed_batch(texts: list[str]) -> List[float] | None:
    """
    Gera embedding para o primeiro texto da lista.
    Para busca, normalmente precisamos apenas de um vetor por vez.
    """
    if not texts:
        return None

    loop = asyncio.get_event_loop()
    try:
        def _embed():
            model = _get_embedding_model()
            if model is None:
                return None
            # fastembed retorna um gerador; pegamos o primeiro resultado
            embeddings = list(model.embed(texts[:1]))
            return embeddings[0].tolist() if embeddings else None

        result = await loop.run_in_executor(None, _embed)
        return result
    except Exception as e:
        log.error("Erro ao gerar embedding", error=str(e))
        return None


async def embed_many(texts: list[str]) -> list[List[float]]:
    """
    Gera embeddings para múltiplos textos em batch.
    Retorna lista vazia se o modelo não estiver disponível.
    """
    if not texts:
        return []

    loop = asyncio.get_event_loop()
    try:
        def _embed_many():
            model = _get_embedding_model()
            if model is None:
                return []
            embeddings = list(model.embed(texts))
            return [e.tolist() for e in embeddings]

        return await loop.run_in_executor(None, _embed_many)
    except Exception as e:
        log.error("Erro ao gerar embeddings em batch", error=str(e))
        return []
