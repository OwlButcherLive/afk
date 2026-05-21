"""WebSocket chat handler for the Agent Gateway.

Handles /ws/chat connections:
- Receives user messages over WebSocket
- Persists them with session association
- Emits typing events
- Generates stub agent replies (default) or routes through Hermes CLI
- Persists replies and sends them back

V2 routing:
  For hermes-agent messages, execution now routes through the V2 compat bridge:
    1. compat.map_v1_message_to_thread() — creates V2 thread/turn/user_item
    2. compat.dispatch_v1_turn() — dispatches through WorkerPool → HermesRuntime
    3. compat.persist_runtime_items() — persists items to V2 thread_store
    4. compat.map_v1_ws_response() — produces V1-shaped WS response from V2 state

  Stub/default agents still use the legacy inline path for now.
  V1 database persistence is preserved for backward compatibility.
"""

import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("gateway.ws")

from gateway import database as db
from gateway.hermes_manager import HermesManager
from gateway.models import (
    AgentStatusEvent,
    ErrorEvent,
    IncomingMessage,
    IncomingMessageType,
    MessageRole,
    OutgoingMessage,
    TypingEvent,
    utc_now,
)

# HermesManager is set during lifespan in main.py
_hermes_manager: HermesManager | None = None


def set_hermes_manager(hm: HermesManager) -> None:
    global _hermes_manager
    _hermes_manager = hm


def _stub_reply(user_text: str) -> str:
    """Generate a simple deterministic stub reply.

    For V1 this is intentionally trivial — enough to validate the
    end-to-end transport path without a real agent runtime.
    """
    user_lower = user_text.strip().lower()

    if user_lower in ("hello", "hi", "hey", "bonjour", "salut"):
        return "Hello! I'm the AFK stub agent. How can I help you?"
    if user_lower in ("who are you", "what are you"):
        return "I'm the AFK Agent Gateway stub — a placeholder until real agent execution is wired in."
    if "?" in user_text:
        return (
            "That's a good question. For now I'm just a stub, "
            "but eventually I'll route your messages to an actual AI agent."
        )
    if user_lower in ("thanks", "merci", "thank you"):
        return "You're welcome!"

    # Default: echo with a prefix
    return f"You said: {user_text}"


async def _process_v2_compat(
    session_id: str,
    agent_id: str,
    text: str,
) -> dict:
    """Process a message through the V2 compat bridge (new execution path).

    For Hermes agents: routes through WorkerPool → HermesRuntime.
    For stub agents: creates V2 thread/turn/items, uses inline stub reply.

    Returns a dict with: ok, reply_text, error, v2_thread_id, v2_turn_id
    """
    from gateway.v2 import compat as v2_compat

    try:
        # Step 1: Map V1 message to V2 thread/turn/user item (always)
        v2_thread_id, v2_turn_id, user_item_id = await v2_compat.map_v1_message_to_thread(
            v1_session_id=session_id,
            v1_agent_id=agent_id,
            v1_text=text,
        )
        logger.info(
            "V2 compat: session=%s thread=%s turn=%s",
            session_id, v2_thread_id, v2_turn_id,
        )

        # Step 2: Generate reply (different path per agent type)
        if agent_id == "hermes-agent":
            # Hermes: dispatch through WorkerPool
            from gateway.main import get_worker_pool
            pool = get_worker_pool()
            dispatch_result = await v2_compat.dispatch_v1_turn(
                v2_thread_id=v2_thread_id,
                v2_turn_id=v2_turn_id,
                worker_pool=pool,
            )

            if not dispatch_result["ok"]:
                logger.error(
                    "V2 dispatch failed: thread=%s turn=%s error=%s",
                    v2_thread_id, v2_turn_id, dispatch_result["error"],
                )
                await v2_compat.persist_agent_reply(
                    v2_thread_id, v2_turn_id,
                    reply_text=f"⚠️ Agent error: {dispatch_result['error']}",
                    error=dispatch_result["error"],
                )
                ws_response = await v2_compat.map_v1_ws_response(
                    v2_thread_id, v2_turn_id,
                    reply_text=f"⚠️ Agent error: {dispatch_result['error']}",
                    error=dispatch_result["error"],
                )
                return {
                    "ok": False,
                    "reply_text": ws_response["text"],
                    "error": dispatch_result["error"],
                    "v2_thread_id": v2_thread_id,
                    "v2_turn_id": v2_turn_id,
                }

            reply_text = dispatch_result["reply_text"]
            await v2_compat.persist_agent_reply(
                v2_thread_id, v2_turn_id,
                reply_text=reply_text,
            )
        else:
            # Stub: use inline reply, persist to V2
            reply_text = _stub_reply(text)
            await v2_compat.persist_agent_reply(
                v2_thread_id, v2_turn_id,
                reply_text=reply_text,
            )

        # Step 3: Build V1-shaped WS response
        ws_response = await v2_compat.map_v1_ws_response(
            v2_thread_id, v2_turn_id,
            reply_text=reply_text,
        )

        logger.info(
            "V2 compat completed: agent=%s thread=%s turn=%s",
            agent_id, v2_thread_id, v2_turn_id,
        )

        return {
            "ok": True,
            "reply_text": ws_response["text"],
            "error": "",
            "v2_thread_id": v2_thread_id,
            "v2_turn_id": v2_turn_id,
        }

    except Exception as e:
        logger.error(
            "V2 compat processing failed: session=%s agent=%s error=%s",
            session_id, agent_id, e,
        )
        # Fallback: generate stub reply for non-Hermes
        if agent_id != "hermes-agent":
            return {
                "ok": False,
                "reply_text": _stub_reply(text),
                "error": str(e),
                "v2_thread_id": "",
                "v2_turn_id": "",
            }
        return {
            "ok": False,
            "reply_text": f"⚠️ V2 processing error: {e}",
            "error": str(e),
            "v2_thread_id": "",
            "v2_turn_id": "",
        }


async def handle_chat_ws(websocket: WebSocket) -> None:
    """Main WebSocket handler for /ws/chat."""
    await websocket.accept()
    logger.info("WebSocket connected: /ws/chat")

    try:
        # Send initial agent status
        await websocket.send_text(
            AgentStatusEvent(agent_id="default", status="online").model_dump_json()
        )

        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
                msg = IncomingMessage(**data)
            except (json.JSONDecodeError, ValueError) as exc:
                await websocket.send_text(
                    ErrorEvent(
                        code="invalid_message",
                        message=f"Cannot parse message: {exc}",
                    ).model_dump_json()
                )
                logger.warning(f"Invalid WS message: {exc}")
                continue

            if msg.type != IncomingMessageType.message:
                await websocket.send_text(
                    ErrorEvent(
                        code="unsupported_type",
                        message=f"Unsupported message type: {msg.type}",
                    ).model_dump_json()
                )
                continue

            # Validate session
            session = await db.get_session(msg.session_id)
            logger.info(
                "WS message: session=%s agent=%s text_len=%d — session_exists=%s",
                msg.session_id, msg.agent_id, len(msg.text), session is not None,
            )
            if session is None:
                await websocket.send_text(
                    ErrorEvent(
                        code="session_not_found",
                        message=f"Session '{msg.session_id}' not found",
                    ).model_dump_json()
                )
                logger.warning(f"Unknown session: {msg.session_id}")
                continue

            # Validate agent exists
            agent = await db.get_agent(msg.agent_id)
            if agent is None:
                await websocket.send_text(
                    ErrorEvent(
                        code="agent_not_found",
                        message=f"Agent '{msg.agent_id}' not found",
                    ).model_dump_json()
                )
                continue

            # ── Step 1: Persist user message (V1 backward compat) ──
            user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
            user_ts = utc_now()
            user_message = await db.save_message(
                message_id=user_msg_id,
                session_id=msg.session_id,
                agent_id=msg.agent_id,
                role=MessageRole.user,
                text=msg.text,
                timestamp=user_ts,
            )

            # Forward user message back to confirm receipt
            await websocket.send_text(
                OutgoingMessage(
                    type="message",
                    id=user_message.id,
                    agent_id=user_message.agent_id,
                    role=user_message.role,
                    text=user_message.text,
                    timestamp=user_message.timestamp,
                ).model_dump_json()
            )

            # ── Step 2: Emit typing indicator ──
            await websocket.send_text(
                TypingEvent(agent_id=msg.agent_id, is_typing=True).model_dump_json()
            )

            # ── Step 3: Generate reply ──
            # All messages route through V2 compat (creates thread/turn/items)
            v2_result = await _process_v2_compat(
                session_id=msg.session_id,
                agent_id=msg.agent_id,
                text=msg.text,
            )
            reply_text = v2_result["reply_text"]
            logger.info(
                "V2 compat response: ok=%s agent=%s session=%s reply_chars=%d",
                v2_result.get("ok", False), msg.agent_id, msg.session_id, len(reply_text),
            )

            # If V2 compat failed, fall back to legacy generation
            if not v2_result.get("ok") and msg.agent_id != "hermes-agent":
                logger.info(
                    "V2 compat unavailable for stub, using legacy: agent=%s",
                    msg.agent_id,
                )
                reply_text = _stub_reply(msg.text)

            # ── Step 4: Persist agent reply (V1 backward compat) ──
            reply_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
            reply_ts = utc_now()
            agent_message = await db.save_message(
                message_id=reply_msg_id,
                session_id=msg.session_id,
                agent_id=msg.agent_id,
                role=MessageRole.agent,
                text=reply_text,
                timestamp=reply_ts,
            )

            # ── Step 5: Stop typing, send reply ──
            await websocket.send_text(
                TypingEvent(agent_id=msg.agent_id, is_typing=False).model_dump_json()
            )

            await websocket.send_text(
                OutgoingMessage(
                    type="message",
                    id=agent_message.id,
                    agent_id=agent_message.agent_id,
                    role=agent_message.role,
                    text=agent_message.text,
                    timestamp=agent_message.timestamp,
                ).model_dump_json()
            )

            logger.info(
                f"Chat message processed: agent={msg.agent_id}, "
                f"session={msg.session_id}, "
                f"user_len={len(msg.text)}, reply_len={len(reply_text)}"
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: /ws/chat")
    except Exception as exc:
        logger.error(f"WebSocket error: {exc}")
        try:
            await websocket.send_text(
                ErrorEvent(code="internal_error", message=str(exc)).model_dump_json()
            )
        except Exception:
            pass
