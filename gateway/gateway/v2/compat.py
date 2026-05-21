"""Compatibility bridge — maps V1 chat endpoints to V2 internal model.

This module provides a transitional layer so the existing Android app
(which uses V1 REST/WS) can continue working while the gateway adopts
the V2 architecture internally.

Mapping:
  V1 "session" (agents, sessions, messages tables)
    -> V2 "thread" (threads, turns, thread_items tables)

  V1 POST /chat/sessions
    -> V2 thread_start()

  V1 GET /chat/history?session=X
    -> V2 thread_read(X)

  V1 WS /ws/chat message
    -> V2 thread_engine -> WorkerPool -> HermesRuntime -> V1 WS response

Since the V2 runtime upgrade (commit 0638de3+), the compat layer
routes Hermes execution through the V2 WorkerPool rather than
calling HermesManager directly. V1 stub agents still use the
existing stub path for now.
"""

import json
import logging
from typing import Any

from gateway.v2 import thread_store as ts
from gateway.v2.models import (
    RuntimeKind,
    ThreadItemKind,
    TurnStatus,
    utc_now,
    new_id,
)
from gateway.v2.thread_engine import (
    thread_read,
    thread_start,
    thread_set_name,
    turn_start,
    turn_complete,
    list_threads_for_session,
    ThreadOpResult,
)
from gateway.v2.session_store import create_server_session, heartbeat
from gateway.v2.worker import WorkerCommandKind

logger = logging.getLogger("gateway.v2.compat")


# ─── Session -> Thread mapping ──────────────────────────────────────────────


_V1_SESSION_DEFAULT = "default"  # V1 session id used by Android as default

# Maps V1 session IDs to V2 thread IDs
_session_to_thread: dict[str, str] = {}

# The default V2 server session for standalone gateway mode
_DEFAULT_SERVER_SESSION: str | None = None

# Runtime mode: set to "v2" to route Hermes through WorkerPool,
# "v1" to fall back to direct HermesManager. Controlled by ws_handler.
V2_RUNTIME_MODE: bool = True

# Global request tracker for V2 WebSocket operations
_v2_request_tracker = None


def get_v2_request_tracker():
    """Get or create the global V2 request tracker."""
    global _v2_request_tracker
    if _v2_request_tracker is None:
        from gateway.v2.requests import RequestTracker
        _v2_request_tracker = RequestTracker()
    return _v2_request_tracker


def add_v1_mapping(v1_session_id: str, v2_thread_id: str) -> None:
    """Register a V1 session ID → V2 thread ID mapping."""
    _session_to_thread[v1_session_id] = v2_thread_id
    logger.debug("V1 mapping added: %s -> %s", v1_session_id, v2_thread_id)


def get_v2_thread_for_v1_session(v1_session_id: str) -> str | None:
    """Get the V2 thread ID for a V1 session, or None."""
    return _session_to_thread.get(v1_session_id)


async def ensure_default_server_session() -> str:
    """Get or create the default V2 server session.

    In standalone mode (no Android SSH session), all V1 traffic
    maps to this single server session.
    """
    global _DEFAULT_SERVER_SESSION
    if _DEFAULT_SERVER_SESSION is None:
        sess = await create_server_session(name="default-v1-compat", client_platform="v1-compat")
        _DEFAULT_SERVER_SESSION = sess.id
        logger.info("Created default V2 server session: %s", sess.id)
    return _DEFAULT_SERVER_SESSION


def clear_mappings() -> None:
    """Clear all V1→V2 mappings. Used in tests and on reset."""
    _session_to_thread.clear()


async def get_or_create_v2_thread_for_v1_session(
    v1_session_id: str,
    agent_id: str = "default",
) -> str:
    """Get an existing V2 thread for a V1 session, or create one eagerly.

    This ensures every V1 session has a corresponding V2 thread from
    creation time, so V1 REST reads can be fully backed by V2 data.
    """
    existing = _session_to_thread.get(v1_session_id)
    if existing is not None:
        return existing

    server_sess_id = await ensure_default_server_session()
    runtime = RuntimeKind.hermes if agent_id == "hermes-agent" else RuntimeKind.stub
    result = await thread_start(
        server_session_id=server_sess_id,
        runtime_kind=runtime.value,
        title=f"V1 session {v1_session_id[:8]}",
    )
    if not result.ok or result.thread is None:
        logger.error("Failed to create V2 thread for V1 session %s: %s",
                      v1_session_id, result.error)
        # Return empty string so callers can handle gracefully
        return ""
    v2_thread_id = result.thread.id
    _session_to_thread[v1_session_id] = v2_thread_id
    logger.info("Eagerly mapped V1 session=%s -> V2 thread=%s", v1_session_id, v2_thread_id)
    return v2_thread_id


# ─── Compatibility operations ───────────────────────────────────────────────


async def map_v1_message_to_thread(
    v1_session_id: str,
    v1_agent_id: str,
    v1_text: str,
) -> tuple[str, str, str]:
    """Process a V1 WS message and route it through V2 internals.

    Creates/retrieves the V2 thread, starts a new turn, and persists
    the user message as a ThreadItem.

    Args:
        v1_session_id: The V1 session ID from the WS message.
        v1_agent_id: The V1 agent ID.
        v1_text: The message text.

    Returns:
        Tuple of (v2_thread_id, v2_turn_id, v2_user_item_id) for
        the caller to reference when persisting the agent reply.
    """
    server_sess_id = await ensure_default_server_session()

    # Map V1 session to V2 thread
    v2_thread_id = _session_to_thread.get(v1_session_id)
    if v2_thread_id is None:
        # First message for this V1 session — create a V2 thread
        runtime = RuntimeKind.hermes if v1_agent_id == "hermes-agent" else RuntimeKind.stub
        result = await thread_start(
            server_session_id=server_sess_id,
            runtime_kind=runtime.value,
            title=v1_text[:80],
        )
        if not result.ok or result.thread is None:
            logger.error("Failed to create V2 thread for V1 session %s: %s",
                          v1_session_id, result.error)
            raise RuntimeError(f"Failed to create thread: {result.error}")
        v2_thread_id = result.thread.id
        _session_to_thread[v1_session_id] = v2_thread_id
        logger.info("Mapped V1 session=%s -> V2 thread=%s", v1_session_id, v2_thread_id)

    # Start a new turn
    turn_result = await turn_start(v2_thread_id)
    if not turn_result.ok or turn_result.turn is None:
        raise RuntimeError(f"Failed to start turn: {turn_result.error}")

    v2_turn_id = turn_result.turn.id

    # Persist the user message as a thread item
    user_item = await ts.create_thread_item(
        thread_id=v2_thread_id,
        turn_id=v2_turn_id,
        kind=ThreadItemKind.user_message.value,
        index=0,
        role="user",
        content=v1_text,
        metadata={"source": "v1_ws", "v1_session_id": v1_session_id},
    )

    # Update thread title from first user message
    if turn_result.turn.turn_index == 0:
        await thread_set_name(v2_thread_id, v1_text[:80])

    # Set the user_message_id on the turn
    from gateway.v2.thread_store import set_turn_message_refs
    await set_turn_message_refs(v2_turn_id, user_item.id, "")

    return v2_thread_id, v2_turn_id, user_item.id


async def dispatch_v1_turn(
    v2_thread_id: str,
    v2_turn_id: str,
    worker_pool,
) -> dict[str, Any]:
    """Dispatch a V2 turn through the WorkerPool for Hermes execution.

    This is the key integration point between V1 and V2:
    - The WorkerPool owns a RuntimeWorker wrapping HermesRuntime
    - The turn is sent as a WorkerCommand
    - The result contains structured RuntimeEvent with ThreadItems

    Args:
        v2_thread_id: The V2 thread ID.
        v2_turn_id: The V2 turn ID.
        worker_pool: The WorkerPool instance from main.py.

    Returns:
        Dict with:
          ok: bool
          reply_text: str (the agent's response, or error message)
          error: str (if failed)
          item_count: int (number of items produced)
          duration_ms: int
    """
    worker = worker_pool.get("hermes")
    if worker is None:
        logger.error("No hermes worker registered in pool — cannot dispatch turn")
        return {"ok": False, "reply_text": "", "error": "No hermes worker available", "item_count": 0, "duration_ms": 0}

    # Load turn and prior items
    turn = await ts.get_turn(v2_turn_id)
    if turn is None:
        return {"ok": False, "reply_text": "", "error": f"Turn '{v2_turn_id}' not found", "item_count": 0, "duration_ms": 0}

    prior_items = await ts.list_thread_items(v2_thread_id)

    # Dispatch through worker command channel
    from gateway.v2.worker import WorkerCommandKind
    result = await worker.send_command(
        WorkerCommandKind.process_turn,
        payload={
            "turn": turn.model_dump() if hasattr(turn, "model_dump") else _dataclass_to_dict(turn),
            "prior_items": [
                i.model_dump() if hasattr(i, "model_dump") else _dataclass_to_dict(i)
                for i in prior_items
            ],
        },
        timeout=120.0,
    )

    if not result.ok:
        logger.error("Worker dispatch failed: %s", result.error)
        return {"ok": False, "reply_text": "", "error": result.error, "item_count": 0, "duration_ms": 0}

    event = result.value
    if not hasattr(event, "kind"):
        logger.error("Worker returned unexpected result type: %s", type(event))
        return {"ok": False, "reply_text": "", "error": "Unexpected worker result", "item_count": 0, "duration_ms": 0}

    # Extract reply text from agent_message items
    reply_text = ""
    item_count = 0
    if hasattr(event, "items"):
        item_count = len(event.items)
        for item in event.items:
            kind_val = item.kind.value if hasattr(item.kind, "value") else item.kind
            if kind_val == "agent_message":
                reply_text = item.content
                break
        if not reply_text:
            # Fall back: use any non-user content
            for item in event.items:
                kind_val = item.kind.value if hasattr(item.kind, "value") else item.kind
                if kind_val != "user_message":
                    reply_text = item.content
                    break

    duration_ms = 0
    if hasattr(event, "metadata") and event.metadata:
        duration_ms = event.metadata.get("duration_ms", 0) or 0

    ok = event.ok if hasattr(event, "ok") else (event.kind == "turn_completed")
    error = event.error if hasattr(event, "error") else ""

    return {
        "ok": ok,
        "reply_text": reply_text or "⚠️ Agent returned empty response.",
        "error": error,
        "item_count": item_count,
        "duration_ms": duration_ms,
    }


def _dataclass_to_dict(obj: Any) -> dict:
    """Convert a dataclass/Pydantic model to a dict."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dataclass_fields__"):
        return {f: getattr(obj, f) for f in obj.__dataclass_fields__ if not f.startswith("_")}
    return dict(obj)


async def persist_runtime_items(
    v2_thread_id: str,
    v2_turn_id: str,
    items: list,
    error: str | None = None,
) -> None:
    """Persist items from a RuntimeEvent as V2 thread items, then complete the turn.

    This is the V2-native path: items are ThreadItem objects produced
    by HermesRuntime.process_turn(). They are persisted directly
    without the compat layer having to reconstruct them.

    Args:
        v2_thread_id: The V2 thread ID.
        v2_turn_id: The V2 turn ID.
        items: List of ThreadItem objects from the RuntimeEvent.
        error: Optional error string for turn completion.
    """
    if not items:
        logger.warning("persist_runtime_items: no items to persist for turn=%s", v2_turn_id)
        await turn_complete(v2_turn_id, error=error or "empty_runtime_items")
        return

    # Persist each item
    user_item_id = ""
    agent_item_id = ""
    for item in items:
        kind_val = item.kind.value if hasattr(item.kind, "value") else item.kind
        role = item.role
        content = item.content
        meta = item.metadata if hasattr(item, "metadata") else {}

        persisted = await ts.create_thread_item(
            thread_id=v2_thread_id,
            turn_id=v2_turn_id,
            kind=kind_val,
            index=item.index if hasattr(item, "index") else 0,
            role=role,
            content=content,
            metadata=meta,
        )

        if kind_val == "user_message":
            user_item_id = persisted.id
        elif kind_val in ("agent_message", "system_event"):
            if not agent_item_id:
                agent_item_id = persisted.id

    # Set message refs on the turn
    from gateway.v2.thread_store import set_turn_message_refs
    await set_turn_message_refs(v2_turn_id, user_item_id, agent_item_id)

    # Complete the turn
    await turn_complete(v2_turn_id, error=error)


async def persist_agent_reply(
    v2_thread_id: str,
    v2_turn_id: str,
    reply_text: str,
    error: str | None = None,
) -> None:
    """Persist the agent's reply as a V2 thread item and complete the turn.

    Legacy path: used when the reply is a bare text string (stub agents,
    fallback). The V2-native path uses persist_runtime_items().

    Args:
        v2_thread_id: The V2 thread ID.
        v2_turn_id: The V2 turn ID.
        reply_text: The agent's response text.
        error: Optional error string if the reply is a failure.
    """
    kind = ThreadItemKind.system_event if error else ThreadItemKind.agent_message
    role = "system" if error else "agent"

    agent_item = await ts.create_thread_item(
        thread_id=v2_thread_id,
        turn_id=v2_turn_id,
        kind=kind.value,
        index=1,
        role=role,
        content=reply_text,
        metadata={"source": "v1_compat_legacy"},
    )

    # Set agent_message_id on turn
    from gateway.v2.thread_store import set_turn_message_refs
    turn_obj = await ts.get_turn(v2_turn_id)
    if turn_obj:
        await set_turn_message_refs(
            v2_turn_id,
            turn_obj.user_message_id or "",
            agent_item.id,
        )

    # Complete the turn
    await turn_complete(v2_turn_id, error=error)


# ─── V1 endpoint helpers (fully V2-backed) ──────────────────────────────────


async def get_v1_session_list(
    v1_db_sessions: list | None = None,
) -> list[dict]:
    """Produce V1-style session list from V2 threads.

    Args:
        v1_db_sessions: Optional list of V1 DB Session objects for sessions
            that haven't had a WS message yet (no V2 thread mapping).
            When provided, they are merged into the result.

    Returns:
        List of V1-shaped session dicts.
    """
    server_id = await ensure_default_server_session()
    threads = await list_threads_for_session(server_id, limit=50)

    sessions = []
    seen_v1_ids: set[str] = set()

    for t in threads:
        # Find the V1 session ID that maps to this thread
        v1_sid = None
        for vsid, vtid in _session_to_thread.items():
            if vtid == t.id:
                v1_sid = vsid
                break
        if v1_sid is None:
            v1_sid = f"v1_compat_{t.id}"

        seen_v1_ids.add(v1_sid)

        status_val = t.status.value if hasattr(t.status, 'value') else t.status
        is_active = status_val in ("active",)

        sessions.append({
            "id": v1_sid,
            "agent_id": t.runtime_kind,
            "title": t.title,
            "last_message_preview": t.last_message_preview,
            "updated_at": t.updated_at,
            "message_count": t.turn_count * 2,
            "is_active": is_active,
        })

    # Merge V1 DB sessions that don't have V2 threads yet
    if v1_db_sessions:
        for s in v1_db_sessions:
            sid = s.id if hasattr(s, "id") else s.get("id")
            if sid not in seen_v1_ids:
                title = s.title if hasattr(s, "title") else s.get("title", "")
                updated = s.updated_at if hasattr(s, "updated_at") else s.get("updated_at", "")
                agent_id = s.agent_id if hasattr(s, "agent_id") else s.get("agent_id", "default")
                sessions.append({
                    "id": sid,
                    "agent_id": agent_id,
                    "title": title,
                    "last_message_preview": "",
                    "updated_at": updated,
                    "message_count": 0,
                    "is_active": True,
                })

    # Sort by updated_at descending
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions


async def get_v1_history(
    v1_session_id: str,
) -> list[dict]:
    """Produce V1-style history from V2 thread items.

    Returns V1-shaped message list from V2 persistence.
    Empty list if the session has no V2 mapping.
    """
    v2_thread_id = _session_to_thread.get(v1_session_id)
    if v2_thread_id is None:
        return []

    result = await thread_read(v2_thread_id, include_items=True)
    if not result.ok or result.thread is None:
        return []

    all_items = await ts.list_thread_items(v2_thread_id)
    runtime_kind_val = result.thread.runtime_kind
    messages = []
    for item in all_items:
        kind_val = item.kind.value if hasattr(item.kind, 'value') else item.kind
        role = "user" if item.role == "user" else "agent"
        messages.append({
            "id": item.id,
            "agent_id": runtime_kind_val,
            "role": role,
            "text": item.content,
            "timestamp": item.created_at,
        })
    return messages


async def map_v1_ws_response(
    v2_thread_id: str,
    v2_turn_id: str,
    reply_text: str,
    error: str | None = None,
) -> dict:
    """Produce a V1-shaped WebSocket response from V2 thread state.

    Returns a dict ready to be sent as JSON over the V1 WS connection.
    The format matches what the existing Android app expects:
    {type, id, agent_id, role, text, timestamp}

    Args:
        v2_thread_id: The V2 thread ID.
        v2_turn_id: The V2 turn ID.
        reply_text: The agent's response text.
        error: Optional error string.

    Returns:
        A V1-shaped WS event dict.
    """
    # Get thread for runtime_kind
    projection = None
    try:
        from gateway.v2.projection import build_thread_projection
        projection = await build_thread_projection(v2_thread_id, include_items=False)
    except Exception as e:
        logger.debug("Could not build projection for WS response: %s", e)

    runtime_kind = projection.runtime_kind if projection else "hermes"
    agent_id = "hermes-agent" if runtime_kind == "hermes" else runtime_kind

    return {
        "type": "message",
        "id": f"v2_agent_{v2_turn_id[:8]}" if not error else f"v2_error_{v2_turn_id[:8]}",
        "agent_id": agent_id,
        "role": "agent",
        "text": reply_text,
        "timestamp": utc_now(),
    }
