"""AFK V2 domain models — durable session runtime core.

Defines the new architectural primitives:

- ServerSession    — represents one authenticated device connection
- Thread           — conversation container within a ServerSession
- Turn             — one user/agent exchange cycle within a Thread
- ThreadItem       — granular event inside a Turn (message, reasoning, tool call, etc.)
- ThreadRuntimeRoute — maps a Thread to its active AgentRuntime
- PendingApproval  — approval request that blocks thread progress
"""

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


# ─── Enums ──────────────────────────────────────────────────────────────────


class ThreadStatus(str, Enum):
    """Lifecycle state of a conversation thread."""
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class TurnStatus(str, Enum):
    """Lifecycle state of a single user/agent exchange."""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class RuntimeKind(str, Enum):
    """Which runtime adapter a thread is attached to."""
    hermes = "hermes"
    stub = "stub"
    # future: claude_code, open_code, etc.


class ConnectionHealth(str, Enum):
    """Observable health of a device connection."""
    connected = "connected"
    degraded = "degraded"
    disconnected = "disconnected"


class ThreadItemKind(str, Enum):
    """Types of events that can appear inside a Turn."""
    user_message = "user_message"
    agent_message = "agent_message"
    reasoning = "reasoning"
    command_execution = "command_execution"
    file_change = "file_change"
    approval_request = "approval_request"
    context_compaction = "context_compaction"
    system_event = "system_event"


# ─── Core models ────────────────────────────────────────────────────────────


class ServerSession(BaseModel):
    """A durable device connection backed by an authenticated SSH session.

    One ServerSession can host multiple Threads. Connection health is
    updated via heartbeats from the Android client.
    """
    id: str
    name: str = ""
    client_platform: str = "android"
    connection_health: ConnectionHealth = ConnectionHealth.disconnected
    created_at: str = ""
    updated_at: str = ""
    last_seen_at: str = ""


class Thread(BaseModel):
    """A conversation container owned by a ServerSession.

    Threads are the top-level unit of conversation. Each Thread is
    routed to an AgentRuntime via ThreadRuntimeRoute.
    """
    id: str
    server_session_id: str
    runtime_kind: RuntimeKind
    status: ThreadStatus = ThreadStatus.active
    title: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class Turn(BaseModel):
    """One user/agent exchange cycle inside a Thread.

    A Turn tracks the lifecycle of a single round: user message in,
    agent processing, agent response out. ThreadItems inside a Turn
    capture the granular events (reasoning, tool calls, etc.).
    """
    id: str
    thread_id: str
    status: TurnStatus = TurnStatus.pending
    turn_index: int = 0
    user_message_id: str | None = None
    agent_message_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class ThreadItem(BaseModel):
    """A granular event inside a Turn.

    ThreadItems form an ordered event log within each Turn. Examples:
    user message, agent reply, reasoning token stream, command execution,
    file change, approval prompt, context compaction notice.
    """
    id: str
    thread_id: str
    turn_id: str
    kind: ThreadItemKind
    index: int = 0
    role: str = ""  # "user", "agent", "system"
    content: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: str = ""


class ThreadRuntimeRoute(BaseModel):
    """Maps a Thread to an active AgentRuntime.

    This is the routing layer that determines which runtime adapter
    processes a thread's messages. The runtime_session_id can hold
    an opaque native session handle if the runtime supports it.
    """
    thread_id: str
    runtime_kind: RuntimeKind
    runtime_session_id: str | None = None
    attached_at: str = ""


class PendingApproval(BaseModel):
    """An approval request that blocks thread progress.

    Raised by the runtime when an action requires user confirmation
    (e.g. destructive command execution, file modification). The turn
    remains in running state until resolved.
    """
    id: str
    thread_id: str
    turn_id: str
    item_id: str
    kind: str = ""
    prompt: str = ""
    status: str = "pending"  # pending | approved | rejected
    created_at: str = ""
    resolved_at: str | None = None


# ─── Request / response models ──────────────────────────────────────────────


class CreateThreadRequest(BaseModel):
    server_session_id: str
    runtime_kind: RuntimeKind = RuntimeKind.hermes
    title: str = ""


class ThreadResponse(BaseModel):
    id: str
    server_session_id: str
    runtime_kind: RuntimeKind
    status: ThreadStatus
    title: str
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str
    turn_count: int = 0
    last_message_preview: str = ""


class ThreadListResponse(BaseModel):
    threads: list[ThreadResponse]


class TurnResponse(BaseModel):
    id: str
    thread_id: str
    status: TurnStatus
    turn_index: int
    items: list[ThreadItem] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


# ─── Helpers ────────────────────────────────────────────────────────────────


def utc_now() -> str:
    """Return current UTC time as ISO 8601 with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id(prefix: str = "") -> str:
    """Generate a short unique identifier."""
    import uuid
    return f"{prefix}{uuid.uuid4().hex[:12]}"
