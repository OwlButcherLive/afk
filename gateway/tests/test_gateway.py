#!/usr/bin/env python3
"""End-to-end test: REST + WebSocket for the Agent Gateway.

Run from the gateway/ directory:
    cd afk/gateway
    pip install -r requirements.txt
    python -m uvicorn gateway.main:app --host 127.0.0.1 --port 3344 &
    python tests/test_gateway.py
"""

import asyncio
import json
import sys
import urllib.request
import urllib.error

import pytest

BASE = "http://127.0.0.1:3344"

# Create a session once for WS tests
def _create_default_session() -> str:
    """Create a session and return its ID."""
    req = urllib.request.Request(
        f"{BASE}/chat/sessions",
        data=json.dumps({"agent_id": "default"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    return data["id"]


def test_rest():
    print("--- REST tests ---")

    # Health
    resp = urllib.request.urlopen(f"{BASE}/health")
    data = json.loads(resp.read())
    assert data == {"status": "ok"}, f"Health failed: {data}"
    print("  ✅ GET /health")

    # Agents
    resp = urllib.request.urlopen(f"{BASE}/chat/agents")
    data = json.loads(resp.read())
    assert "agents" in data
    assert data["agents"][0]["id"] == "default"
    print("  ✅ GET /chat/agents")

    # History (empty)
    resp = urllib.request.urlopen(f"{BASE}/chat/history?agent=default&limit=10")
    data = json.loads(resp.read())
    assert data == {"messages": []}, f"History not empty: {data}"
    print("  ✅ GET /chat/history (empty)")

    # Agent not found
    try:
        urllib.request.urlopen(f"{BASE}/chat/history?agent=nonexistent")
        assert False, "Should have raised 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
        print("  ✅ GET /chat/history (404 for unknown agent)")

    # Sessions
    resp = urllib.request.urlopen(f"{BASE}/chat/sessions")
    data = json.loads(resp.read())
    assert "sessions" in data
    assert len(data["sessions"]) >= 1
    print("  ✅ GET /chat/sessions")

    # Create session
    sess_id = _create_default_session()
    assert sess_id.startswith("sess_")
    print("  ✅ POST /chat/sessions (created)")

    # Get session by ID
    resp = urllib.request.urlopen(f"{BASE}/chat/sessions/{sess_id}")
    data = json.loads(resp.read())
    assert data["id"] == sess_id
    assert data["agent_id"] == "default"
    print("  ✅ GET /chat/sessions/{id}")

    # History by session (should be empty for new session)
    resp = urllib.request.urlopen(f"{BASE}/chat/history?session={sess_id}&limit=10")
    data = json.loads(resp.read())
    assert data == {"messages": []}, f"Session history not empty: {data}"
    print("  ✅ GET /chat/history?session= (empty)")

    print("  ✅ All REST tests passed")


@pytest.mark.asyncio
async def test_ws():
    print("\n--- WebSocket tests ---")
    try:
        import websockets
    except ImportError:
        print("  ⚠️  websockets module not installed, skipping WS tests")
        return

    uri = "ws://127.0.0.1:3344/ws/chat"

    async with websockets.connect(uri) as ws:
        # 1. Initial agent_status
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        event = json.loads(raw)
        assert event["type"] == "agent_status"
        assert event["agent_id"] == "default"
        assert event["status"] == "online"
        print("  ✅ Initial agent_status event")

        # Create a session for WS test
        sess_id = _create_default_session()
        print(f"  📋 Using session: {sess_id}")

        # 2. Send a message with session_id
        await ws.send(json.dumps({
            "type": "message",
            "session_id": sess_id,
            "agent_id": "default",
            "text": "hello"
        }))

        # Collect responses (user echo, typing on, typing off, agent reply)
        events = []
        for _ in range(4):
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            events.append(json.loads(raw))

        # Response 0: user message echo
        assert events[0]["type"] == "message"
        assert events[0]["role"] == "user"
        assert events[0]["text"] == "hello"
        print("  ✅ User message persisted and echoed")

        # Response 1: typing on
        assert events[1]["type"] == "typing"
        assert events[1]["is_typing"] is True
        print("  ✅ Typing indicator sent")

        # Response 2: typing off
        assert events[2]["type"] == "typing"
        assert events[2]["is_typing"] is False
        print("  ✅ Typing stopped")

        # Response 3: agent reply
        assert events[3]["type"] == "message"
        assert events[3]["role"] == "agent"
        assert "Hello" in events[3]["text"]
        print(f"  ✅ Agent reply received: \"{events[3]['text']}\"")

        # 3. Verify history now has 2 messages (via session)
        resp = urllib.request.urlopen(f"{BASE}/chat/history?session={sess_id}&limit=10")
        data = json.loads(resp.read())
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "agent"
        print("  ✅ History updated with 2 messages")

        print("\n  ✅ All WebSocket tests passed")


def test_agent_selection():
    """Verify agent list contains both default and hermes-agent."""
    print("\n--- Agent selection tests ---")

    resp = urllib.request.urlopen(f"{BASE}/chat/agents")
    data = json.loads(resp.read())
    agent_ids = {a["id"] for a in data["agents"]}

    assert "default" in agent_ids, "Default agent missing"
    assert "hermes-agent" in agent_ids, "Hermes agent missing"
    print(f"  ✅ Agents found: {', '.join(sorted(agent_ids))}")

    # Verify hermes-agent has the right name
    hermes = [a for a in data["agents"] if a["id"] == "hermes-agent"][0]
    assert "Hermes" in hermes["name"], f"Unexpected name: {hermes['name']}"
    print(f"  ✅ Hermes agent name: {hermes['name']}")

    print("  ✅ All agent selection tests passed")


def test_hermes_status_endpoint():
    """Verify the hermes status endpoint returns expected fields."""
    print("\n--- Hermes status endpoint tests ---")

    resp = urllib.request.urlopen(f"{BASE}/agents/hermes-agent/status")
    data = json.loads(resp.read())

    assert "available" in data
    assert "executable_path" in data
    assert "candidates_checked" in data
    assert "usable" in data
    assert "usable_reason" in data
    assert "version" in data

    print(f"  ✅ available: {data['available']}")
    print(f"  ✅ executable_path: {data['executable_path']}")
    print(f"  ✅ candidates_checked: {data['candidates_checked']}")
    print(f"  ✅ usable: {data['usable']}")
    print(f"  ✅ usable_reason: {data['usable_reason']}")
    print(f"  ✅ version: {data['version']}")
    print("  ✅ All hermes status tests passed")


def test_create_session_with_hermes():
    """Verify sessions can be created for hermes-agent."""
    print("\n--- Hermes session creation tests ---")

    sess_id = _create_session_for_agent("hermes-agent")
    assert sess_id.startswith("sess_"), f"Bad session ID: {sess_id}"
    print(f"  ✅ Created session: {sess_id}")

    # Verify session has correct agent_id
    resp = urllib.request.urlopen(f"{BASE}/chat/sessions/{sess_id}")
    data = json.loads(resp.read())
    assert data["agent_id"] == "hermes-agent", f"Wrong agent: {data['agent_id']}"
    print(f"  ✅ Session agent_id: {data['agent_id']}")

    print("  ✅ All hermes session tests passed")


def test_unknown_agent_rejected():
    """Verify creating a session with unknown agent returns 404."""
    print("\n--- Unknown agent rejection tests ---")

    req = urllib.request.Request(
        f"{BASE}/chat/sessions",
        data=json.dumps({"agent_id": "nonexistent-agent"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        assert False, "Should have raised 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404
        print(f"  ✅ Unknown agent correctly rejected (404)")


def _create_session_for_agent(agent_id: str) -> str:
    """Create a session for the given agent and return its ID."""
    req = urllib.request.Request(
        f"{BASE}/chat/sessions",
        data=json.dumps({"agent_id": agent_id}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["id"]


if __name__ == "__main__":
    import sys

    test_rest()
    test_agent_selection()
    test_hermes_status_endpoint()
    test_create_session_with_hermes()
    test_unknown_agent_rejected()

    asyncio.run(test_ws())

    print("\n✅✅✅ ALL TESTS PASSED ✅✅✅")
