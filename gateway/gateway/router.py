"""REST router for the Agent Gateway.

Endpoints are gradually migrating from V1 DB to V2 compat:
  GET /chat/sessions  — V2 compat (with V1 DB fallback for unmapped sessions)
  GET /chat/history   — V2 compat (via V2 thread items)
  POST /chat/sessions — V1 DB + eager V2 thread mapping
  GET /chat/agents    — V1 DB (agents are stable)
  GET /health         — no change
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from gateway import database as db
from gateway.hermes_manager import HermesManager
from gateway.v2 import compat as v2_compat

logger = logging.getLogger("gateway.router")

router = APIRouter()

# Set during lifespan in main.py
_hermes_manager: HermesManager | None = None


def set_hermes_manager(hm: HermesManager) -> None:
    global _hermes_manager
    _hermes_manager = hm


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
    """Get chat history. Reads from V2 via compat bridge.

    If the session exists in V2 compat, reads from V2 thread items.
    Otherwise falls back to V1 DB for backward compatibility.
    """
    if session:
        # Try V2 compat first
        v2_messages = await v2_compat.get_v1_history(session)
        if v2_messages:
            return HistoryResponse(messages=[V1MessageItem(**m) for m in v2_messages])

        # Fallback: check V1 DB
        sess = await db.get_session(session)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{session}' not found")
        v1_messages = await db.get_history(session_id=session, limit=limit)
        return HistoryResponse(messages=[
            V1MessageItem(id=m.id, agent_id=m.agent_id, role=m.role.value,
                          text=m.text, timestamp=m.timestamp)
            for m in v1_messages
        ])
    else:
        # Fallback: V1 DB by agent
        v1_agent = agent or "default"
        all_agents = await db.get_agents()
        agent_ids = {a.id for a in all_agents}
        if v1_agent not in agent_ids:
            raise HTTPException(status_code=404, detail=f"Agent '{v1_agent}' not found")
        v1_messages = await db.get_history(agent_id=v1_agent, limit=limit)
        return HistoryResponse(messages=[
            V1MessageItem(id=m.id, agent_id=m.agent_id, role=m.role.value,
                          text=m.text, timestamp=m.timestamp)
            for m in v1_messages
        ])


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
    """Get a single session by ID. Reads from V1 DB for now."""
    session = await db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionResponse(
        id=session.id,
        agent_id=session.agent_id,
        title=session.title,
        updated_at=session.updated_at,
    )


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
