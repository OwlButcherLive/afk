"""Pydantic models for the Agent Gateway API."""

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel


# ─── REST models ────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"


class AgentStatus(str, Enum):
    online = "online"
    offline = "offline"
    busy = "busy"


class Agent(BaseModel):
    id: str
    name: str
    status: AgentStatus = AgentStatus.online


class AgentsResponse(BaseModel):
    agents: list[Agent]


class MessageRole(str, Enum):
    user = "user"
    agent = "agent"


class Message(BaseModel):
    id: str
    agent_id: str
    role: MessageRole
    text: str
    timestamp: str  # ISO 8601


class HistoryResponse(BaseModel):
    messages: list[Message]


class Session(BaseModel):
    id: str
    agent_id: str
    title: str
    last_message_preview: str = ""
    updated_at: str


class SessionResponse(BaseModel):
    id: str
    agent_id: str
    title: str
    updated_at: str


class SessionsListResponse(BaseModel):
    sessions: list[Session]


class CreateSessionRequest(BaseModel):
    agent_id: str


# ─── Hermes models ────────────────────────────────────────────────────────────

class HermesStatusResponse(BaseModel):
    available: bool
    version: str = ""
    busy: bool = False
    error: str = ""
    executable_path: str = ""
    candidates_checked: list[str] = []
    usable: bool = False
    usable_reason: str = ""
    deep_probe_ok: bool = False
    deep_probe_error: str = ""


# ─── WebSocket message models ────────────────────────────────────────────────

class IncomingMessageType(str, Enum):
    message = "message"


class IncomingMessage(BaseModel):
    type: IncomingMessageType
    session_id: str
    agent_id: str
    text: str


class OutgoingEventType(str, Enum):
    message = "message"
    typing = "typing"
    error = "error"
    agent_status = "agent_status"


class OutgoingMessage(BaseModel):
    type: OutgoingEventType
    id: str
    agent_id: str
    role: MessageRole
    text: str
    timestamp: str


class TypingEvent(BaseModel):
    type: OutgoingEventType = OutgoingEventType.typing
    agent_id: str
    is_typing: bool


class ErrorEvent(BaseModel):
    type: OutgoingEventType = OutgoingEventType.error
    code: str
    message: str


class AgentStatusEvent(BaseModel):
    type: OutgoingEventType = OutgoingEventType.agent_status
    agent_id: str
    status: AgentStatus


def utc_now() -> str:
    """Return current UTC time as ISO 8601 with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
