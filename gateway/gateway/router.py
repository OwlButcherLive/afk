"""REST router for the Agent Gateway.

All data-reading endpoints are now fully V2-backed:
  GET /chat/sessions       — V2 compat (thread projection)
  GET /chat/sessions/{id}  — V2 compat (thread read)
  GET /chat/history        — V2 compat (thread items)
  GET /chat/agents         — V1 DB (agents table is stable, not data)
  POST /chat/sessions      — V1 DB session + eager V2 thread mapping
  GET /health              — no change

V2-native endpoints (projection layer, no V1 compat):
  GET /api/v2/threads      — list threads for default server session
  GET /api/v2/threads/{id} — thread detail with snapshot
  GET /api/v2/runtimes     — available runtime kinds and status
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from gateway import database as db
from gateway.hermes_manager import HermesManager
from gateway.v2 import compat as v2_compat
from gateway.v2.projection import build_thread_list, build_thread_projection
from gateway.v2.worker import WorkerPool

logger = logging.getLogger("gateway.router")

router = APIRouter()

# Set during lifespan in main.py
_hermes_manager: HermesManager | None = None
_worker_pool: WorkerPool | None = None


def set_hermes_manager(hm: HermesManager) -> None:
    global _hermes_manager
    _hermes_manager = hm


def set_worker_pool(pool: WorkerPool) -> None:
    global _worker_pool
    _worker_pool = pool


# ─── Response models ─────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str


class AgentItem(BaseModel):
    id: str
    name: str
    status: str = "online"


class AgentsResponse(BaseModel):
    agents: list[AgentItem]


class V1MessageItem(BaseModel):
    id: str
    agent_id: str
    role: str
    text: str
    timestamp: str


class HistoryResponse(BaseModel):
    messages: list[V1MessageItem]


class V1SessionItem(BaseModel):
    id: str
    agent_id: str
    title: str
    last_message_preview: str = ""
    updated_at: str = ""
    message_count: int = 0
    is_active: bool = True


class SessionsListResponse(BaseModel):
    sessions: list[V1SessionItem]


class SessionResponse(BaseModel):
    id: str
    agent_id: str
    title: str
    last_message_preview: str = ""
    updated_at: str = ""


class CreateSessionRequest(BaseModel):
    agent_id: str


# ─── Health ──────────────────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


# ─── Agents ──────────────────────────────────────────────────────────────────


@router.get("/chat/agents", response_model=AgentsResponse)
async def list_agents():
    """List available agents. Reads from V1 DB (agents table is stable)."""
    agents = await db.get_agents()
    return AgentsResponse(agents=[AgentItem(id=a.id, name=a.name, status=a.status.value) for a in agents])


# ─── History (V2-backed) ────────────────────────────────────────────────────


@router.get("/chat/history", response_model=HistoryResponse)
async def chat_history(
    session: str | None = Query(None, description="Session ID"),
    agent: str | None = Query("default", description="Agent ID (fallback if no session)"),
    limit: int = Query(50, ge=1, le=200, description="Max messages"),
):
    """Get chat history. Fully V2-backed via compat bridge.

    Reads from V2 thread items via compat. Supports both
    session-based and agent-based queries.
    """
    if session:
        # Session-based: try V2 compat first
        v2_messages = await v2_compat.get_v1_history(session)
        if v2_messages is not None:
            return HistoryResponse(messages=[V1MessageItem(**m) for m in v2_messages])

        # Not found in V2 — 404
        raise HTTPException(status_code=404, detail=f"Session '{session}' not found")
    else:
        # Validate agent via V1 DB (agents table is stable)
        all_agents = await db.get_agents()
        agent_ids = {a.id for a in all_agents}
        v1_agent = agent or "default"
        if v1_agent not in agent_ids:
            raise HTTPException(status_code=404, detail=f"Agent '{v1_agent}' not found")

        # Agent-based: read from V2 compat across all threads
        v2_messages = await v2_compat.get_v1_history_by_agent(
            v1_agent_id=v1_agent,
            limit=limit,
        )
        return HistoryResponse(messages=[V1MessageItem(**m) for m in v2_messages])


# ─── Session endpoints (V2-backed) ──────────────────────────────────────────


@router.get("/chat/sessions", response_model=SessionsListResponse)
async def list_sessions():
    """List sessions. Reads from V2 compat via projection + V1 DB fallback.

    V2 threads are the primary source. V1 DB sessions that haven't
    mapped to a V2 thread are merged in for backward compatibility.
    """
    v1_db_sessions = await db.get_sessions()
    v2_sessions = await v2_compat.get_v1_session_list(v1_db_sessions=v1_db_sessions)
    return SessionsListResponse(sessions=[V1SessionItem(**s) for s in v2_sessions])


@router.post("/chat/sessions", response_model=SessionResponse, status_code=201)
async def create_session(req: CreateSessionRequest):
    """Create a new session. Creates in V1 DB + eager V2 thread mapping."""
    agent = await db.get_agent(req.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' not found")

    # Create in V1 DB
    session = await db.create_session(req.agent_id)

    # Eagerly create V2 thread mapping for this session
    v2_thread_id = await v2_compat.get_or_create_v2_thread_for_v1_session(
        v1_session_id=session.id,
        agent_id=req.agent_id,
    )
    if not v2_thread_id:
        logger.warning("Failed to create eager V2 thread for session=%s", session.id)

    return SessionResponse(
        id=session.id,
        agent_id=session.agent_id,
        title=session.title,
        updated_at=session.updated_at,
    )


@router.get("/chat/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get a single session by ID. Fully V2-backed via compat bridge."""
    v2_session = await v2_compat.get_v1_session_by_id(session_id)
    if v2_session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionResponse(**v2_session)


# ─── Hermes status ──────────────────────────────────────────────────────────


@router.get("/agents/hermes-agent/status")
async def hermes_status():
    """Get Hermes Agent CLI status."""
    if _hermes_manager is None:
        return {"available": False, "error": "Hermes manager not initialized"}
    status = await _hermes_manager.get_status()
    return {
        "available": status.available,
        "version": status.version,
        "busy": status.busy,
        "error": status.error,
        "executable_path": status.executable_path,
        "candidates_checked": status.candidates_checked,
        "usable": status.usable,
        "usable_reason": status.usable_reason,
        "deep_probe_ok": status.deep_probe_ok,
        "deep_probe_error": status.deep_probe_error,
    }


# ─── V2-native REST endpoints (projection layer) ────────────────────────────


class V2ThreadListItem(BaseModel):
    id: str
    title: str
    status: str
    runtime_kind: str
    turn_count: int
    last_message_preview: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_active: bool = True


class V2ThreadListResponse(BaseModel):
    threads: list[V2ThreadListItem]


class V2ThreadDetailResponse(BaseModel):
    id: str
    title: str
    status: str
    runtime_kind: str
    turn_count: int
    active_turn_id: str = ""
    active_turn_status: str = ""
    items: list[dict] = []
    last_message_preview: str = ""
    created_at: str = ""
    updated_at: str = ""


class V2RuntimeItem(BaseModel):
    kind: str
    status: str = "unknown"
    active_turns: int = 0
    worker_count: int = 0


class V2RuntimeListResponse(BaseModel):
    runtimes: list[V2RuntimeItem]


@router.get("/api/v2/threads", response_model=V2ThreadListResponse)
async def v2_list_threads(limit: int = Query(50, ge=1, le=200, description="Max threads")):
    """List all V2 threads for the default server session."""
    server_id = await v2_compat.ensure_default_server_session()
    items = await build_thread_list(server_id, limit=limit)
    return V2ThreadListResponse(
        threads=[
            V2ThreadListItem(
                id=t.id,
                title=t.title,
                status=t.status,
                runtime_kind=t.runtime_kind,
                turn_count=t.turn_count,
                last_message_preview=t.last_message_preview,
                created_at=t.created_at,
                updated_at=t.updated_at,
                is_active=t.is_active,
            )
            for t in items
        ]
    )


@router.get("/api/v2/threads/{thread_id}", response_model=V2ThreadDetailResponse)
async def v2_get_thread(thread_id: str):
    """Get a V2 thread by ID with full detail (items, turn state)."""
    projection = await build_thread_projection(thread_id, include_items=True)
    if projection is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found")
    return V2ThreadDetailResponse(
        id=projection.id,
        title=projection.title,
        status=projection.status,
        runtime_kind=projection.runtime_kind,
        turn_count=projection.turn_count,
        active_turn_id=projection.active_turn_id,
        active_turn_status=projection.active_turn_status,
        items=projection.items,
        last_message_preview=projection.last_message_preview,
        created_at=projection.created_at,
        updated_at=projection.updated_at,
    )


@router.get("/api/v2/runtimes", response_model=V2RuntimeListResponse)
async def v2_list_runtimes():
    """List available V2 runtime kinds and their status."""
    runtimes: list[V2RuntimeItem] = []
    if _worker_pool is not None:
        workers = _worker_pool.list_workers()
        seen: set[str] = set()
        for w in workers:
            kind = w.get("kind", "unknown")
            if kind not in seen:
                seen.add(kind)
                runtimes.append(V2RuntimeItem(
                    kind=kind,
                    status=w.get("status", "idle"),
                    active_turns=w.get("active_turns", 0),
                    worker_count=1,
                ))
    if not runtimes:
        runtimes.append(V2RuntimeItem(kind="unknown", status="unavailable"))
    return V2RuntimeListResponse(runtimes=runtimes)
