"""AFK V2 — server-side architecture for session runtime and thread engine.

V2 transforms the gateway from a message-centric dispatcher to a
stateful session runtime system. Key modules:

  models.py       — domain primitives (ServerSession, Thread, Turn, ThreadItem)
  database.py     — schema evolution (7 new tables, version tracking)
  thread_store.py — Thread/Turn/ThreadItem persistence
  session_store.py — ServerSession persistence
  thread_engine.py — Thread lifecycle operations (start, resume, read, archive)
  runtime.py      — AgentRuntime ABC + HermesRuntime (returns structured ThreadItems)
  worker.py       — WorkerPool + RuntimeWorker (command channel pattern)
  health.py       — HealthMonitor (Disconnected→Connecting→Connected→Unresponsive)
  events.py       — Event streaming models (snapshot, update, delta)
  projection.py   — Thread projection layer (mobile-friendly snapshots)
  requests.py     — Request correlation (request_id tracking, cleanup)
  compat.py       — V1→V2 compatibility bridge (WorkerPool dispatch, WS response mapping)
"""
