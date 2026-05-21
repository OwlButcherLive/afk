"""Agent Gateway — minimal FastAPI backend for AFK.

Runs on localhost (127.0.0.1) and is reached by the AFK Android app
through an SSH local port forwarding tunnel.

Usage:
    uvicorn gateway.main:app --host 127.0.0.1 --port 3344

Or via systemd (see deploy/agent-gateway.service).
"""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from gateway import database as db
from gateway.hermes_manager import HermesManager
from gateway.router import router, set_hermes_manager as router_set_hermes
from gateway.v2 import database as v2db
from gateway.ws_handler import handle_chat_ws, set_hermes_manager as ws_set_hermes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, clean up on shutdown."""
    logger.info("Initializing database...")
    db.init_db()
    v2db.init_v2_schema()
    logger.info("Database ready.")

    # Initialize Hermes Agent manager
    hermes = HermesManager()
    await hermes.initialize()
    router_set_hermes(hermes)
    ws_set_hermes(hermes)
    logger.info("Hermes Agent manager initialized.")

    yield

    # Shutdown
    await hermes.cleanup()
    logger.info("Gateway shutting down.")


app = FastAPI(
    title="AFK Agent Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: allow localhost origins for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
app.include_router(router)


# WebSocket endpoint
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await handle_chat_ws(websocket)
