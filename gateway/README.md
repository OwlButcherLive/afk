# AFK Agent Gateway

Minimal local FastAPI backend that the AFK Android app talks to through an SSH tunnel.

Runs on the Debian host behind a forwarded SSH port (~/.local/bin/hermes chatbot via subprocess).

## Directory Structure

```
gateway/
├── gateway/                    # Python package
│   ├── main.py                 # FastAPI app entry point (uvicorn)
│   ├── models.py               # Pydantic schemas (REST + WebSocket)
│   ├── database.py             # SQLite persistence (aiosqlite)
│   ├── router.py               # REST endpoints
│   ├── ws_handler.py           # WebSocket chat handler
│   └── hermes_manager.py       # Hermes CLI subprocess adapter
├── requirements.txt
└── README.md
```

## Quick Start

```bash
cd gateway
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
rm -f gateway.db  # fresh database
./venv/bin/python -m uvicorn gateway.main:app --host 127.0.0.1 --port 3344 --reload
```

On first startup, the DB is seeded with two agents:
- `default` — stub agent with deterministic replies (for transport validation)
- `hermes-agent` — routes to the real Hermes CLI via subprocess

## Verify

```bash
# Health
curl http://127.0.0.1:3344/health

# List agents
curl http://127.0.0.1:3344/chat/agents

# Hermes status (deep probe, executable path, version)
curl http://127.0.0.1:3344/agents/hermes-agent/status

# Sessions
curl http://127.0.0.1:3344/chat/sessions

# Create session
curl -X POST http://127.0.0.1:3344/chat/sessions \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "hermes-agent"}'
```

## Run Tests

```bash
cd gateway
./venv/bin/python -m pytest tests/test_gateway.py -v
```

## systemd Installation

```bash
sudo cp deploy/agent-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable agent-gateway
sudo systemctl start agent-gateway
journalctl -u agent-gateway -f
```

**Note:** The service file expects the gateway at `/srv/agent-gateway/`. Adjust paths if deploying from a different location. Use `ProtectHome=read-only` (not `ProtectHome=yes`) because the Hermes CLI lives under `~/.hermes/`.

## API Contract

### REST

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/chat/agents` | List available agents (id, name, status) |
| GET | `/chat/sessions` | List sessions with latest message preview |
| POST | `/chat/sessions` | Create session `{"agent_id": "hermes-agent"}` |
| GET | `/chat/sessions/{id}` | Get session details |
| GET | `/chat/history?session={id}&limit=50` | Message history |
| GET | `/agents/hermes-agent/status` | Hermes CLI readiness (deep probe, executable) |

### WebSocket

`ws://127.0.0.1:3344/ws/chat`

**Send:**
```json
{"type": "message", "session_id": "sess_xxx", "agent_id": "hermes-agent", "text": "hello"}
```

**Receive events:**
- `message` — `{type, id, agent_id, role, text, timestamp}`
- `typing` — `{type, agent_id, is_typing}`
- `error` — `{type, code, message}`
- `agent_status` — `{type, agent_id, status}`

### Agent Routing

The gateway routes WebSocket messages by `agent_id`:

- **`hermes-agent`** (when HermesManager is initialized) → `hermes chat -q` subprocess
- **`hermes-agent`** (when HermesManager is None) → typed error message
- **Any other agent_id** → deterministic stub reply (no real agent)

HermesManager initializes on first status query or WS message. It:
1. Discovers the Hermes CLI binary by checking candidates (PATH, explicit paths)
2. Runs `hermes --version` to verify the executable
3. Runs a deep probe (`hermes chat -q "ping" -Q`) to verify the CLI can produce responses
4. Reports full status including executable path, version, deep_probe_ok, and usable flag

## Hermes Manager

`hermes_manager.py` dispatches user messages as independent `hermes chat -q` subprocess calls.

Key points:
- Stateless per-call (no persistent tmux session for V1)
- 120s timeout per request
- Banner/ANSI stripping via regex
- Augmented env (preserves PATH) with `HERMES_YOLO_MODE=1`
- Concurrency lock per HermesManager instance

## Data

SQLite database at `gateway/gateway.db` (auto-created on startup). Tables:
- `agents` — id, name, status
- `sessions` — id, agent_id, title, updated_at
- `messages` — id, session_id, agent_id, role, text, timestamp

WAL mode enabled for concurrent reads.
