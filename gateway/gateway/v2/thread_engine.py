"""Thread lifecycle engine — explicit internal operations for thread management.

Provides the internal API for thread lifecycle operations:
  - thread/start    — create and begin a new thread
  - thread/resume   — reactivate a paused/archived thread
  - thread/read     — load thread with turns and items
  - thread/archive  - mark thread as archived
  - thread/set_name - update thread title
"""

import logging

from gateway.v2.models import (
    Thread,
    ThreadResponse,
    ThreadStatus,
    Turn,
    TurnStatus,
    utc_now,
    new_id,
)
from gateway.v2 import thread_store as ts

logger = logging.getLogger("gateway.v2.thread_engine")


# ─── Operation results ──────────────────────────────────────────────────────


class ThreadOpResult:
    """Result of a thread lifecycle operation."""
    def __init__(self, ok: bool = True, thread: ThreadResponse | None = None,
                 error: str = ""):
        self.ok = ok
        self.thread = thread
        self.error = error


class TurnOpResult:
    """Result of a turn lifecycle operation."""
    def __init__(self, ok: bool = True, turn: Turn | None = None,
                 error: str = ""):
        self.ok = ok
        self.turn = turn
        self.error = error


# ─── Thread lifecycle operations ────────────────────────────────────────────


async def thread_start(
    server_session_id: str,
    runtime_kind: str = "hermes",
    title: str = "",
) -> ThreadOpResult:
    """Create and start a new thread.

    This is the canonical 'new chat' operation. Creates the thread,
    sets it active, and prepares it to receive turns.
    """
    try:
        thread = await ts.create_thread(
            server_session_id=server_session_id,
            runtime_kind=runtime_kind,
            title=title,
        )
        response = await _thread_to_response(thread)
        logger.info("Thread started: id=%s session=%s runtime=%s",
                     thread.id, server_session_id, runtime_kind)
        return ThreadOpResult(thread=response)
    except Exception as e:
        logger.error("thread_start failed: %s", e)
        return ThreadOpResult(ok=False, error=str(e))


async def thread_resume(thread_id: str) -> ThreadOpResult:
    """Resume a paused or archived thread, making it active again."""
    try:
        thread = await ts.get_thread(thread_id)
        if thread is None:
            return ThreadOpResult(ok=False, error=f"Thread '{thread_id}' not found")

        if thread.status == ThreadStatus.active:
            # Already active — just return current state
            response = await _thread_to_response(thread)
            return ThreadOpResult(thread=response)

        await ts.update_thread_status(thread_id, ThreadStatus.active)
        thread.status = ThreadStatus.active
        response = await _thread_to_response(thread)
        logger.info("Thread resumed: id=%s", thread_id)
        return ThreadOpResult(thread=response)
    except Exception as e:
        logger.error("thread_resume failed: %s", e)
        return ThreadOpResult(ok=False, error=str(e))


async def thread_read(
    thread_id: str,
    include_items: bool = True,
) -> ThreadOpResult:
    """Read a thread with its turns and items."""
    try:
        thread = await ts.get_thread(thread_id)
        if thread is None:
            return ThreadOpResult(ok=False, error=f"Thread '{thread_id}' not found")

        response = await _thread_to_response(thread)
        if include_items:
            turns_list = await ts.list_turns(thread_id)
            # Attach items to each turn
            from gateway.v2.thread_store import get_turn_with_items
            turn_responses = []
            for t in turns_list:
                tr = await get_turn_with_items(t.id)
                if tr:
                    turn_responses.append(tr)
            # Store turns in metadata for now (will be separate field in projection)
            response.metadata["turns"] = [
                {
                    "id": tr.id,
                    "status": tr.status.value if hasattr(tr.status, 'value') else tr.status,
                    "turn_index": tr.turn_index,
                    "item_count": len(tr.items),
                    "started_at": tr.started_at,
                    "completed_at": tr.completed_at,
                    "error": tr.error,
                }
                for tr in turn_responses
            ]
            response.metadata["total_turns"] = len(turn_responses)
            # Also include full items if available
            all_items = await ts.list_thread_items(thread_id)
            response.metadata["total_items"] = len(all_items)

        return ThreadOpResult(thread=response)
    except Exception as e:
        logger.error("thread_read failed: %s", e)
        return ThreadOpResult(ok=False, error=str(e))


async def thread_archive(thread_id: str) -> ThreadOpResult:
    """Archive a thread (soft delete / hide from default list)."""
    try:
        thread = await ts.get_thread(thread_id)
        if thread is None:
            return ThreadOpResult(ok=False, error=f"Thread '{thread_id}' not found")

        await ts.update_thread_status(thread_id, ThreadStatus.archived)
        thread.status = ThreadStatus.archived
        response = await _thread_to_response(thread)
        logger.info("Thread archived: id=%s", thread_id)
        return ThreadOpResult(thread=response)
    except Exception as e:
        logger.error("thread_archive failed: %s", e)
        return ThreadOpResult(ok=False, error=str(e))


async def thread_set_name(thread_id: str, title: str) -> ThreadOpResult:
    """Update the thread title."""
    try:
        thread = await ts.get_thread(thread_id)
        if thread is None:
            return ThreadOpResult(ok=False, error=f"Thread '{thread_id}' not found")

        ts_now = utc_now()
        conn = None
        try:
            from gateway.v2 import database as v2db
            conn = await v2db.get_async_conn()
            await conn.execute(
                "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                (title, ts_now, thread_id),
            )
            await conn.commit()
        finally:
            if conn:
                await conn.close()

        thread.title = title
        response = await _thread_to_response(thread)
        logger.info("Thread renamed: id=%s title='%s'", thread_id, title)
        return ThreadOpResult(thread=response)
    except Exception as e:
        logger.error("thread_set_name failed: %s", e)
        return ThreadOpResult(ok=False, error=str(e))


async def list_threads_for_session(
    server_session_id: str,
    limit: int = 50,
) -> list[ThreadResponse]:
    """List active threads for a session."""
    return await ts.list_threads(
        server_session_id=server_session_id,
        limit=limit,
    )


# ─── Turn lifecycle operations ──────────────────────────────────────────────


async def turn_start(thread_id: str) -> TurnOpResult:
    """Start a new turn in the given thread.

    Creates a pending turn and sets it to running.
    Returns the turn ready to receive items.
    """
    try:
        # Find next turn index
        turns_list = await ts.list_turns(thread_id)
        next_index = len(turns_list)

        turn = await ts.create_turn(thread_id, next_index)
        await ts.update_turn_status(turn.id, TurnStatus.running)
        turn.status = TurnStatus.running

        logger.info("Turn started: thread=%s turn=%s index=%d",
                     thread_id, turn.id, next_index)
        return TurnOpResult(turn=turn)
    except Exception as e:
        logger.error("turn_start failed: %s", e)
        return TurnOpResult(ok=False, error=str(e))


async def turn_complete(
    turn_id: str,
    error: str | None = None,
) -> TurnOpResult:
    """Complete a turn (success or failure)."""
    try:
        if error:
            await ts.update_turn_status(turn_id, TurnStatus.failed, error=error)
        else:
            await ts.update_turn_status(turn_id, TurnStatus.completed)

        turn = await ts.get_turn(turn_id)
        return TurnOpResult(turn=turn)
    except Exception as e:
        logger.error("turn_complete failed: %s", e)
        return TurnOpResult(ok=False, error=str(e))


async def turn_interrupt(turn_id: str) -> TurnOpResult:
    """Interrupt a running turn."""
    try:
        turn = await ts.get_turn(turn_id)
        if turn is None:
            return TurnOpResult(ok=False, error=f"Turn '{turn_id}' not found")
        if turn.status != TurnStatus.running:
            return TurnOpResult(ok=False, error=f"Turn '{turn_id}' is not running (status={turn.status})")

        await ts.update_turn_status(turn_id, TurnStatus.interrupted)
        turn.status = TurnStatus.interrupted
        logger.info("Turn interrupted: id=%s", turn_id)
        return TurnOpResult(turn=turn)
    except Exception as e:
        logger.error("turn_interrupt failed: %s", e)
        return TurnOpResult(ok=False, error=str(e))


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _thread_to_response(thread: Thread) -> ThreadResponse:
    """Convert a Thread model to a ThreadResponse with computed fields."""
    turns_list = await ts.list_turns(thread.id)
    items = await ts.list_thread_items(thread.id)
    last_user = None
    for item in reversed(items):
        if item.kind == "user_message":
            last_user = item.content
            break
    preview = last_user[:80] + ("..." if last_user and len(last_user) > 80 else "") if last_user else ""
    return ThreadResponse(
        id=thread.id,
        server_session_id=thread.server_session_id,
        runtime_kind=thread.runtime_kind,
        status=thread.status,
        title=thread.title,
        metadata=thread.metadata,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        turn_count=len(turns_list),
        last_message_preview=preview,
    )
