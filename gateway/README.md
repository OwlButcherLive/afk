# AFK Agent Gateway

Minimal local FastAPI backend that the AFK Android app talks to through an SSH tunnel.

## Directory Structure

```
gateway/
├── gateway/                    # Python package
│   ├── main.py                 # FastAPI app entry point
│   ├── models.py               # Pydantic schemas (REST + WebSocket)
│   ├── database.py             # SQLite persistence layer
│   ├── router.py               # REST endpoints
│   └── ws_handler.py           # WebSocket chat handler
├── tests/
│   └── test_gateway.py         # End-to-end REST + WS tests
├── deploy/
│   └── agent-gateway.service   # systemd unit file
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

## Verify

```bash
curl http://127.0.0.1:3344/health
curl http://127.0.0.1:3344/chat/agents
curl "http://127.0.0.1:3344/chat/history?agent=default&limit=10"
```

## Run Tests

```bash
cd gateway
./venv/bin/python tests/test_gateway.py
```

## systemd Installation

```bash
sudo cp gateway/deploy/agent-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable agent-gateway
sudo systemctl start agent-gateway
journalctl -u agent-gateway -f
```

**Note:** The service file expects the gateway at `/srv/agent-gateway/`. Adjust paths in the service file if deploying from a different location.

## API Contract

### REST

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check → `{"status": "ok"}` |
| GET | `/chat/agents` | List available agents |
| GET | `/chat/history?agent=default&limit=50` | Message history |

### WebSocket

`ws://127.0.0.1:3344/ws/chat`

**Send:**
```json
{"type": "message", "agent_id": "default", "text": "hello"}
```

**Receive events:** `message`, `typing`, `error`, `agent_status`

## Default Agent

A single stub agent (`default`) is auto-created on first run. It echoes messages with deterministic responses — enough to validate end-to-end transport from the AFK Android app.

## Data

SQLite database at `gateway/gateway.db` (auto-created on startup).
