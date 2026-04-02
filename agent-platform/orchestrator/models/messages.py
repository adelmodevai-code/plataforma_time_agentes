"""
Modelos Pydantic compartilhados entre Orchestrator e Agents.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    USER_MESSAGE = "user_message"
    APPROVAL = "approval"
    DENIAL = "denial"
    PING = "ping"


class EventType(str, Enum):
    TYPING = "typing"
    MESSAGE = "message"
    ACTION = "action"
    APPROVAL_REQUEST = "approval_request"
    DELEGATION = "delegation"       # LogicX/CyberT delegando a outro agente
    FILE_CREATED = "file_created"   # Metatron criou/atualizou um arquivo
    COMPLETE = "complete"
    ERROR = "error"


class AgentName(str, Enum):
    METATRON = "Metatron"
    BEHOLDER = "Beholder"
    LOGICX = "LogicX"
    VOPS = "Vops"
    CYBERT = "CyberT"
    ZEROCOOL = "Zerocool"
    SYSTEM = "system"


class InboundRequest(BaseModel):
    """Payload recebido do Go Gateway."""
    message_id: str
    session_id: str
    type: MessageType
    content: str
    metadata: Optional[dict[str, Any]] = None


class StreamEvent(BaseModel):
    """Evento SSE enviado de volta ao Go Gateway."""
    agent: AgentName = AgentName.SYSTEM
    type: EventType
    content: str
    metadata: Optional[dict[str, Any]] = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_sse(self) -> str:
        """Serializa para formato Server-Sent Events."""
        return f"data: {self.model_dump_json()}\n\n"


class ApprovalRequest(BaseModel):
    """Pedido de autorização para Zerocool executar pentest."""
    request_id: str
    session_id: str
    agent: AgentName = AgentName.ZEROCOOL
    vulnerability: str
    target: str
    test_type: str
    risk_level: str  # "low" | "medium" | "high"
    description: str
    evidence_from_cybert: Optional[dict[str, Any]] = None


class ConversationMessage(BaseModel):
    """Mensagem persistida no histórico de conversa."""
    role: str  # "user" | "assistant"
    agent: Optional[AgentName] = None
    content: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class FeedbackRequest(BaseModel):
    """Feedback do usuário sobre a resposta de um agente."""
    session_id: str
    message_id: str
    agent: AgentName
    rating: str  # "positive" | "negative"
    comment: Optional[str] = None
