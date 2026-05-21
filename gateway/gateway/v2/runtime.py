"""AFK V2 runtime abstractions.

Defines AgentRuntime as an abstract interface for agent execution backends.
HermesRuntime is the V2-conformant wrapper around the existing HermesManager.

Design:
- AgentRuntime is a trait (ABC) that all runtimes implement
- Runtimes are owned by ServerSessionRuntime
- Each thread is routed to one runtime via ThreadRuntimeRoute
- The runtime receives a fully reconstructed Turn context (not bare messages)
- process_turn() returns RuntimeEvent with structured ThreadItem objects
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from gateway.v2.models import ThreadItem, Turn

logger = logging.getLogger("gateway.v2.runtime")


# ─── Command model ──────────────────────────────────────────────────────────


@dataclass
class RuntimeCommand:
    """A command sent to an AgentRuntime."""
    kind: str  # "process_turn", "interrupt", "reset", "shutdown"
    payload: dict = field(default_factory=dict)


@dataclass
class RuntimeEvent:
    """An event emitted by an AgentRuntime.

    The ``items`` field contains structured ThreadItem objects
    (not bare strings) so callers can persist them directly.
    """
    kind: str  # "turn_completed", "turn_failed", "item_produced", "approval_requested"
    turn_id: str = ""
    items: list = field(default_factory=list)
    error: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.kind in ("turn_completed", "item_produced")


# ─── AgentRuntime trait ─────────────────────────────────────────────────────


class AgentRuntime(abc.ABC):
    """Abstract interface for an agent execution backend.

    Each runtime receives turns (not bare messages) and produces
    ThreadItems (not raw text). The runtime is responsible for:
    - processing a turn with full context
    - emitting ThreadItems for each granular event
    - requesting approval when needed
    - managing its own native session if applicable
    """

    @property
    @abc.abstractmethod
    def kind(self) -> str:
        """Return the RuntimeKind string for this runtime."""
        ...

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Set up the runtime. Called once at startup."""
        ...

    @abc.abstractmethod
    async def process_turn(
        self,
        turn: Turn,
        prior_items: list[ThreadItem],
    ) -> RuntimeEvent:
        """Process one turn with full context.

        Args:
            turn: The current turn being processed (includes user message).
            prior_items: All ThreadItems from prior turns (for context).

        Returns:
            RuntimeEvent with completed ThreadItems or failure.
        """
        ...

    @abc.abstractmethod
    async def process_turn_streaming(
        self,
        turn: Turn,
        prior_items: list[ThreadItem],
        item_callback: Callable | None = None,
    ) -> RuntimeEvent:
        """Process a turn with streaming support.

        Args:
            turn: The current turn being processed.
            prior_items: Prior ThreadItems for context.
            item_callback: Optional async callback called as each ThreadItem
                is produced during streaming.

        Returns:
            RuntimeEvent with all ThreadItems produced during the turn.
        """
        ...

    @abc.abstractmethod
    async def interrupt(self, turn_id: str) -> bool:
        """Try to interrupt a running turn. Returns True if interrupted."""
        ...

    @abc.abstractmethod
    async def reset(self) -> None:
        """Reset runtime state (new conversation)."""
        ...

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Release runtime resources."""
        ...

    @abc.abstractmethod
    async def get_status(self) -> dict:
        """Return runtime status info."""
        ...


# ─── HermesRuntime ──────────────────────────────────────────────────────────


class HermesRuntime(AgentRuntime):
    """V2-conformant wrapper around Hermes CLI subprocess dispatch.

    Wraps the existing HermesManager but adopts the V2 contract:
    - Receives Turn + prior_items instead of raw text
    - Produces structured ThreadItems (user_message, agent_message, system_event)
    - Supports interruption and reset
    - Returns items as actual ThreadItem dataclass instances
    """

    def __init__(self, manager):
        from gateway.hermes_manager import HermesManager
        self._manager: HermesManager = manager
        self._busy: bool = False
        self._current_turn_id: str = ""

    @property
    def kind(self) -> str:
        return "hermes"

    async def initialize(self) -> None:
        await self._manager.initialize()
        logger.info("HermesRuntime initialized via existing HermesManager")

    async def _build_thread_items(
        self,
        turn: Turn,
        prior_items: list[ThreadItem],
        user_text: str,
        reply_text: str,
        is_error: bool = False,
        metadata: dict | None = None,
    ) -> list:
        """Build ThreadItem objects from a completed Hermes response.

        Returns structured items that can be persisted directly.
        """
        from gateway.v2.models import ThreadItem as V2ThreadItem, ThreadItemKind, utc_now

        items = []
        ts = utc_now()

        # User message item (captures what was sent)
        user_item = V2ThreadItem(
            id=f"rt_user_{turn.id[:8]}",
            thread_id=turn.thread_id,
            turn_id=turn.id,
            kind=ThreadItemKind.user_message,
            index=0,
            role="user",
            content=user_text,
            metadata={"runtime": "hermes", "generated": True},
            created_at=ts,
        )
        items.append(user_item)

        if is_error:
            # System event for errors
            error_item = V2ThreadItem(
                id=f"rt_err_{turn.id[:8]}",
                thread_id=turn.thread_id,
                turn_id=turn.id,
                kind=ThreadItemKind.system_event,
                index=1,
                role="system",
                content=reply_text,
                metadata=metadata or {},
                created_at=ts,
            )
            items.append(error_item)
        else:
            # Agent message item
            agent_item = V2ThreadItem(
                id=f"rt_agent_{turn.id[:8]}",
                thread_id=turn.thread_id,
                turn_id=turn.id,
                kind=ThreadItemKind.agent_message,
                index=1,
                role="agent",
                content=reply_text,
                metadata=metadata or {},
                created_at=ts,
            )
            items.append(agent_item)

        return items

    async def process_turn(
        self,
        turn: Turn,
        prior_items: list[ThreadItem],
    ) -> RuntimeEvent:
        self._busy = True
        self._current_turn_id = turn.id

        # Find the user message text
        if turn.user_message_id:
            user_msg = next(
                (item for item in prior_items if item.id == turn.user_message_id),
                None,
            )
            text = user_msg.content if user_msg else turn.user_message_id
        else:
            text = turn.user_message_id or ""

        # Build context from prior items (user + agent messages only, not generated runtime items)
        context_messages = [
            m for m in prior_items
            if m.kind in ("user_message", "agent_message")
            and not m.metadata.get("generated")
        ]

        # Dispatch to Hermes via existing manager
        from gateway.models import Message, MessageRole

        hermes_context = []
        for item in context_messages:
            role = MessageRole.user if item.role == "user" else MessageRole.agent
            hermes_context.append(Message(
                id=item.id,
                agent_id="hermes-agent",
                role=role,
                text=item.content,
                timestamp=item.created_at,
            ))

        result = await self._manager.send_task(
            message=text,
            timeout=120.0,
            context_messages=hermes_context if hermes_context else None,
        )

        self._busy = False
        self._current_turn_id = ""

        meta = {
            "runtime": "hermes",
            "executable": result.executable if result.success else "",
            "duration_ms": result.duration_ms,
        }

        if result.success:
            items = await self._build_thread_items(
                turn=turn,
                prior_items=prior_items,
                user_text=text,
                reply_text=result.text,
                metadata=meta,
            )
            return RuntimeEvent(
                kind="turn_completed",
                turn_id=turn.id,
                items=items,
                metadata=meta,
            )
        else:
            items = await self._build_thread_items(
                turn=turn,
                prior_items=prior_items,
                user_text=text,
                reply_text=result.error,
                is_error=True,
                metadata=meta,
            )
            return RuntimeEvent(
                kind="turn_failed",
                turn_id=turn.id,
                items=items,
                error=result.error,
                metadata=meta,
            )

    async def process_turn_streaming(
        self,
        turn: Turn,
        prior_items: list[ThreadItem],
        item_callback: Callable | None = None,
    ) -> RuntimeEvent:
        """Process a turn with item callback for streaming.

        Currently wraps the non-streaming process_turn and calls the
        callback with completed items. Future work will make this truly
        streaming by emitting items mid-execution.
        """
        event = await self.process_turn(turn, prior_items)
        if item_callback and event.items:
            for item in event.items:
                try:
                    await item_callback(item, event.kind)
                except Exception as e:
                    logger.warning("Streaming callback failed: %s", e)
        return event

    async def interrupt(self, turn_id: str) -> bool:
        logger.warning("HermesRuntime.interrupt not yet implemented")
        return False

    async def reset(self) -> None:
        logger.info("HermesRuntime.reset")
        self._busy = False
        self._current_turn_id = ""

    async def shutdown(self) -> None:
        await self._manager.cleanup()
        logger.info("HermesRuntime shutdown")

    async def get_status(self) -> dict:
        status = await self._manager.get_status()
        return {
            "kind": "hermes",
            "available": status.available,
            "version": status.version,
            "busy": self._busy,
            "executable_path": status.executable_path,
            "usable": status.usable,
        }


# ─── ServerSessionRuntime ───────────────────────────────────────────────────


class ServerSessionRuntime:
    """Owns the agent runtimes for one server session.

    A ServerSessionRuntime is created when a device connects and is
    torn down on disconnect. It manages:
    - The pool of AgentRuntime instances available to this session
    - Thread-to-runtime routing
    - Thread lifecycle (create, pause, resume, archive)
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._runtimes: dict[str, AgentRuntime] = {}
        self._thread_routes: dict[str, str] = {}  # thread_id -> runtime_kind
        logger.info("ServerSessionRuntime created for session=%s", session_id)

    def register_runtime(self, kind: str, runtime: AgentRuntime) -> None:
        self._runtimes[kind] = runtime
        logger.info("Runtime registered: session=%s runtime=%s", self.session_id, kind)

    def get_runtime(self, kind: str) -> AgentRuntime | None:
        return self._runtimes.get(kind)

    def route_thread(self, thread_id: str, runtime_kind: str) -> None:
        self._thread_routes[thread_id] = runtime_kind

    def get_runtime_for_thread(self, thread_id: str) -> AgentRuntime | None:
        kind = self._thread_routes.get(thread_id)
        if kind is None:
            return None
        return self._runtimes.get(kind)

    async def shutdown_all(self) -> None:
        for kind, runtime in self._runtimes.items():
            logger.info("Shutting down runtime: session=%s runtime=%s", self.session_id, kind)
            await runtime.shutdown()
        self._runtimes.clear()
        self._thread_routes.clear()
