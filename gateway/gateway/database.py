"""SQLite persistence layer for the Agent Gateway.

Uses aiosqlite for async database access.
Tables are created on startup and seeded with a default agent.
"""

import sqlite3
from pathlib import Path

import aiosqlite

from gateway.models import (
    Agent,
    AgentStatus,
    Message,
    MessageRole,
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

            CREATE TABLE IF NOT EXISTS messages (
                id        TEXT PRIMARY KEY,
                agent_id  TEXT NOT NULL REFERENCES agents(id),
                role      TEXT NOT NULL CHECK(role IN ('user', 'agent')),
                text      TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

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
    agent_id: str,
    role: MessageRole,
    text: str,
    timestamp: str | None = None,
) -> Message:
    ts = timestamp or utc_now()
    conn = await get_async_conn()
    try:
        await conn.execute(
            "INSERT INTO messages (id, agent_id, role, text, timestamp) VALUES (?, ?, ?, ?, ?)",
            (message_id, agent_id, role.value, text, ts),
        )
        await conn.commit()
        return Message(id=message_id, agent_id=agent_id, role=role, text=text, timestamp=ts)
    finally:
        await conn.close()


async def get_history(agent_id: str, limit: int = 50) -> list[Message]:
    conn = await get_async_conn()
    try:
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
