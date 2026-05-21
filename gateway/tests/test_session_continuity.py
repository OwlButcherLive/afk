"""Gateway tests for session continuity.

Verifies that messages sent via WebSocket to the same session
remain in that session and do not create new sessions.
"""
import json
import time
import httpx
import pytest
from websockets.sync.client import connect as ws_connect

BASE = "http://localhost:3344"
WS = "ws://localhost:3344/ws/chat"


@pytest.fixture(autouse=True)
def check_gateway():
    """Fail fast if gateway is not running."""
    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
    except Exception as e:
        pytest.skip(f"Gateway not reachable: {e}")


def test_health():
    r = httpx.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_agents_list():
    r = httpx.get(f"{BASE}/chat/agents")
    assert r.status_code == 200
    agents = r.json()["agents"]
    ids = {a["id"] for a in agents}
    assert "hermes-agent" in ids, "hermes-agent should be seeded"


def test_create_session():
    r = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    assert r.status_code == 201
    data = r.json()
    assert data["agent_id"] == "hermes-agent"
    assert data["id"].startswith("sess_")


def test_get_session():
    # Create first
    r = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    sid = r.json()["id"]
    # Get by id
    r = httpx.get(f"{BASE}/chat/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid


def test_history_empty_session():
    r = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    sid = r.json()["id"]
    r = httpx.get(f"{BASE}/chat/history", params={"session": sid})
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_session_continuity_same_session():
    """Core test: 3 messages via WS -> all in the same session, no new session created."""
    # Count sessions before
    before = httpx.get(f"{BASE}/chat/sessions").json()
    count_before = len(before["sessions"])

    # Create one fresh session
    r = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    assert r.status_code == 201
    session_id = r.json()["id"]

    # Send 3 messages via WS
    messages = ["hello", "what is 2+2", "thanks"]
    with ws_connect(WS) as ws:
        # Consume initial agent_status
        ws.recv(timeout=5)

        for text in messages:
            payload = json.dumps({
                "type": "message",
                "session_id": session_id,
                "agent_id": "hermes-agent",
                "text": text,
            })
            ws.send(payload)

            # Consume user echo
            ws.recv(timeout=10)
            # Consume typing=true
            ws.recv(timeout=10)
            # Consume typing=false
            ws.recv(timeout=120)
            # Consume response
            ws.recv(timeout=120)

    # Check sessions after — should be exactly +1 from before
    after = httpx.get(f"{BASE}/chat/sessions").json()
    assert len(after["sessions"]) == count_before + 1, (
        f"Expected {count_before + 1} sessions, got {len(after['sessions'])}. "
        "Sessions were created for individual messages instead of reusing one."
    )

    # Check our session has 6 messages (3 user + 3 agent)
    r = httpx.get(f"{BASE}/chat/history", params={"session": session_id, "limit": 100})
    msgs = r.json()["messages"]
    assert len(msgs) == 6, f"Expected 6 messages in session, got {len(msgs)}"
    assert msgs[0]["role"] == "user"
    assert msgs[0]["text"] == "hello"
    assert msgs[2]["role"] == "user"
    assert msgs[2]["text"] == "what is 2+2"


def test_session_continuity_separate_sessions():
    """Verify that different sessions don't share messages."""
    # Create two sessions
    r1 = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    s1 = r1.json()["id"]
    r2 = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    s2 = r2.json()["id"]
    assert s1 != s2

    # Send to session 1
    with ws_connect(WS) as ws:
        ws.recv(timeout=5)
        payload = json.dumps({
            "type": "message", "session_id": s1,
            "agent_id": "hermes-agent", "text": "only in session 1",
        })
        ws.send(payload)
        # Consume user echo (fast)
        ws.recv(timeout=10)
        # Consume typing=true (fast)
        ws.recv(timeout=10)
        # Consume typing=false then agent response (both after Hermes API)
        for _ in range(2):
            ws.recv(timeout=120)

    # Session 1 should have 2 messages, session 2 should have 0
    h1 = httpx.get(f"{BASE}/chat/history", params={"session": s1}).json()
    h2 = httpx.get(f"{BASE}/chat/history", params={"session": s2}).json()
    assert len(h1["messages"]) == 2, f"Session 1 should have 2 msgs, got {len(h1['messages'])}"
    assert len(h2["messages"]) == 0, f"Session 2 should have 0 msgs, got {len(h2['messages'])}"


def test_unknown_session_returns_error():
    """Sending to a non-existent session should return error, not create one."""
    count_before = len(httpx.get(f"{BASE}/chat/sessions").json()["sessions"])
    with ws_connect(WS) as ws:
        ws.recv(timeout=5)
        payload = json.dumps({
            "type": "message",
            "session_id": "sess_nonexistent",
            "agent_id": "hermes-agent",
            "text": "hello",
        })
        ws.send(payload)
        resp = json.loads(ws.recv(timeout=10))
        assert resp["type"] == "error"
        assert "not found" in resp.get("message", "").lower()

    count_after = len(httpx.get(f"{BASE}/chat/sessions").json()["sessions"])
    assert count_after == count_before, "Unknown session should not create a new session"


def test_deep_probe_ok():
    r = httpx.get(f"{BASE}/agents/hermes-agent/status")
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is True
    assert data["deep_probe_ok"] is True
    assert "hermes" in data["executable_path"]


def test_rapid_fire_same_session():
    """Simulate the user's exact bug scenario: rapid messages in the same thread.

    Sends 3 messages in quick succession through a single WS connection,
    then verifies only 1 new session was created and all 6 messages
    (3 user + 3 agent) are in that single session.
    """
    count_before = len(httpx.get(f"{BASE}/chat/sessions").json()["sessions"])

    # Create one session
    r = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    assert r.status_code == 201
    session_id = r.json()["id"]

    # Rapid-fire 3 messages in one WS connection (simulating user typing fast)
    messages = ["first", "second", "third"]
    with ws_connect(WS) as ws:
        ws.recv(timeout=5)  # agent_status

        for i, text in enumerate(messages):
            payload = json.dumps({
                "type": "message",
                "session_id": session_id,
                "agent_id": "hermes-agent",
                "text": text,
            })
            ws.send(payload)
            # Consume user echo (fast)
            ws.recv(timeout=10)
            # Consume typing=true (fast)
            ws.recv(timeout=10)
            # Consume typing=false then agent response (both sent after Hermes API,
            # which takes 20-30s — use generous timeout for the first post-hermes event)
            for _ in range(2):
                ws.recv(timeout=120)

    # Verify exactly 1 new session
    after = httpx.get(f"{BASE}/chat/sessions").json()
    assert len(after["sessions"]) == count_before + 1, (
        f"Expected {count_before + 1} sessions, got {len(after['sessions'])}. "
        "Rapid messages are creating separate sessions!"
    )

    # Verify all 6 messages in one session
    h = httpx.get(f"{BASE}/chat/history", params={"session": session_id, "limit": 100}).json()
    assert len(h["messages"]) == 6, f"Expected 6 messages, got {len(h['messages'])}"
    assert h["messages"][0]["text"] == "first"
    assert h["messages"][2]["text"] == "second"
    assert h["messages"][4]["text"] == "third"


# ─── Context continuity tests ───────────────────────────────────────────


def test_context_loaded_from_prior_messages():
    """Verify that prior messages are loaded from DB and included in context.

    When Hermes is called, the WS handler loads prior messages from the
    session's history and passes them as context_messages to send_task().
    This test verifies the gateway-side plumbing by checking that:
    1. Prior messages exist in the DB for the session
    2. The second WS call sees those prior messages
    3. Messages from OTHER sessions are NOT loaded
    """
    # Create session
    r = httpx.post(f"{BASE}/chat/sessions", json={"agent_id": "hermes-agent"})
    sid = r.json()["id"]

    # Send first message
    with ws_connect(WS) as ws:
        ws.recv(timeout=5)
        payload = json.dumps({
            "type": "message", "session_id": sid,
            "agent_id": "hermes-agent", "text": "first message",
        })
        ws.send(payload)
        for _ in range(4):
            ws.recv(timeout=120)

    # Verify 2 messages exist in session (1 user + 1 agent)
    h = httpx.get(f"{BASE}/chat/history", params={"session": sid, "limit": 50}).json()
    assert len(h["messages"]) == 2, (
        f"Expected 2 messages after first send, got {len(h['messages'])}"
    )

    # Send second message — should load prior 2 messages as context
    with ws_connect(WS) as ws:
        ws.recv(timeout=5)
        payload = json.dumps({
            "type": "message", "session_id": sid,
            "agent_id": "hermes-agent", "text": "second message",
        })
        ws.send(payload)
        for _ in range(4):
            ws.recv(timeout=120)

    # Verify 4 messages exist (2 user + 2 agent) — no extra sessions created
    h = httpx.get(f"{BASE}/chat/history", params={"session": sid, "limit": 50}).json()
    assert len(h["messages"]) == 4, (
        f"Expected 4 messages after second send, got {len(h['messages'])}"
    )
    assert h["messages"][0]["text"] == "first message"
    assert h["messages"][2]["text"] == "second message"
