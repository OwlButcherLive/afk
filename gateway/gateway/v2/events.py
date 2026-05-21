"""AFK V2 event streaming — snapshot and delta event models for thread state.

Provides the first proper event streaming foundation:
- ThreadSnapshot — full thread state projection
- ThreadUpdateEvent — granular state changes
- ThreadItemAppended — live item emission during turn execution
- ThreadEventKind — all event types

Design direction:
  ThreadSnapshot   → initial state on connect/reconnect
  ThreadUpdate     → incremental delta (future: Immer-style patches)
  ThreadItemAppended → live streaming during agent execution
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ─── Event kinds ────────────────────────────────────────────────────────────


class ThreadEventKind(str, Enum):
    """Types of events that can be emitted for thread state changes.

    Direction for future patches (not yet implemented):
      item_delta   → patch for a specific item
      thread_patch → JSON Patch (RFC 6902) for any thread field
    """
    snapshot = "thread_snapshot"
    item_appended = "thread_item_appended"
    turn_completed = "turn_completed"
    turn_failed = "turn_failed"
    turn_interrupted = "turn_interrupted"
    status_changed = "thread_status_changed"
    title_changed = "thread_title_changed"
    thread_archived = "thread_archived"
    approval_requested = "approval_requested"
    approval_resolved = "approval_resolved"
    heartbeat = "thread_heartbeat"


# ─── Event models ───────────────────────────────────────────────────────────


@dataclass
class ThreadSnapshotItem:
    """A single item in a thread snapshot, designed for mobile consumption."""
    id: str
    turn_id: str
    turn_index: int
    kind: str  # ThreadItemKind value
    index: int
    role: str
    content: str
    created_at: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ThreadSnapshot:
    """Full thread state snapshot — the source of truth for a client.

    Emitted on connect/reconnect so the client can render the full
    thread without incremental replay.
    """
    kind: str = "thread_snapshot"
    thread_id: str = ""
    title: str = ""
    status: str = ""
    runtime_kind: str = ""
    turn_count: int = 0
    active_turn_id: str = ""
    active_turn_status: str = ""
    items: list[ThreadSnapshotItem] = field(default_factory=list)
    last_message_preview: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ThreadItemAppended:
    """A new item was appended to a running turn — streamed live."""
    kind: str = "item_appended"
    thread_id: str = ""
    turn_id: str = ""
    item: ThreadSnapshotItem | None = None
    turn_completed: bool = False
    turn_failed: bool = False
    error: str = ""


@dataclass
class ThreadStatusChanged:
    """Thread status changed (e.g. active → archived)."""
    kind: str = "thread_status_changed"
    thread_id: str = ""
    old_status: str = ""
    new_status: str = ""
    updated_at: str = ""


@dataclass
class ThreadTitleChanged:
    """Thread title was updated."""
    kind: str = "thread_title_changed"
    thread_id: str = ""
    title: str = ""
    updated_at: str = ""


@dataclass
class TurnCompleted:
    """A turn completed or failed."""
    kind: str = "turn_completed"
    thread_id: str = ""
    turn_id: str = ""
    turn_index: int = 0
    success: bool = True
    error: str = ""
    item_count: int = 0
    completed_at: str = ""


@dataclass
class TurnInterrupted:
    """A running turn was interrupted."""
    kind: str = "turn_interrupted"
    thread_id: str = ""
    turn_id: str = ""
    turn_index: int = 0
    interrupted_at: str = ""


@dataclass
class ApprovalRequested:
    """An action requires user approval."""
    kind: str = "approval_requested"
    thread_id: str = ""
    turn_id: str = ""
    approval_id: str = ""
    prompt: str = ""
    kind_label: str = ""


@dataclass
class ApprovalResolved:
    """An approval request was resolved."""
    kind: str = "approval_resolved"
    thread_id: str = ""
    approval_id: str = ""
    status: str = ""
    resolved_at: str = ""


# ─── Event protocol ─────────────────────────────────────────────────────────


# Union type for all V2 thread events
ThreadEvent = (
    ThreadSnapshot
    | ThreadItemAppended
    | ThreadStatusChanged
    | ThreadTitleChanged
    | TurnCompleted
    | TurnInterrupted
    | ApprovalRequested
    | ApprovalResolved
)


def _dataclass_to_dict_or_raw(obj: Any) -> Any:
    """Convert a dataclass to a dict, or return the object as-is."""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for f in obj.__dataclass_fields__:
            result[f] = _dataclass_to_dict_or_raw(getattr(obj, f))
        return result
    return obj


def event_to_dict(event: ThreadEvent) -> dict[str, Any]:
    """Serialize a V2 thread event to a dict for JSON transmission.

    Respects the kind field for downstream dispatch.
    """
    result: dict[str, Any] = {
        "type": event.kind,
    }
    for field_name in event.__dataclass_fields__:
        if field_name == "kind":
            continue
        value: Any = getattr(event, field_name)
        if isinstance(value, dict) and not value:
            continue
        if isinstance(value, list):
            if not value:
                continue
            # Convert dataclass items to dicts if needed
            result[field_name] = [
                _dataclass_to_dict_or_raw(item) for item in value
            ]
            continue
        if value is not None and value != "" and value != 0:
            result[field_name] = value
    return result
