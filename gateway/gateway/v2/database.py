"""AFK V2 schema evolution — new tables alongside existing V1 schema.

This module manages the V2 database tables. The V1 tables (agents, sessions,
messages) remain untouched for backward compatibility.

Migration approach:
- New tables are created alongside existing ones
- V2 code never reads/writes V1 tables directly
- V1 code never reads/writes V2 tables
- A gateway_version row tracks the schema version

Schema direction (for future milestones):

  server_sessions
    ├── threads
    │     ├── turns
    │     │     └── thread_items
    │     ├── thread_runtime_routes
    │     ├── pending_approvals
    │     └── queued_followups (future)
    └── connection_health_log (future)
"""

import sqlite3
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger("gateway.v2.db")

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "gateway.db"

_V2_SCHEMA_SQL = """
-- Server sessions: durable device connections
CREATE TABLE IF NOT EXISTS server_sessions (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL DEFAULT '',
    client_platform   TEXT NOT NULL DEFAULT 'android',
    connection_health TEXT NOT NULL DEFAULT 'disconnected',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL
);

-- Threads: conversation containers owned by a server session
CREATE TABLE IF NOT EXISTS threads (
    id                TEXT PRIMARY KEY,
    server_session_id TEXT NOT NULL REFERENCES server_sessions(id),
    runtime_kind      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active',
    title             TEXT NOT NULL DEFAULT '',
    metadata          TEXT NOT NULL DEFAULT '{}',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_session
    ON threads(server_session_id, updated_at DESC);

-- Turns: one user/agent exchange within a thread
CREATE TABLE IF NOT EXISTS turns (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL REFERENCES threads(id),
    status          TEXT NOT NULL DEFAULT 'pending',
    turn_index      INTEGER NOT NULL,
    user_message_id TEXT,
    agent_message_id TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_thread
    ON turns(thread_id, turn_index ASC);

-- Thread items: granular events inside a turn
CREATE TABLE IF NOT EXISTS thread_items (
    id          TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES threads(id),
    turn_id     TEXT NOT NULL REFERENCES turns(id),
    kind        TEXT NOT NULL,
    item_index  INTEGER NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_turn
    ON thread_items(thread_id, turn_id, item_index ASC);

-- Runtime routes: maps threads to active agent runtimes
CREATE TABLE IF NOT EXISTS thread_runtime_routes (
    thread_id          TEXT PRIMARY KEY REFERENCES threads(id),
    runtime_kind       TEXT NOT NULL,
    runtime_session_id TEXT,
    attached_at        TEXT NOT NULL
);

-- Pending approvals: actions awaiting user confirmation
CREATE TABLE IF NOT EXISTS pending_approvals (
    id          TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES threads(id),
    turn_id     TEXT NOT NULL REFERENCES turns(id),
    item_id     TEXT NOT NULL REFERENCES thread_items(id),
    kind        TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_pending
    ON pending_approvals(thread_id, status);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS gateway_schema (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


# ─── Synchronous helpers (used during startup) ───────────────────────────────


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_v2_schema() -> None:
    """Create V2 tables if they don't exist. Safe to call repeatedly."""
    conn = _get_conn()
    try:
        conn.executescript(_V2_SCHEMA_SQL)
        # Record schema version
        from gateway.v2.models import utc_now
        conn.execute(
            "INSERT OR IGNORE INTO gateway_schema (version, applied_at) VALUES (?, ?)",
            (2, utc_now()),
        )
        conn.commit()
        logger.info("V2 schema initialized (tables: server_sessions, threads, turns, thread_items, ...)")
    finally:
        conn.close()


# ─── Async data access ──────────────────────────────────────────────────────


async def get_async_conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(_DB_PATH))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn
