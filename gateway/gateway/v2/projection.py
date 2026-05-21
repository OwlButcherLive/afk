"""Thread projection layer — builds mobile-friendly snapshots from V2 persistence.

The projection layer is the bridge between raw V2 persistence
(threads, turns, thread_items tables) and client-friendly views.

This module provides:
- ThreadProjection — builds a complete thread snapshot with hydrated items
- ThreadListItem — compact view for thread lists
- build_thread_projection() — full snapshot by thread ID
- build_thread_list() — compact list for a server session

Design:
- One source of truth for thread state (the V2 database)
- Separate raw runtime state from projected/mobile-friendly state
- No database writes — read-only query helpers
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from gateway.v2 import thread_store as ts
from gateway.v2.models import ThreadItemKind
from gateway.v2.events import ThreadSnapshot, ThreadSnapshotItem

logger = logging.getLogger("gateway.v2.projection")


@dataclass
class ThreadListItem:
    """Compact thread info for list views (session list, thread selector)."""
    id: str
    title: str
    status: str
    runtime_kind: str
    turn_count: int
    last_message_preview: str
    last_user_message: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_active: bool = True


@dataclass
class ThreadProjection:
    """Full thread projection — the canonical client-facing thread view.

    Contains all data needed to render a thread on any client:
    - thread metadata
    - fully hydrated items ordered by turn+index
    - active turn info
    - computed preview text
    """
    id: str
    title: str
    status: str
    runtime_kind: str
    turn_count: int
    active_turn_id: str = ""
    active_turn_status: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    last_message_preview: str = ""
    created_at: str = ""
    updated_at: str = ""


def _item_to_dict(item) -> dict[str, Any]:
    """Convert a ThreadItem to a serializable dict."""
    kind_val = item.kind.value if hasattr(item.kind, "value") else item.kind
    return {
        "id": item.id,
        "turn_id": item.turn_id,
        "kind": kind_val,
        "index": item.index,
        "role": item.role,
        "content": item.content,
        "metadata": item.metadata,
        "created_at": item.created_at,
    }


def _compute_preview(items: list) -> str:
    """Compute a preview string from the last user message in items."""
    for item in reversed(items):
        kind_val = item.kind.value if hasattr(item.kind, "value") else item.kind
        if kind_val == "user_message":
            content = item.content
            if len(content) > 80:
                return content[:80] + "..."
            return content
    return ""


async def build_thread_projection(
    thread_id: str,
    include_items: bool = True,
) -> ThreadProjection | None:
    """Build a full thread projection from V2 persistence.

    Args:
        thread_id: The V2 thread ID.
        include_items: If True, include all items in the projection.

    Returns:
        A ThreadProjection, or None if the thread doesn't exist.
    """
    thread = await ts.get_thread(thread_id)
    if thread is None:
        return None

    turns_list = await ts.list_turns(thread_id)
    items = await ts.list_thread_items(thread_id) if include_items else []

    # Find active turn
    active_turn = None
    for t in turns_list:
        status_val = t.status.value if hasattr(t.status, "value") else t.status
        if status_val in ("running", "pending"):
            active_turn = t
            break

    preview = _compute_preview(items)

    return ThreadProjection(
        id=thread.id,
        title=thread.title,
        status=thread.status.value if hasattr(thread.status, "value") else thread.status,
        runtime_kind=thread.runtime_kind.value if hasattr(thread.runtime_kind, "value") else thread.runtime_kind,
        turn_count=len(turns_list),
        active_turn_id=active_turn.id if active_turn else "",
        active_turn_status=active_turn.status.value if active_turn else "",
        items=[_item_to_dict(i) for i in items] if include_items else [],
        last_message_preview=preview,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )


async def build_thread_list(
    server_session_id: str,
    limit: int = 50,
) -> list[ThreadListItem]:
    """Build a compact thread list for a server session.

    Args:
        server_session_id: The V2 server session ID.
        limit: Max number of threads to return.

    Returns:
        List of ThreadListItem, sorted by updated_at DESC.
    """
    responses = await ts.list_threads(
        server_session_id=server_session_id,
        limit=limit,
    )
    results = []
    for r in responses:
        results.append(ThreadListItem(
            id=r.id,
            title=r.title,
            status=r.status.value if hasattr(r.status, "value") else r.status,
            runtime_kind=r.runtime_kind.value if hasattr(r.runtime_kind, "value") else r.runtime_kind,
            turn_count=r.turn_count,
            last_message_preview=r.last_message_preview,
            created_at=r.created_at,
            updated_at=r.updated_at,
            is_active=r.status in ("active",) if hasattr(r.status, "value") else True,
        ))
    return results


async def build_snapshot(thread_id: str) -> ThreadSnapshot | None:
    """Build a full ThreadSnapshot for event streaming.

    Used when emitting the initial thread state to a connected client,
    or when the client requests a full refresh.
    """
    projection = await build_thread_projection(thread_id, include_items=True)
    if projection is None:
        return None

    snapshot_items = []
    for item_dict in projection.items:
        snapshot_items.append(ThreadSnapshotItem(
            id=item_dict["id"],
            turn_id=item_dict["turn_id"],
            turn_index=0,  # Filled below
            kind=item_dict["kind"],
            index=item_dict["index"],
            role=item_dict["role"],
            content=item_dict["content"],
            created_at=item_dict["created_at"],
            metadata=item_dict.get("metadata", {}),
        ))

    # Fill turn_index for each item by loading turn info
    turns = await ts.list_turns(thread_id)
    turn_map = {t.id: t.turn_index for t in turns}
    for si in snapshot_items:
        si.turn_index = turn_map.get(si.turn_id, 0)

    return ThreadSnapshot(
        thread_id=projection.id,
        title=projection.title,
        status=projection.status,
        runtime_kind=projection.runtime_kind,
        turn_count=projection.turn_count,
        active_turn_id=projection.active_turn_id,
        active_turn_status=projection.active_turn_status,
        items=snapshot_items,
        last_message_preview=projection.last_message_preview,
        created_at=projection.created_at,
        updated_at=projection.updated_at,
    )


async def build_v1_history_payload(thread_id: str) -> list[dict]:
    """Build a V1-shaped history payload from V2 thread data.

    Returns list of dicts matching the V1 Message model shape.
    """
    projection = await build_thread_projection(thread_id, include_items=True)
    if projection is None:
        return []

    runtime_kind = projection.runtime_kind
    messages = []
    for item in projection.items:
        role = "user" if item.get("role") == "user" else "agent"
        messages.append({
            "id": item["id"],
            "agent_id": runtime_kind,
            "role": role,
            "text": item["content"],
            "timestamp": item.get("created_at", ""),
        })
    return messages


async def build_v1_session_list_payload(
    server_session_id: str,
    limit: int = 50,
) -> list[dict]:
    """Build a V1-shaped session list payload from V2 thread projections.

    Returns list of dicts matching the V1 Session model shape.
    """
    items = await build_thread_list(server_session_id, limit=limit)
    sessions = []
    for item in items:
        sessions.append({
            "id": item.id,
            "agent_id": item.runtime_kind,
            "title": item.title,
            "last_message_preview": item.last_message_preview,
            "updated_at": item.updated_at,
            "message_count": item.turn_count * 2,
            "is_active": item.is_active,
        })
    return sessions
