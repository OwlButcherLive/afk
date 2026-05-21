"""WebSocket chat handler for the Agent Gateway.

Handles /ws/chat connections:
- Receives user messages over WebSocket
- Persists them with session association
- Emits typing events
- Generates stub agent replies
- Persists replies and sends them back
"""

import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("gateway.ws")

from gateway import database as db
from gateway.droid_manager import DroidManager
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

# DroidManager is set during lifespan in main.py
_droid_manager: DroidManager | None = None


def set_droid_manager(dm: DroidManager) -> None:
    global _droid_manager
    _droid_manager = dm


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

            # ── Step 1: Persist user message ──
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
            if msg.agent_id == "factory-droid" and _droid_manager is not None:
                # Route through real Factory Droid
                droid_result = await _droid_manager.send_task(msg.text, timeout=120.0)
                if droid_result.success:
                    reply_text = droid_result.text
                else:
                    reply_text = f"⚠️ Droid error: {droid_result.error}"
                logger.info(
                    f"Droid replied in {droid_result.duration_ms}ms "
                    f"(success={droid_result.success})"
                )
            else:
                # Standard stub reply for non-droid agents
                reply_text = _stub_reply(msg.text)

            # ── Step 4: Persist agent reply ──
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
