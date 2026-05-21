"""ThreadStore — V2 persistence for threads, turns, and thread items."""

import json
import logging

from gateway.v2 import database as v2db
from gateway.v2.models import (
    Thread,
    ThreadItem,
    ThreadResponse,
    ThreadStatus,
    Turn,
    TurnResponse,
    TurnStatus,
    utc_now,
    new_id,
)

logger = logging.getLogger("gateway.v2.thread_store")


# ─── Thread CRUD ────────────────────────────────────────────────────────────


async def create_thread(
    server_session_id: str,
    runtime_kind: str = "hermes",
    title: str = "",
) -> Thread:
    """Create a new thread in a server session."""
    tid = new_id("thread_")
    ts = utc_now()
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO threads (id, server_session_id, runtime_kind, status, title, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, server_session_id, runtime_kind, "active", title, "{}", ts, ts),
        )
        await conn.commit()
        return Thread(
            id=tid,
            server_session_id=server_session_id,
            runtime_kind=runtime_kind,
            title=title,
            created_at=ts,
            updated_at=ts,
        )
    finally:
        await conn.close()


async def get_thread(thread_id: str) -> Thread | None:
    conn = await v2db.get_async_conn()
    try:
        cursor = await conn.execute(
            "SELECT id, server_session_id, runtime_kind, status, title, metadata, created_at, updated_at "
            "FROM threads WHERE id = ?", (thread_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Thread(
            id=row["id"],
            server_session_id=row["server_session_id"],
            runtime_kind=row["runtime_kind"],
            status=ThreadStatus(row["status"]),
            title=row["title"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    finally:
        await conn.close()


async def list_threads(server_session_id: str | None = None, limit: int = 50) -> list[ThreadResponse]:
    conn = await v2db.get_async_conn()
    try:
        if server_session_id:
            cursor = await conn.execute(
                "SELECT t.*, "
                "(SELECT COUNT(*) FROM turns WHERE thread_id = t.id) as turn_count, "
                "(SELECT content FROM thread_items WHERE thread_id = t.id AND kind='user_message' "
                " ORDER BY created_at DESC LIMIT 1) as last_preview "
                "FROM threads t WHERE t.server_session_id = ? "
                "ORDER BY t.updated_at DESC LIMIT ?",
                (server_session_id, limit),
            )
        else:
            cursor = await conn.execute(
                "SELECT t.*, "
                "(SELECT COUNT(*) FROM turns WHERE thread_id = t.id) as turn_count, "
                "(SELECT content FROM thread_items WHERE thread_id = t.id AND kind='user_message' "
                " ORDER BY created_at DESC LIMIT 1) as last_preview "
                "FROM threads t ORDER BY t.updated_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            preview = row["last_preview"] or ""
            results.append(ThreadResponse(
                id=row["id"],
                server_session_id=row["server_session_id"],
                runtime_kind=row["runtime_kind"],
                status=ThreadStatus(row["status"]),
                title=row["title"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                turn_count=row["turn_count"],
                last_message_preview=preview[:80] + ("..." if len(preview) > 80 else ""),
            ))
        return results
    finally:
        await conn.close()


async def update_thread_status(thread_id: str, status: ThreadStatus) -> None:
    ts = utc_now()
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, ts, thread_id),
        )
        await conn.commit()
    finally:
        await conn.close()


# ─── Turn CRUD ──────────────────────────────────────────────────────────────


async def create_turn(thread_id: str, turn_index: int) -> Turn:
    tid = new_id("turn_")
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO turns (id, thread_id, status, turn_index, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (tid, thread_id, "pending", turn_index, utc_now()),
        )
        await conn.commit()
        return Turn(id=tid, thread_id=thread_id, turn_index=turn_index)
    finally:
        await conn.close()


async def get_turn(turn_id: str) -> Turn | None:
    conn = await v2db.get_async_conn()
    try:
        cursor = await conn.execute(
            "SELECT * FROM turns WHERE id = ?", (turn_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Turn(
            id=row["id"],
            thread_id=row["thread_id"],
            status=TurnStatus(row["status"]),
            turn_index=row["turn_index"],
            user_message_id=row["user_message_id"],
            agent_message_id=row["agent_message_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )
    finally:
        await conn.close()


async def list_turns(thread_id: str) -> list[Turn]:
    conn = await v2db.get_async_conn()
    try:
        cursor = await conn.execute(
            "SELECT * FROM turns WHERE thread_id = ? ORDER BY turn_index ASC",
            (thread_id,),
        )
        rows = await cursor.fetchall()
        return [
            Turn(
                id=row["id"],
                thread_id=row["thread_id"],
                status=TurnStatus(row["status"]),
                turn_index=row["turn_index"],
                user_message_id=row["user_message_id"],
                agent_message_id=row["agent_message_id"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                error=row["error"],
            )
            for row in rows
        ]
    finally:
        await conn.close()


async def update_turn_status(turn_id: str, status: TurnStatus, error: str | None = None) -> None:
    conn = await v2db.get_async_conn()
    try:
        if status == TurnStatus.completed:
            await conn.execute(
                "UPDATE turns SET status = ?, completed_at = ? WHERE id = ?",
                (status.value, utc_now(), turn_id),
            )
        elif status == TurnStatus.failed:
            await conn.execute(
                "UPDATE turns SET status = ?, completed_at = ?, error = ? WHERE id = ?",
                (status.value, utc_now(), error or "", turn_id),
            )
        else:
            await conn.execute(
                "UPDATE turns SET status = ? WHERE id = ?",
                (status.value, turn_id),
            )
        await conn.commit()
    finally:
        await conn.close()


async def set_turn_message_refs(turn_id: str, user_msg_id: str, agent_msg_id: str) -> None:
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "UPDATE turns SET user_message_id = ?, agent_message_id = ? WHERE id = ?",
            (user_msg_id, agent_msg_id, turn_id),
        )
        await conn.commit()
    finally:
        await conn.close()


# ─── ThreadItem CRUD ────────────────────────────────────────────────────────


async def create_thread_item(
    thread_id: str,
    turn_id: str,
    kind: str,
    index: int,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> ThreadItem:
    iid = new_id("item_")
    ts = utc_now()
    meta_json = json.dumps(metadata or {})
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO thread_items (id, thread_id, turn_id, kind, item_index, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, thread_id, turn_id, kind, index, role, content, meta_json, ts),
        )
        await conn.commit()
        return ThreadItem(
            id=iid,
            thread_id=thread_id,
            turn_id=turn_id,
            kind=kind,
            index=index,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at=ts,
        )
    finally:
        await conn.close()


async def list_thread_items(thread_id: str, turn_id: str | None = None) -> list[ThreadItem]:
    conn = await v2db.get_async_conn()
    try:
        if turn_id:
            cursor = await conn.execute(
                "SELECT * FROM thread_items WHERE thread_id = ? AND turn_id = ? ORDER BY item_index ASC",
                (thread_id, turn_id),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM thread_items WHERE thread_id = ? ORDER BY item_index ASC",
                (thread_id,),
            )
        rows = await cursor.fetchall()
        return [
            ThreadItem(
                id=row["id"],
                thread_id=row["thread_id"],
                turn_id=row["turn_id"],
                kind=row["kind"],
                index=row["item_index"],
                role=row["role"],
                content=row["content"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                created_at=row["created_at"],
            )
            for row in rows
        ]
    finally:
        await conn.close()


async def get_turn_with_items(turn_id: str) -> TurnResponse | None:
    """Get a turn with all its thread items."""
    turn = await get_turn(turn_id)
    if turn is None:
        return None
    items = await list_thread_items(turn.thread_id, turn_id)
    return TurnResponse(
        id=turn.id,
        thread_id=turn.thread_id,
        status=turn.status,
        turn_index=turn.turn_index,
        items=items,
        started_at=turn.started_at,
        completed_at=turn.completed_at,
        error=turn.error,
    )
