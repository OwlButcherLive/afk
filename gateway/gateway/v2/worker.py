"""Worker pattern for AFK V2 runtimes.

Each runtime worker owns its client/process and communicates via
asyncio.Queue command channels. This provides:
- explicit worker lifecycle (start, shutdown)
- natural backpressure via bounded queues
- testable command/response flow
- clean separation between caller and worker
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from gateway.v2.runtime import AgentRuntime, RuntimeEvent

logger = logging.getLogger("gateway.v2.worker")


# ─── Command protocol ───────────────────────────────────────────────────────


class WorkerCommandKind(str, Enum):
    """Types of commands that can be sent to a worker."""
    process_turn = "process_turn"
    interrupt = "interrupt"
    reset = "reset"
    get_status = "get_status"
    shutdown = "shutdown"


@dataclass
class WorkerCommand:
    """A command sent to a runtime worker via its channel."""
    kind: WorkerCommandKind
    payload: dict = field(default_factory=dict)
    reply_to: asyncio.Future | None = None

    def reply(self, value: Any) -> None:
        if self.reply_to and not self.reply_to.done():
            self.reply_to.set_result(value)


@dataclass
class WorkerResult:
    """Result produced by a worker."""
    ok: bool = True
    value: Any = None
    error: str = ""


# ─── Runtime Worker ─────────────────────────────────────────────────────────


class RuntimeWorker:
    """A worker that wraps an AgentRuntime with a command channel.

    The worker owns the runtime instance and processes commands
    sequentially from its input queue. Shutdown is explicit via
    the shutdown command.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        queue_size: int = 16,
        worker_id: str = "",
    ):
        self.runtime = runtime
        self.worker_id = worker_id or f"worker_{id(self)}"
        self._cmd_queue: asyncio.Queue[WorkerCommand] = asyncio.Queue(maxsize=queue_size)
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the worker's event loop."""
        if self._running:
            return
        self._running = True
        await self.runtime.initialize()
        self._task = asyncio.create_task(self._run())
        logger.info("Worker started: id=%s runtime=%s", self.worker_id, self.runtime.kind)

    async def _run(self) -> None:
        """Main event loop — process commands from the queue."""
        try:
            while self._running:
                try:
                    cmd = await asyncio.wait_for(self._cmd_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                try:
                    result = await self._execute_command(cmd)
                    cmd.reply(result)
                except Exception as e:
                    logger.error("Worker command failed: worker=%s cmd=%s error=%s",
                                  self.worker_id, cmd.kind, e)
                    cmd.reply(WorkerResult(ok=False, error=str(e)))
                finally:
                    self._cmd_queue.task_done()
        except asyncio.CancelledError:
            logger.info("Worker cancelled: id=%s", self.worker_id)
        finally:
            self._running = False

    async def _execute_command(self, cmd: WorkerCommand) -> WorkerResult:
        """Execute a single command."""
        if cmd.kind == WorkerCommandKind.process_turn:
            from gateway.v2.models import Turn, ThreadItem
            turn_data = cmd.payload.get("turn")
            prior_items = cmd.payload.get("prior_items", [])
            turn = Turn(**turn_data) if isinstance(turn_data, dict) else None
            if turn is None:
                return WorkerResult(ok=False, error="No turn data in payload")
            items = [ThreadItem(**i) if isinstance(i, dict) else i for i in prior_items]
            event = await self.runtime.process_turn(turn, items)
            return WorkerResult(value=event)

        elif cmd.kind == WorkerCommandKind.interrupt:
            turn_id = cmd.payload.get("turn_id", "")
            ok = await self.runtime.interrupt(turn_id)
            return WorkerResult(value={"interrupted": ok})

        elif cmd.kind == WorkerCommandKind.reset:
            await self.runtime.reset()
            return WorkerResult(value={"reset": True})

        elif cmd.kind == WorkerCommandKind.get_status:
            status = await self.runtime.get_status()
            return WorkerResult(value=status)

        elif cmd.kind == WorkerCommandKind.shutdown:
            await self.runtime.shutdown()
            self._running = False
            return WorkerResult(value={"shutdown": True})

        else:
            return WorkerResult(ok=False, error=f"Unknown command: {cmd.kind}")

    async def send_command(
        self,
        kind: WorkerCommandKind,
        payload: dict | None = None,
        timeout: float = 30.0,
    ) -> WorkerResult:
        """Send a command and wait for the result."""
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        cmd = WorkerCommand(
            kind=kind,
            payload=payload or {},
            reply_to=future,
        )
        try:
            await asyncio.wait_for(self._cmd_queue.put(cmd), timeout=5.0)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            error_msg = f"Command timed out: {kind}"
            logger.warning("Worker timeout: worker=%s %s", self.worker_id, error_msg)
            return WorkerResult(ok=False, error=error_msg)

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Shutdown the worker gracefully."""
        if not self._running:
            return
        logger.info("Shutting down worker: id=%s", self.worker_id)
        await self.send_command(WorkerCommandKind.shutdown, timeout=timeout)
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        self._running = False


# ─── Worker Pool ────────────────────────────────────────────────────────────


class WorkerPool:
    """Manages a pool of runtime workers.

    Workers are indexed by runtime kind (e.g. 'hermes').
    Each runtime kind gets at most one worker.
    """

    def __init__(self):
        self._workers: dict[str, RuntimeWorker] = {}

    def get(self, kind: str) -> RuntimeWorker | None:
        return self._workers.get(kind)

    async def register(
        self,
        kind: str,
        runtime_factory: Callable[[], AgentRuntime],
    ) -> RuntimeWorker:
        """Create and start a worker for the given runtime kind."""
        if kind in self._workers:
            logger.warning("Worker already registered for kind=%s, replacing", kind)
            await self._workers[kind].shutdown()

        runtime = runtime_factory()
        worker = RuntimeWorker(runtime=runtime, worker_id=f"pool_{kind}")
        await worker.start()
        self._workers[kind] = worker
        logger.info("Worker registered: kind=%s worker=%s", kind, worker.worker_id)
        return worker

    async def shutdown_all(self) -> None:
        """Shutdown all workers."""
        for kind, worker in list(self._workers.items()):
            logger.info("Shutting down pool worker: kind=%s", kind)
            await worker.shutdown()
        self._workers.clear()

    def list_workers(self) -> list[dict]:
        """Return info about each registered worker."""
        result = []
        for kind, worker in self._workers.items():
            runtime_kind = worker.runtime.kind if hasattr(worker.runtime, 'kind') else kind
            result.append({
                "kind": runtime_kind,
                "worker_id": worker.worker_id,
                "status": "running" if worker.is_running else "stopped",
                "active_turns": 0,
            })
        return result
