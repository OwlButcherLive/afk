"""V2 WebSocket handler — native thread event streaming endpoint.

Endpoint: /ws/v2/thread

Protocol:
  Client sends JSON messages with:
    type: string — command type
    thread_id: string — V2 thread ID (required for thread commands)
    request_id: string — correlation ID for request/response

  Commands:
    hello              — initialize session, get protocol version + runtimes
    subscribe          — subscribe to thread events
    unsubscribe        — stop receiving events for a thread
    start_turn         — start a new turn and dispatch to runtime
    interrupt_turn     — interrupt a running turn
    request_snapshot   — receive a full thread snapshot
    heartbeat          — keepalive

  Server sends JSON events with:
    type: string — event type
    request_id: string — echoed back from client request
    ... event-specific fields

  Event types:
    hello_response     — response to hello (protocol info, runtimes, session)
    thread_snapshot    — full thread state
    turn_started       — turn was created and dispatched
    item_appended      — new ThreadItem produced during execution
    turn_completed     — turn finished successfully
    turn_failed        — turn failed
    error              — error response
    ack                — acknowledge command receipt
    pong               — heartbeat response
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from gateway.v2 import thread_store as ts
from gateway.v2 import compat as v2_compat
from gateway.v2.projection import build_snapshot, build_thread_projection
from gateway.v2.thread_engine import (
    thread_start,
    turn_start,
    turn_complete,
    turn_interrupt,
    thread_read,
)
from gateway.v2.events import (
    event_to_dict,
    ThreadItemAppended,
    ThreadSnapshot,
    ThreadSnapshotItem,
    TurnCompleted,
)

logger = logging.getLogger("gateway.v2.ws")

# Track which clients are subscribed to which threads
_subscribed_clients: dict[str, set[WebSocket]] = {}  # thread_id -> set of WS


def _add_subscription(thread_id: str, ws: WebSocket) -> None:
    if thread_id not in _subscribed_clients:
        _subscribed_clients[thread_id] = set()
    _subscribed_clients[thread_id].add(ws)


def _remove_subscription(thread_id: str, ws: WebSocket) -> None:
    clients = _subscribed_clients.get(thread_id)
    if clients:
        clients.discard(ws)
        if not clients:
            del _subscribed_clients[thread_id]


def _remove_client_all_subscriptions(ws: WebSocket) -> None:
    """Remove a client from all subscriptions (on disconnect)."""
    for thread_id in list(_subscribed_clients.keys()):
        _remove_subscription(thread_id, ws)


async def _broadcast_to_thread(thread_id: str, event: dict, exclude: WebSocket | None = None) -> None:
    """Broadcast an event to all subscribers of a thread."""
    clients = _subscribed_clients.get(thread_id, set())
    dead: list[WebSocket] = []
    for ws in clients:
        if exclude and ws == exclude:
            continue
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _remove_subscription(thread_id, ws)


async def _send_event(ws: WebSocket, event: dict | str) -> None:
    """Send a JSON event to a specific WebSocket."""
    if isinstance(event, str):
        await ws.send_text(event)
    else:
        await ws.send_text(json.dumps(event))


def _ack(request_id: str, status: str = "ok", **kwargs) -> dict:
    """Build an acknowledgment response."""
    return {"type": "ack", "request_id": request_id, "status": status, **kwargs}


def _error(request_id: str, message: str, code: str = "error") -> dict:
    """Build an error response."""
    return {"type": "error", "request_id": request_id, "code": code, "message": message}


async def _handle_subscribe(ws: WebSocket, msg: dict) -> dict | None:
    """Handle subscribe command."""
    thread_id = msg.get("thread_id", "")
    request_id = msg.get("request_id", "")

    if not thread_id:
        return _error(request_id, "thread_id is required")

    # Verify thread exists
    projection = await build_thread_projection(thread_id, include_items=False)
    if projection is None:
        return _error(request_id, f"Thread '{thread_id}' not found", code="not_found")

    _add_subscription(thread_id, ws)

    # Send full snapshot on subscribe
    snapshot = await build_snapshot(thread_id)
    if snapshot:
        await _send_event(ws, event_to_dict(snapshot))

    return _ack(request_id, "subscribed", thread_id=thread_id)


async def _handle_unsubscribe(ws: WebSocket, msg: dict) -> dict | None:
    """Handle unsubscribe command."""
    thread_id = msg.get("thread_id", "")
    request_id = msg.get("request_id", "")
    _remove_subscription(thread_id, ws)
    return _ack(request_id, "unsubscribed", thread_id=thread_id)


async def _handle_start_turn(ws: WebSocket, msg: dict) -> dict | None:
    """Handle start_turn command — creates a turn and dispatches to runtime."""
    thread_id = msg.get("thread_id", "")
    text = msg.get("text", "")
    request_id = msg.get("request_id", "")

    if not thread_id or not text:
        return _error(request_id, "thread_id and text are required")

    # Verify thread exists
    projection = await build_thread_projection(thread_id, include_items=False)
    if projection is None:
        return _error(request_id, f"Thread '{thread_id}' not found", code="not_found")

    # Track this request
    tracker = v2_compat.get_v2_request_tracker()
    tracker.create_request(
        kind="process_turn",
        thread_id=thread_id,
        request_id=request_id,
        metadata={"text_len": len(text)},
    )

    # Start a turn
    turn_result = await turn_start(thread_id)
    if not turn_result.ok or turn_result.turn is None:
        tracker.fail_request(request_id, error=turn_result.error)
        return _error(request_id, f"Failed to start turn: {turn_result.error}")

    v2_turn_id = turn_result.turn.id

    # Persist user message
    from gateway.v2.models import utc_now as v2_utc_now

    user_item = await ts.create_thread_item(
        thread_id=thread_id,
        turn_id=v2_turn_id,
        kind="user_message",
        index=0,
        role="user",
        content=text,
        metadata={"source": "v2_ws", "request_id": request_id},
    )

    from gateway.v2.thread_store import set_turn_message_refs
    await set_turn_message_refs(v2_turn_id, user_item.id, "")

    # Send turn_started event
    await _send_event(ws, {
        "type": "turn_started",
        "request_id": request_id,
        "thread_id": thread_id,
        "turn_id": v2_turn_id,
    })

    # Broadcast user message to other subscribers
    user_snapshot_item = ThreadSnapshotItem(
        id=user_item.id,
        turn_id=v2_turn_id,
        turn_index=turn_result.turn.turn_index,
        kind="user_message",
        index=0,
        role="user",
        content=text,
        created_at=v2_utc_now(),
    )
    appended_evt = event_to_dict(ThreadItemAppended(
        thread_id=thread_id,
        turn_id=v2_turn_id,
        item=user_snapshot_item,
    ))
    await _broadcast_to_thread(thread_id, appended_evt, exclude=ws)

    # Dispatch through WorkerPool
    from gateway.main import get_worker_pool
    pool = get_worker_pool()
    dispatch_result = await v2_compat.dispatch_v1_turn(
        v2_thread_id=thread_id,
        v2_turn_id=v2_turn_id,
        worker_pool=pool,
    )

    if dispatch_result["ok"]:
        # Persist the reply
        await v2_compat.persist_agent_reply(
            thread_id, v2_turn_id,
            reply_text=dispatch_result["reply_text"],
        )

        # Send turn_completed
        await _send_event(ws, {
            "type": "turn_completed",
            "request_id": request_id,
            "thread_id": thread_id,
            "turn_id": v2_turn_id,
            "reply_text": dispatch_result["reply_text"],
            "duration_ms": dispatch_result.get("duration_ms", 0),
        })

        # Broadcast to other subscribers
        agent_snapshot_item = ThreadSnapshotItem(
            id=f"agent_{v2_turn_id[:8]}",
            turn_id=v2_turn_id,
            turn_index=turn_result.turn.turn_index,
            kind="agent_message",
            index=1,
            role="agent",
            content=dispatch_result["reply_text"],
            created_at=v2_utc_now(),
        )
        completed_evt = event_to_dict(TurnCompleted(
            thread_id=thread_id,
            turn_id=v2_turn_id,
            turn_index=turn_result.turn.turn_index,
            success=True,
            item_count=2,
        ))
        await _broadcast_to_thread(thread_id, completed_evt, exclude=ws)

        tracker.resolve_request(request_id, metadata={
            "turn_id": v2_turn_id,
            "duration_ms": dispatch_result.get("duration_ms", 0),
        })

        return None
    else:
        # Persist error
        await v2_compat.persist_agent_reply(
            thread_id, v2_turn_id,
            reply_text=f"⚠️ Agent error: {dispatch_result['error']}",
            error=dispatch_result["error"],
        )

        await _send_event(ws, {
            "type": "turn_failed",
            "request_id": request_id,
            "thread_id": thread_id,
            "turn_id": v2_turn_id,
            "error": dispatch_result["error"],
        })

        tracker.fail_request(request_id, error=dispatch_result["error"])
        return None


async def _handle_interrupt_turn(ws: WebSocket, msg: dict) -> dict | None:
    """Handle interrupt_turn command."""
    turn_id = msg.get("turn_id", "")
    request_id = msg.get("request_id", "")

    if not turn_id:
        return _error(request_id, "turn_id is required")

    result = await turn_interrupt(turn_id)
    if result.ok:
        await _broadcast_to_thread(result.turn.thread_id if result.turn else "", {
            "type": "turn_interrupted",
            "turn_id": turn_id,
            "thread_id": result.turn.thread_id if result.turn else "",
        })
        return _ack(request_id, "interrupted", turn_id=turn_id)
    else:
        return _error(request_id, result.error, code="interrupt_failed")


async def _handle_request_snapshot(ws: WebSocket, msg: dict) -> dict | None:
    """Handle request_snapshot command."""
    thread_id = msg.get("thread_id", "")
    request_id = msg.get("request_id", "")

    if not thread_id:
        return _error(request_id, "thread_id is required")

    snapshot = await build_snapshot(thread_id)
    if snapshot is None:
        return _error(request_id, f"Thread '{thread_id}' not found", code="not_found")

    await _send_event(ws, event_to_dict(snapshot))
    return _ack(request_id, "snapshot_sent", thread_id=thread_id)


async def _handle_hello(ws: WebSocket, msg: dict) -> dict | None:
    """Handle hello command — initialize session and return protocol info."""
    request_id = msg.get("request_id", "")

    server_id = await v2_compat.ensure_default_server_session()

    # Available runtimes
    runtimes = []
    try:
        from gateway.main import get_worker_pool
        pool = get_worker_pool()
        workers = pool.list_workers()
        for w in workers:
            runtimes.append({"kind": w["kind"], "status": w["status"]})
    except Exception:
        runtimes.append({"kind": "unknown", "status": "unavailable"})

    await _send_event(ws, {
        "type": "hello_response",
        "request_id": request_id,
        "protocol_version": "2.0.0",
        "server_session_id": server_id,
        "runtimes": runtimes,
        "endpoints": {
            "ws_v2_thread": "/ws/v2/thread",
            "rest_v2_threads": "/api/v2/threads",
        },
    })
    return None


_HANDLERS = {
    "hello": _handle_hello,
    "subscribe": _handle_subscribe,
    "unsubscribe": _handle_unsubscribe,
    "start_turn": _handle_start_turn,
    "interrupt_turn": _handle_interrupt_turn,
    "request_snapshot": _handle_request_snapshot,
}


async def handle_v2_thread_ws(websocket: WebSocket) -> None:
    """V2 WebSocket handler for /ws/v2/thread."""
    await websocket.accept()
    logger.info("V2 WebSocket connected: /ws/v2/thread")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                await _send_event(websocket,
                    _error("", f"Invalid JSON: {exc}", code="invalid_json"))
                continue

            msg_type = msg.get("type", "")
            request_id = msg.get("request_id", "")

            if msg_type == "heartbeat":
                await _send_event(websocket, {
                    "type": "pong",
                    "request_id": request_id,
                })
                continue

            handler = _HANDLERS.get(msg_type)
            if handler is None:
                await _send_event(websocket,
                    _error(request_id, f"Unknown command: {msg_type}", code="unknown_command"))
                continue

            try:
                response = await handler(websocket, msg)
                if response:
                    await _send_event(websocket, response)
            except Exception as exc:
                logger.error("V2 WS handler error: type=%s error=%s", msg_type, exc)
                await _send_event(websocket,
                    _error(request_id, f"Internal error: {exc}", code="internal_error"))

    except WebSocketDisconnect:
        logger.info("V2 WebSocket disconnected: /ws/v2/thread")
    except Exception as exc:
        logger.error(f"V2 WebSocket error: {exc}")
    finally:
        # Clean up subscriptions and pending requests
        _remove_client_all_subscriptions(websocket)
        tracker = v2_compat.get_v2_request_tracker()
        pending = tracker.list_pending()
        for req in pending:
            tracker.cancel_request(req.id, reason="v2_ws_disconnect")
