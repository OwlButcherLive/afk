"""SQLite persistence layer for the Agent Gateway.

Uses aiosqlite for async database access.
Tables are created on startup and seeded with a default agent.
"""

import sqlite3
import uuid
from pathlib import Path

import aiosqlite

from gateway.models import (
    Agent,
    AgentStatus,
    Message,
    MessageRole,
    Session,
    utc_now,
)

DB_PATH = Path(__file__).resolve().parent.parent / "gateway.db"


# ─── Synchronous helpers (used during startup) ───────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and seed default agent. Safe to call repeatedly."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                id   TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'online'
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id        TEXT PRIMARY KEY,
                agent_id  TEXT NOT NULL REFERENCES agents(id),
                title     TEXT NOT NULL DEFAULT 'New conversation',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id        TEXT PRIMARY KEY,
                session_id TEXT REFERENCES sessions(id),
                agent_id  TEXT NOT NULL REFERENCES agents(id),
                role      TEXT NOT NULL CHECK(role IN ('user', 'agent')),
                text      TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at DESC);

            CREATE INDEX IF NOT EXISTS idx_messages_session_ts
                ON messages(session_id, timestamp ASC);

            CREATE INDEX IF NOT EXISTS idx_messages_agent_ts
                ON messages(agent_id, timestamp DESC);
        """)

        # Seed default agent if missing
        row = conn.execute(
            "SELECT id FROM agents WHERE id = ?", ("default",)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO agents (id, name, status) VALUES (?, ?, ?)",
                ("default", "Default Agent", "online"),
            )
            conn.commit()

        # Seed factory-droid agent if missing
        droid_row = conn.execute(
            "SELECT id FROM agents WHERE id = ?", ("factory-droid",)
        ).fetchone()
        if droid_row is None:
            conn.execute(
                "INSERT INTO agents (id, name, status) VALUES (?, ?, ?)",
                ("factory-droid", "Factory Droid", "online"),
            )
            conn.commit()

        # Create a default session for backward compat if missing
        default_sess = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", ("default",)
        ).fetchone()
        if default_sess is None:
            conn.execute(
                "INSERT INTO sessions (id, agent_id, title, updated_at) VALUES (?, ?, ?, ?)",
                ("default", "default", "Default conversation", utc_now()),
            )
            conn.commit()
    finally:
        conn.close()


# ─── Async data access ──────────────────────────────────────────────────────

async def get_async_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(DB_PATH))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def get_agents() -> list[Agent]:
    conn = await get_async_conn()
    try:
        cursor = await conn.execute("SELECT id, name, status FROM agents ORDER BY id")
        rows = await cursor.fetchall()
        return [
            Agent(id=row["id"], name=row["name"], status=AgentStatus(row["status"]))
            for row in rows
        ]
    finally:
        await conn.close()


async def get_agent(agent_id: str) -> Agent | None:
    conn = await get_async_conn()
    try:
        cursor = await conn.execute(
            "SELECT id, name, status FROM agents WHERE id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Agent(id=row["id"], name=row["name"], status=AgentStatus(row["status"]))
    finally:
        await conn.close()


async def save_message(
    message_id: str,
    session_id: str,
    agent_id: str,
    role: MessageRole,
    text: str,
    timestamp: str | None = None,
) -> Message:
    ts = timestamp or utc_now()
    conn = await get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO messages (id, session_id, agent_id, role, text, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, session_id, agent_id, role.value, text, ts),
        )
        await conn.commit()

        # Update session's updated_at and title from first user message
        if role == MessageRole.user:
            preview = text[:80] + ("..." if len(text) > 80 else "")
            await conn.execute(
                "UPDATE sessions SET updated_at = ?, title = ? WHERE id = ?",
                (ts, preview, session_id),
            )
        else:
            await conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (ts, session_id),
            )
        await conn.commit()

        return Message(id=message_id, agent_id=agent_id, role=role, text=text, timestamp=ts)
    finally:
        await conn.close()


async def get_history(
    agent_id: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[Message]:
    conn = await get_async_conn()
    try:
        if session_id:
            cursor = await conn.execute(
                """
                SELECT id, agent_id, role, text, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (session_id, limit),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT id, agent_id, role, text, timestamp
                FROM messages
                WHERE agent_id = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (agent_id, limit),
            )
        rows = await cursor.fetchall()
        return [
            Message(
                id=row["id"],
                agent_id=row["agent_id"],
                role=MessageRole(row["role"]),
                text=row["text"],
                timestamp=row["timestamp"],
            )
            for row in rows
        ]
    finally:
        await conn.close()


# ─── Session CRUD ────────────────────────────────────────────────────────────

async def create_session(agent_id: str) -> Session:
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    ts = utc_now()
    conn = await get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO sessions (id, agent_id, title, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, agent_id, "New conversation", ts),
        )
        await conn.commit()
        return Session(id=session_id, agent_id=agent_id, title="New conversation", updated_at=ts)
    finally:
        await conn.close()


async def get_sessions() -> list[Session]:
    conn = await get_async_conn()
    try:
        cursor = await conn.execute(
            """
            SELECT s.id, s.agent_id, s.title, s.updated_at,
                   COALESCE(m.text, '') as last_text
            FROM sessions s
            LEFT JOIN messages m ON m.id = (
                SELECT id FROM messages WHERE session_id = s.id
                ORDER BY timestamp DESC LIMIT 1
            )
            ORDER BY s.updated_at DESC
            """,
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            preview = row["last_text"]
            if preview:
                role_prefix = "You said: "  # will be overridden below
                # Try to determine if last message was user or agent
                preview = preview[:80] + ("..." if len(preview) > 80 else "")
            result.append(
                Session(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    title=row["title"],
                    last_message_preview=preview if preview else "",
                    updated_at=row["updated_at"],
                )
            )
        return result
    finally:
        await conn.close()


async def get_session(session_id: str) -> Session | None:
    conn = await get_async_conn()
    try:
        cursor = await conn.execute(
            """
            SELECT id, agent_id, title, updated_at
            FROM sessions WHERE id = ?
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Session(
            id=row["id"],
            agent_id=row["agent_id"],
            title=row["title"],
            updated_at=row["updated_at"],
        )
    finally:
        await conn.close()
