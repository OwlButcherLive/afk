"""SessionStore — V2 persistence for ServerSession objects."""

import logging

from gateway.v2 import database as v2db
from gateway.v2.models import ServerSession, ConnectionHealth, utc_now, new_id

logger = logging.getLogger("gateway.v2.session_store")


async def create_server_session(
    name: str = "",
    client_platform: str = "android",
) -> ServerSession:
    """Create a new server session (device connection)."""
    sid = new_id("srv_")
    ts = utc_now()
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO server_sessions (id, name, client_platform, connection_health, created_at, updated_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, name, client_platform, "disconnected", ts, ts, ts),
        )
        await conn.commit()
        return ServerSession(
            id=sid,
            name=name,
            client_platform=client_platform,
            connection_health=ConnectionHealth.disconnected,
            created_at=ts,
            updated_at=ts,
            last_seen_at=ts,
        )
    finally:
        await conn.close()


async def get_server_session(session_id: str) -> ServerSession | None:
    conn = await v2db.get_async_conn()
    try:
        cursor = await conn.execute(
            "SELECT id, name, client_platform, connection_health, created_at, updated_at, last_seen_at "
            "FROM server_sessions WHERE id = ?", (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ServerSession(
            id=row["id"],
            name=row["name"],
            client_platform=row["client_platform"],
            connection_health=ConnectionHealth(row["connection_health"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_seen_at=row["last_seen_at"],
        )
    finally:
        await conn.close()


async def update_connection_health(session_id: str, health: ConnectionHealth) -> None:
    ts = utc_now()
    conn = await v2db.get_async_conn()
    try:
        await conn.execute(
            "UPDATE server_sessions SET connection_health = ?, updated_at = ?, last_seen_at = ? WHERE id = ?",
            (health.value, ts, ts, session_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def heartbeat(session_id: str) -> None:
    """Update last_seen_at and connection_health to connected."""
    await update_connection_health(session_id, ConnectionHealth.connected)


async def list_server_sessions(limit: int = 20) -> list[ServerSession]:
    conn = await v2db.get_async_conn()
    try:
        cursor = await conn.execute(
            "SELECT id, name, client_platform, connection_health, created_at, updated_at, last_seen_at "
            "FROM server_sessions ORDER BY last_seen_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            ServerSession(
                id=row["id"],
                name=row["name"],
                client_platform=row["client_platform"],
                connection_health=ConnectionHealth(row["connection_health"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                last_seen_at=row["last_seen_at"],
            )
            for row in rows
        ]
    finally:
        await conn.close()
