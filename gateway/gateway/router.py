"""REST API routes for the Agent Gateway."""

from fastapi import APIRouter, HTTPException, Query

from gateway import database as db
from gateway.models import (
    AgentsResponse,
    HealthResponse,
    HistoryResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@router.get("/chat/agents", response_model=AgentsResponse)
async def list_agents():
    agents = await db.get_agents()
    return AgentsResponse(agents=agents)


@router.get("/chat/history", response_model=HistoryResponse)
async def chat_history(
    agent: str = Query("default", description="Agent ID"),
    limit: int = Query(50, ge=1, le=200, description="Max messages"),
):
    agents = await db.get_agents()
    agent_ids = {a.id for a in agents}
    if agent not in agent_ids:
        raise HTTPException(status_code=404, detail=f"Agent '{agent}' not found")

    messages = await db.get_history(agent_id=agent, limit=limit)
    return HistoryResponse(messages=messages)
