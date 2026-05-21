"""Connection health monitoring for AFK V2.

Provides the first proper connection health state model:
  - Disconnected
  - Connecting
  - Connected
  - Unresponsive

HealthMonitor tracks heartbeats and detects stale connections.
Full reconnection logic is not implemented yet — the architecture
and hooks are in place for future milestones.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from gateway.v2.models import ConnectionHealth

logger = logging.getLogger("gateway.v2.health")


# ─── Extended health states ─────────────────────────────────────────────────


class HealthState(str, Enum):
    """Extended connection health states for the monitoring system.

    Maps to the simpler ConnectionHealth model for persistence:
      Disconnected -> disconnected
      Connecting   -> disconnected  (transitional)
      Connected    -> connected
      Unresponsive -> degraded
    """
    Disconnected = "disconnected"
    Connecting = "connecting"
    Connected = "connected"
    Unresponsive = "unresponsive"

    def to_connection_health(self) -> ConnectionHealth:
        mapping = {
            HealthState.Disconnected: ConnectionHealth.disconnected,
            HealthState.Connecting: ConnectionHealth.disconnected,
            HealthState.Connected: ConnectionHealth.connected,
            HealthState.Unresponsive: ConnectionHealth.degraded,
        }
        return mapping[self]


# ─── Health Monitor ─────────────────────────────────────────────────────────


@dataclass
class SessionHealthRecord:
    """Health tracking data for one server session."""
    session_id: str
    state: HealthState = HealthState.Disconnected
    last_heartbeat: float = 0.0  # time.monotonic()
    last_seen_ago: float = 0.0
    missed_heartbeats: int = 0
    connected_at: float = 0.0
    disconnects: int = 0


_HEARTBEAT_TIMEOUT = 60.0   # seconds without heartbeat -> Unresponsive
_UNRESPONSIVE_TIMEOUT = 300.0  # seconds Unresponsive -> Disconnected
_CHECK_INTERVAL = 15.0      # how often to check for stale connections


class HealthMonitor:
    """Monitors connection health for all server sessions.

    Detects stale connections and transitions health states.
    Does NOT implement reconnection — that's a future milestone.
    """

    def __init__(self):
        self._sessions: dict[str, SessionHealthRecord] = {}
        self._check_task: asyncio.Task | None = None
        self._on_state_change = None  # callback: (session_id, old_state, new_state) -> None

    def set_state_change_callback(self, callback) -> None:
        """Set a callback fired on health state transitions."""
        self._on_state_change = callback

    def register_session(self, session_id: str) -> SessionHealthRecord:
        """Register a new session for health tracking."""
        record = SessionHealthRecord(session_id=session_id)
        self._sessions[session_id] = record
        logger.debug("Health monitor: registered session=%s", session_id)
        return record

    def unregister_session(self, session_id: str) -> None:
        """Remove a session from health tracking."""
        self._sessions.pop(session_id, None)
        logger.debug("Health monitor: unregistered session=%s", session_id)

    def mark_connected(self, session_id: str) -> None:
        """Mark a session as connected."""
        import time
        record = self._sessions.get(session_id)
        if record is None:
            record = self.register_session(session_id)
        old = record.state
        record.state = HealthState.Connected
        record.last_heartbeat = time.monotonic()
        record.missed_heartbeats = 0
        if record.connected_at == 0:
            record.connected_at = time.monotonic()
        self._fire_change(session_id, old, record.state)

    def mark_connecting(self, session_id: str) -> None:
        """Mark a session as connecting."""
        record = self._sessions.get(session_id)
        if record is None:
            record = self.register_session(session_id)
        old = record.state
        record.state = HealthState.Connecting
        self._fire_change(session_id, old, record.state)

    def mark_disconnected(self, session_id: str) -> None:
        """Mark a session as disconnected."""
        record = self._sessions.get(session_id)
        if record is None:
            return
        old = record.state
        record.state = HealthState.Disconnected
        record.disconnects += 1
        self._fire_change(session_id, old, record.state)

    def heartbeat(self, session_id: str) -> None:
        """Record a heartbeat from a session."""
        import time
        record = self._sessions.get(session_id)
        if record is None:
            record = self.register_session(session_id)
        record.last_heartbeat = time.monotonic()
        record.missed_heartbeats = 0
        if record.state == HealthState.Unresponsive:
            old = record.state
            record.state = HealthState.Connected
            self._fire_change(session_id, old, record.state)

    def get_health(self, session_id: str) -> HealthState | None:
        """Get the current health state of a session."""
        record = self._sessions.get(session_id)
        return record.state if record else None

    def get_all_health(self) -> dict[str, HealthState]:
        """Get health states for all sessions."""
        return {sid: r.state for sid, r in self._sessions.items()}

    def _fire_change(self, session_id: str, old: HealthState, new: HealthState) -> None:
        if old != new and self._on_state_change:
            try:
                self._on_state_change(session_id, old, new)
            except Exception as e:
                logger.warning("Health state change callback failed: %s", e)

    async def start_monitoring(self) -> None:
        """Start the periodic health check loop."""
        if self._check_task:
            return
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info("Health monitor started (interval=%ds)", _CHECK_INTERVAL)

    async def stop_monitoring(self) -> None:
        """Stop the health check loop."""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None
        logger.info("Health monitor stopped")

    async def _check_loop(self) -> None:
        """Periodically check for stale connections."""
        import time
        try:
            while True:
                await asyncio.sleep(_CHECK_INTERVAL)
                now = time.monotonic()
                for sid, record in list(self._sessions.items()):
                    if record.state == HealthState.Connected:
                        if now - record.last_heartbeat > _HEARTBEAT_TIMEOUT:
                            old = record.state
                            record.state = HealthState.Unresponsive
                            record.missed_heartbeats += 1
                            self._fire_change(sid, old, record.state)
                            logger.warning(
                                "Session unresponsive: id=%s last_heartbeat=%.0fs ago",
                                sid, now - record.last_heartbeat,
                            )
                    elif record.state == HealthState.Unresponsive:
                        if now - record.last_heartbeat > _UNRESPONSIVE_TIMEOUT:
                            old = record.state
                            record.state = HealthState.Disconnected
                            self._fire_change(sid, old, record.state)
                            logger.warning(
                                "Session disconnected (timeout): id=%s", sid,
                            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Health check loop error: %s", e)
