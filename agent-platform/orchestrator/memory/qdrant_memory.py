"""
Memória vetorial de longo prazo usando Qdrant.

Arquitetura:
- Uma collection única: `agent_platform_memory`
- Cada ponto = uma troca de mensagem (user + agent response)
- Payload rico: agent, session_id, role, timestamp, tags
- Busca semântica por agente e por contexto geral

Uso:
    from memory.qdrant_memory import vector_memory

    # Armazenar
    await vector_memory.store(
        agent="Beholder",
        session_id="abc123",
        content="CPU do pod X está em 98%",
        role="assistant",
        metadata={"namespace": "agent-platform"}
    )

    # Buscar
    memories = await vector_memory.search(
        agent="Beholder",
        query="problema de CPU nos pods",
        top_k=5
    )
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from memory.embeddings import embed, embed_batch, EMBEDDING_DIM

log = structlog.get_logger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "agent_platform_memory"

# Limite de caracteres por chunk armazenado
MAX_CONTENT_LENGTH = 2000


class VectorMemory:
    """
    Interface de memória vetorial sobre Qdrant.
    Degradação graciosa: se Qdrant não estiver disponível,
    loga o erro e continua sem falhar.
    """

    def __init__(self):
        self._client = None
        self._available = False

    async def connect(self):
        """Inicializa cliente Qdrant e cria a collection se não existir."""
        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = AsyncQdrantClient(url=QDRANT_URL)

            # Verifica se a collection já existe
            collections = await self._client.get_collections()
            existing = [c.name for c in collections.collections]

            if COLLECTION_NAME not in existing:
                await self._client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=EMBEDDING_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                log.info(
                    "Collection Qdrant criada.",
                    collection=COLLECTION_NAME,
                    dim=EMBEDDING_DIM,
                )
            else:
                log.info("Collection Qdrant já existe.", collection=COLLECTION_NAME)

            self._available = True
            log.info("Qdrant conectado.", url=QDRANT_URL)

        except ImportError:
            log.error("qdrant-client não instalado. Memória vetorial desativada.")
        except Exception as e:
            log.warning(
                "Qdrant não disponível — memória vetorial desativada.",
                error=str(e),
            )

    async def disconnect(self):
        """Fecha conexão com Qdrant."""
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        self._available = False
        log.info("Qdrant desconectado.")

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    # ─────────────────────────────────────────────────────────────────
    # store
    # ─────────────────────────────────────────────────────────────────

    async def store(
        self,
        agent: str,
        session_id: str,
        content: str,
        role: str = "assistant",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Armazena uma memória no Qdrant.

        Args:
            agent:      Nome do agente (Beholder, LogicX, etc.)
            session_id: ID da sessão WebSocket
            content:    Texto a armazenar (pergunta ou resposta)
            role:       "user" ou "assistant"
            metadata:   Dados extras (namespace, severity, request_id, etc.)

        Returns:
            True se armazenado com sucesso, False caso contrário.
        """
        if not self.available:
            return False

        # Trunca conteúdo muito longo
        content_trimmed = content[:MAX_CONTENT_LENGTH]
        if not content_trimmed.strip():
            return False

        try:
            from qdrant_client.models import PointStruct

            vector = await embed(content_trimmed)
            if vector is None:
                log.warning("Embedding falhou — memória não armazenada.")
                return False

            point_id = str(uuid.uuid4())
            payload = {
                "agent": agent,
                "session_id": session_id,
                "role": role,
                "content": content_trimmed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **(metadata or {}),
            }

            await self._client.upsert(
                collection_name=COLLECTION_NAME,
                points=[PointStruct(id=point_id, vector=vector, payload=payload)],
            )

            log.debug(
                "Memória armazenada.",
                agent=agent,
                session_id=session_id[:8],
                role=role,
                chars=len(content_trimmed),
            )
            return True

        except Exception as e:
            log.error("Erro ao armazenar memória no Qdrant", error=str(e))
            return False

    # ─────────────────────────────────────────────────────────────────
    # search
    # ─────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        agent: str | None = None,
        top_k: int = 5,
        score_threshold: float = 0.60,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Busca memórias semanticamente relevantes.

        Args:
            query:           Texto de busca (normalmente a mensagem do usuário)
            agent:           Filtra por agente específico (None = todos)
            top_k:           Número máximo de resultados
            score_threshold: Score mínimo de similaridade (0-1)
            session_id:      Filtra por sessão específica (None = todas)

        Returns:
            Lista de dicts com content, agent, role, timestamp, score
        """
        if not self.available:
            return []

        if not query.strip():
            return []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

            vector = await embed(query)
            if vector is None:
                return []

            # Monta filtro dinâmico
            conditions = []
            if agent:
                conditions.append(
                    FieldCondition(key="agent", match=MatchValue(value=agent))
                )
            if session_id:
                conditions.append(
                    FieldCondition(key="session_id", match=MatchValue(value=session_id))
                )

            query_filter = Filter(must=conditions) if conditions else None

            results = await self._client.search(
                collection_name=COLLECTION_NAME,
                query_vector=vector,
                query_filter=query_filter,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )

            memories = []
            for hit in results:
                payload = hit.payload or {}
                memories.append({
                    "content":    payload.get("content", ""),
                    "agent":      payload.get("agent", ""),
                    "role":       payload.get("role", ""),
                    "timestamp":  payload.get("timestamp", ""),
                    "session_id": payload.get("session_id", ""),
                    "score":      round(hit.score, 3),
                    # campos extras (namespace, severity, etc.)
                    "metadata": {
                        k: v for k, v in payload.items()
                        if k not in ("content", "agent", "role", "timestamp", "session_id")
                    },
                })

            log.debug(
                "Busca vetorial concluída.",
                query_preview=query[:50],
                agent=agent or "all",
                results=len(memories),
            )
            return memories

        except Exception as e:
            log.error("Erro ao buscar memórias no Qdrant", error=str(e))
            return []

    # ─────────────────────────────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────────────────────────────

    def format_for_prompt(
        self,
        memories: list[dict],
        max_memories: int = 4,
    ) -> str:
        """
        Formata memórias relevantes como contexto para injetar no system prompt.

        Exemplo de saída:
            ## Memórias Relevantes (contexto de sessões anteriores)
            - [Beholder | 2026-03-28] CPU do pod orchestrator estava em 98% ...
            - [LogicX   | 2026-03-27] Causa raiz: vazamento de memória no ...
        """
        if not memories:
            return ""

        lines = ["## Memórias Relevantes (contexto de sessões anteriores)"]
        for mem in memories[:max_memories]:
            ts = mem.get("timestamp", "")[:10]  # só a data
            agent = mem.get("agent", "?")
            content = mem.get("content", "")[:300]
            score = mem.get("score", 0)
            lines.append(f"- [{agent} | {ts} | sim={score}] {content}")

        return "\n".join(lines)

    async def collection_info(self) -> dict | None:
        """Retorna informações sobre a collection (tamanho, vetores, etc.)."""
        if not self.available:
            return None
        try:
            info = await self._client.get_collection(COLLECTION_NAME)
            return {
                "name": COLLECTION_NAME,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception as e:
            log.error("Erro ao buscar info da collection", error=str(e))
            return None


# Singleton global
vector_memory = VectorMemory()
