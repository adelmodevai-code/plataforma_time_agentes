"""
Gerenciamento de memória de curto prazo via Redis.
Armazena histórico de conversa por session_id com TTL configurável.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import redis.asyncio as redis
import structlog

from models.messages import ConversationMessage

log = structlog.get_logger(__name__)

CONVERSATION_TTL = int(os.getenv("CONVERSATION_TTL_SECONDS", 86400))  # 24h
MAX_HISTORY_LENGTH = int(os.getenv("MAX_HISTORY_LENGTH", 50))


class RedisMemory:
    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self):
        url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self._client = redis.from_url(url, encoding="utf-8", decode_responses=True)
        await self._client.ping()
        log.info("Redis conectado", url=url)

    async def disconnect(self):
        if self._client:
            await self._client.aclose()

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}:history"

    async def append_message(self, session_id: str, message: ConversationMessage) -> None:
        """Adiciona uma mensagem ao histórico da sessão."""
        key = self._key(session_id)
        await self._client.rpush(key, message.model_dump_json())
        # Mantém apenas as últimas MAX_HISTORY_LENGTH mensagens
        await self._client.ltrim(key, -MAX_HISTORY_LENGTH, -1)
        await self._client.expire(key, CONVERSATION_TTL)

    async def get_history(self, session_id: str) -> list[ConversationMessage]:
        """Recupera o histórico completo da sessão."""
        key = self._key(session_id)
        raw_messages = await self._client.lrange(key, 0, -1)
        messages = []
        for raw in raw_messages:
            try:
                messages.append(ConversationMessage.model_validate_json(raw))
            except Exception as e:
                log.warning("Mensagem inválida no histórico", error=str(e))
        return messages

    async def clear_session(self, session_id: str) -> None:
        """Limpa o histórico de uma sessão."""
        await self._client.delete(self._key(session_id))

    async def store_approval_pending(self, request_id: str, data: dict) -> None:
        """Armazena pedido de aprovação pendente do Zerocool."""
        key = f"approval:pending:{request_id}"
        await self._client.setex(key, 3600, json.dumps(data))  # 1h para aprovar

    async def get_approval_pending(self, request_id: str) -> Optional[dict]:
        """Recupera um pedido de aprovação pendente."""
        key = f"approval:pending:{request_id}"
        raw = await self._client.get(key)
        if raw:
            return json.loads(raw)
        return None

    async def resolve_approval(self, request_id: str) -> None:
        """Remove o pedido após aprovação/negação."""
        await self._client.delete(f"approval:pending:{request_id}")


# Singleton
memory = RedisMemory()
