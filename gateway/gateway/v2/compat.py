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
    -> V2 turn_start() + thread_store.add_item() + runtime.process_turn()
"""

import json
import logging

from gateway.v2 import thread_store as ts
from gateway.v2.models import (
    RuntimeKind,
    ThreadItemKind,
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
)
from gateway.v2.session_store import create_server_session, heartbeat

logger = logging.getLogger("gateway.v2.compat")


# ─── Session -> Thread mapping ──────────────────────────────────────────────


_V1_SESSION_DEFAULT = "default"  # V1 session id used by Android as default

# Maps V1 session IDs to V2 thread IDs
_session_to_thread: dict[str, str] = {}

# The default V2 server session for standalone gateway mode
_DEFAULT_SERVER_SESSION: str | None = None


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


# ─── Compatibility operations ───────────────────────────────────────────────


async def map_v1_message_to_thread(
    v1_session_id: str,
    v1_agent_id: str,
    v1_text: str,
) -> tuple[str, str, str]:
    """Process a V1 WS message and route it through V2 internals.

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
    )

    # Update thread title from first user message
    if turn_result.turn.turn_index == 0:
        await thread_set_name(v2_thread_id, v1_text[:80])

    # Set the user_message_id on the turn
    from gateway.v2.thread_store import set_turn_message_refs
    await set_turn_message_refs(v2_turn_id, user_item.id, "")

    return v2_thread_id, v2_turn_id, user_item.id


async def persist_agent_reply(
    v2_thread_id: str,
    v2_turn_id: str,
    reply_text: str,
    error: str | None = None,
) -> None:
    """Persist the agent's reply as a V2 thread item and complete the turn.

    Args:
        v2_thread_id: The V2 thread ID.
        v2_turn_id: The V2 turn ID.
        reply_text: The agent's response text.
        error: Optional error string if the reply is a failure.
    """
    # Persist as thread item
    agent_item = await ts.create_thread_item(
        thread_id=v2_thread_id,
        turn_id=v2_turn_id,
        kind=ThreadItemKind.agent_message.value,
        index=1,
        role="agent",
        content=reply_text,
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


# ─── V1 endpoint helpers ────────────────────────────────────────────────────


async def get_v1_session_list() -> list[dict]:
    """Produce V1-style session list from V2 threads."""
    server_id = await ensure_default_server_session()
    threads = await list_threads_for_session(server_id, limit=50)

    # Build reverse mapping: thread_id -> v1_session_id
    rev_map = {v: k for k, v in _session_to_thread.items()}

    sessions = []
    for t in threads:
        # Find the V1 session ID that maps to this thread
        v1_sid = None
        for vsid, vtid in _session_to_thread.items():
            if vtid == t.id:
                v1_sid = vsid
                break
        if v1_sid is None:
            v1_sid = f"v1_compat_{t.id}"

        sessions.append({
            "id": v1_sid,
            "agent_id": t.runtime_kind,
            "title": t.title,
            "last_message_preview": t.last_message_preview,
            "updated_at": t.updated_at,
            "message_count": t.turn_count * 2,  # approximate
        })
    return sessions


async def get_v1_history(v1_session_id: str) -> list[dict]:
    """Produce V1-style history from V2 thread items."""
    v2_thread_id = _session_to_thread.get(v1_session_id)
    if v2_thread_id is None:
        return []

    result = await thread_read(v2_thread_id, include_items=True)
    if not result.ok or result.thread is None:
        return []

    all_items = await ts.list_thread_items(v2_thread_id)
    messages = []
    for item in all_items:
        role = "user" if item.role == "user" else "agent"
        messages.append({
            "id": item.id,
            "agent_id": result.thread.runtime_kind,
            "role": role,
            "text": item.content,
            "timestamp": item.created_at,
        })
    return messages
