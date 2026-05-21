"""REST API routes for the Agent Gateway."""

import logging

from fastapi import APIRouter, HTTPException, Query

from gateway import database as db
from gateway.hermes_manager import HermesManager
from gateway.models import (
    AgentsResponse,
    CreateSessionRequest,
    HealthResponse,
    HermesStatusResponse,
    HistoryResponse,
    SessionResponse,
    SessionsListResponse,
)

logger = logging.getLogger("gateway.router")

router = APIRouter()

# HermesManager is set during lifespan in main.py
_hermes_manager: HermesManager | None = None


def set_hermes_manager(hm: HermesManager) -> None:
    global _hermes_manager
    _hermes_manager = hm


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@router.get("/chat/agents", response_model=AgentsResponse)
async def list_agents():
    agents = await db.get_agents()
    return AgentsResponse(agents=agents)


@router.get("/chat/history", response_model=HistoryResponse)
async def chat_history(
    session: str | None = Query(None, description="Session ID"),
    agent: str | None = Query("default", description="Agent ID (fallback if no session)"),
    limit: int = Query(50, ge=1, le=200, description="Max messages"),
):
    if session:
        sess = await db.get_session(session)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"Session '{session}' not found")
        messages = await db.get_history(session_id=session, limit=limit)
    else:
        agents = await db.get_agents()
        agent_ids = {a.id for a in agents}
        if agent not in agent_ids:
            raise HTTPException(status_code=404, detail=f"Agent '{agent}' not found")
        messages = await db.get_history(agent_id=agent, limit=limit)
    return HistoryResponse(messages=messages)


# ─── Session endpoints ───────────────────────────────────────────────────────


@router.get("/chat/sessions", response_model=SessionsListResponse)
async def list_sessions():
    sessions = await db.get_sessions()
    return SessionsListResponse(sessions=sessions)


@router.post("/chat/sessions", response_model=SessionResponse, status_code=201)
async def create_session(req: CreateSessionRequest):
    agent = await db.get_agent(req.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' not found")
    session = await db.create_session(req.agent_id)
    return SessionResponse(
        id=session.id,
        agent_id=session.agent_id,
        title=session.title,
        updated_at=session.updated_at,
    )


@router.get("/chat/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    session = await db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionResponse(
        id=session.id,
        agent_id=session.agent_id,
        title=session.title,
        updated_at=session.updated_at,
    )


# ─── Hermes Agent status ────────────────────────────────────────────────────


@router.get("/agents/hermes-agent/status", response_model=HermesStatusResponse)
async def hermes_status():
    if _hermes_manager is None:
        logger.warning("Hermes status queried but manager not initialized")
        return HermesStatusResponse(
            available=False,
            error="Hermes manager not initialized",
            usable=False,
            usable_reason="HermesManager was never initialized during gateway startup",
        )
    status = await _hermes_manager.get_status()
    logger.info(
        "Hermes status queried — available=%s, executable=%s, version=%s, usable=%s",
        status.available, status.executable_path,
        status.version, status.usable,
    )
    return HermesStatusResponse(
        available=status.available,
        version=status.version,
        busy=status.busy,
        error=status.error,
        executable_path=status.executable_path,
        candidates_checked=status.candidates_checked,
        usable=status.usable,
        usable_reason=status.usable_reason,
    )
