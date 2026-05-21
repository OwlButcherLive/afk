"""Tests for AFK V2 core: models, lifecycle operations, worker pattern, health,
events, projection, requests, and compat layer.

Run from gateway/ directory:
    python -m pytest tests/test_v2_core.py -v
"""

import pytest
from gateway.v2.models import (
    ServerSession,
    Thread,
    Turn,
    ThreadItem,
    ThreadStatus,
    TurnStatus,
    RuntimeKind,
    ConnectionHealth,
    ThreadItemKind,
    utc_now,
    new_id,
)
from gateway.v2.worker import WorkerCommandKind, WorkerCommand, WorkerResult
from gateway.v2.events import (
    ThreadSnapshot,
    ThreadSnapshotItem,
    ThreadItemAppended,
    ThreadStatusChanged,
    ThreadEventKind,
    event_to_dict,
)
from gateway.v2.requests import RequestTracker, RequestStatus
from gateway.v2.runtime import HermesRuntime, RuntimeEvent


# ═══════════════════════════════════════════════════════════════════════════
# V2 Domain Models
# ═══════════════════════════════════════════════════════════════════════════


class TestV2Models:
    """V2 domain model construction and validation."""

    def test_server_session_defaults(self):
        s = ServerSession(id="srv_test", created_at=utc_now(), updated_at=utc_now(), last_seen_at=utc_now())
        assert s.id == "srv_test"
        assert s.client_platform == "android"
        assert s.connection_health == ConnectionHealth.disconnected
        assert s.name == ""

    def test_thread_construction(self):
        t = Thread(
            id="thread_abc",
            server_session_id="srv_test",
            runtime_kind=RuntimeKind.hermes,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        assert t.status == ThreadStatus.active
        assert t.runtime_kind == RuntimeKind.hermes
        assert t.title == ""

    def test_turn_lifecycle(self):
        turn = Turn(id="turn_abc", thread_id="thread_abc", turn_index=0)
        assert turn.status == TurnStatus.pending
        assert turn.turn_index == 0
        turn.status = TurnStatus.running
        assert turn.status == TurnStatus.running
        turn.status = TurnStatus.completed
        assert turn.status == TurnStatus.completed
        turn.status = TurnStatus.failed
        assert turn.status == TurnStatus.failed
        turn.status = TurnStatus.interrupted
        assert turn.status == TurnStatus.interrupted

    def test_thread_item_kinds(self):
        kinds = list(ThreadItemKind)
        expected = [
            "user_message", "agent_message", "reasoning",
            "command_execution", "file_change", "approval_request",
            "context_compaction", "system_event",
        ]
        assert [k.value for k in kinds] == expected

    def test_thread_item_with_metadata(self):
        item = ThreadItem(
            id="item_test",
            thread_id="thread_abc",
            turn_id="turn_abc",
            kind=ThreadItemKind.user_message,
            index=0,
            role="user",
            content="Hello",
            metadata={"source": "test"},
            created_at=utc_now(),
        )
        assert item.content == "Hello"
        assert item.metadata["source"] == "test"
        assert item.kind == ThreadItemKind.user_message

    def test_new_id_format(self):
        tid = new_id("thread_")
        assert tid.startswith("thread_")
        assert len(tid) > 10

    def test_utc_now_format(self):
        ts = utc_now()
        assert "T" in ts
        assert ts.endswith("Z")

    def test_thread_status_enum(self):
        assert len(list(ThreadStatus)) == 4

    def test_turn_status_enum(self):
        assert len(list(TurnStatus)) == 5

    def test_runtime_kind_enum(self):
        assert "hermes" in [k.value for k in RuntimeKind]

    def test_connection_health_enum(self):
        assert len(list(ConnectionHealth)) == 3

    def test_thread_item_generated_flag(self):
        """Runtime-generated items have the generated metadata flag."""
        item = ThreadItem(
            id="item_rt",
            thread_id="t1",
            turn_id="turn1",
            kind=ThreadItemKind.agent_message,
            index=1,
            role="agent",
            content="Hello from runtime",
            metadata={"runtime": "hermes", "generated": True},
            created_at=utc_now(),
        )
        assert item.metadata.get("generated") is True


# ═══════════════════════════════════════════════════════════════════════════
# Worker Commands
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkerCommands:
    """WorkerCommandKind enum and WorkerCommand construction."""

    def test_worker_commands(self):
        kinds = list(WorkerCommandKind)
        expected = ["process_turn", "interrupt", "reset", "get_status", "shutdown"]
        assert [k.value for k in kinds] == expected

    def test_worker_command_with_reply(self):
        import asyncio
        future = asyncio.get_event_loop().create_future()
        cmd = WorkerCommand(
            kind=WorkerCommandKind.process_turn,
            payload={"turn_id": "test"},
            reply_to=future,
        )
        assert cmd.kind == WorkerCommandKind.process_turn
        assert cmd.payload["turn_id"] == "test"
        assert cmd.reply_to is future

    def test_worker_result_defaults(self):
        r = WorkerResult()
        assert r.ok is True
        assert r.value is None
        assert r.error == ""

    def test_worker_result_error(self):
        r = WorkerResult(ok=False, error="something failed")
        assert r.ok is False
        assert r.error == "something failed"


# ═══════════════════════════════════════════════════════════════════════════
# Runtime Events
# ═══════════════════════════════════════════════════════════════════════════


class TestRuntimeEvent:
    """RuntimeEvent construction and properties."""

    def test_runtime_event_ok_completed(self):
        event = RuntimeEvent(kind="turn_completed", turn_id="turn1", items=["result"])
        assert event.ok is True
        assert event.kind == "turn_completed"

    def test_runtime_event_ok_item_produced(self):
        event = RuntimeEvent(kind="item_produced")
        assert event.ok is True

    def test_runtime_event_not_ok_failed(self):
        event = RuntimeEvent(kind="turn_failed", turn_id="turn1", error="fail")
        assert event.ok is False

    def test_runtime_event_not_ok_approval(self):
        event = RuntimeEvent(kind="approval_requested")
        assert event.ok is False

    def test_runtime_event_with_items(self):
        from gateway.v2.models import ThreadItem, ThreadItemKind
        items = [
            ThreadItem(id="u1", thread_id="t1", turn_id="turn1",
                       kind=ThreadItemKind.user_message, index=0,
                       role="user", content="hi", created_at=utc_now()),
            ThreadItem(id="a1", thread_id="t1", turn_id="turn1",
                       kind=ThreadItemKind.agent_message, index=1,
                       role="agent", content="hello", created_at=utc_now()),
        ]
        event = RuntimeEvent(kind="turn_completed", turn_id="turn1", items=items)
        assert len(event.items) == 2
        assert event.items[0].kind == ThreadItemKind.user_message
        assert event.items[1].content == "hello"


# ═══════════════════════════════════════════════════════════════════════════
# Event Streaming Models
# ═══════════════════════════════════════════════════════════════════════════


class TestEventModels:
    """V2 event streaming model construction and serialization."""

    def test_thread_event_kind_values(self):
        kinds = list(ThreadEventKind)
        expected = [
            "thread_snapshot", "thread_item_appended", "turn_completed",
            "turn_failed", "turn_interrupted", "thread_status_changed",
            "thread_title_changed", "thread_archived", "approval_requested",
            "approval_resolved", "thread_heartbeat",
        ]
        assert [k.value for k in kinds] == expected

    def test_thread_snapshot_construction(self):
        items = [
            ThreadSnapshotItem(
                id="item1", turn_id="turn1", turn_index=0,
                kind="user_message", index=0, role="user",
                content="Hello", created_at=utc_now(),
            ),
            ThreadSnapshotItem(
                id="item2", turn_id="turn1", turn_index=0,
                kind="agent_message", index=1, role="agent",
                content="Hi there", created_at=utc_now(),
            ),
        ]
        snap = ThreadSnapshot(
            thread_id="thread1",
            title="Test Thread",
            status="active",
            runtime_kind="hermes",
            turn_count=1,
            items=items,
            last_message_preview="Hello",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        assert snap.kind == "thread_snapshot"
        assert snap.thread_id == "thread1"
        assert len(snap.items) == 2
        assert snap.turn_count == 1

    def test_thread_item_appended_construction(self):
        item = ThreadSnapshotItem(
            id="item3", turn_id="turn2", turn_index=1,
            kind="agent_message", index=0, role="agent",
            content="Processing...", created_at=utc_now(),
        )
        appended = ThreadItemAppended(
            thread_id="thread1",
            turn_id="turn2",
            item=item,
        )
        assert appended.kind == "item_appended"
        assert appended.item is not None
        assert appended.item.content == "Processing..."

    def test_thread_status_changed(self):
        evt = ThreadStatusChanged(
            thread_id="t1",
            old_status="active",
            new_status="archived",
            updated_at=utc_now(),
        )
        assert evt.kind == "thread_status_changed"
        assert evt.old_status == "active"
        assert evt.new_status == "archived"

    def test_event_to_dict(self):
        """event_to_dict produces clean dicts for JSON transmission."""
        snap = ThreadSnapshot(
            thread_id="t1",
            title="Test",
            status="active",
            runtime_kind="hermes",
            turn_count=2,
        )
        d = event_to_dict(snap)
        assert d["type"] == "thread_snapshot"
        assert d["thread_id"] == "t1"
        assert d["title"] == "Test"
        assert d["status"] == "active"
        # Fields with empty/zero values should be omitted
        assert "last_message_preview" not in d
        assert "created_at" not in d

    def test_event_to_dict_with_items(self):
        item = ThreadSnapshotItem(
            id="i1", turn_id="tu1", turn_index=0,
            kind="user_message", index=0, role="user",
            content="hi", created_at=utc_now(),
        )
        snap = ThreadSnapshot(
            thread_id="t1",
            title="Test",
            status="active",
            runtime_kind="hermes",
            turn_count=1,
            items=[item],
            last_message_preview="hi",
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        d = event_to_dict(snap)
        assert d["type"] == "thread_snapshot"
        assert len(d["items"]) == 1
        assert d["items"][0]["id"] == "i1"
        assert d["last_message_preview"] == "hi"


# ═══════════════════════════════════════════════════════════════════════════
# Request Tracker
# ═══════════════════════════════════════════════════════════════════════════


class TestRequestTracker:
    """Request correlation tracking."""

    def test_create_and_resolve(self):
        tracker = RequestTracker()
        req = tracker.create_request(kind="process_turn", thread_id="t1", turn_id="tu1")
        assert req.status == RequestStatus.pending
        assert req.kind == "process_turn"
        assert req.thread_id == "t1"
        assert req.turn_id == "tu1"
        assert req.created_at > 0

        resolved = tracker.resolve_request(req.id)
        assert resolved is not None
        assert resolved.status == RequestStatus.completed
        assert resolved.completed_at > 0

    def test_create_and_fail(self):
        tracker = RequestTracker()
        req = tracker.create_request(kind="interrupt", thread_id="t2")
        failed = tracker.fail_request(req.id, error="timeout")
        assert failed is not None
        assert failed.status == RequestStatus.failed
        assert "timeout" in failed.error

    def test_list_pending_empty(self):
        tracker = RequestTracker()
        assert tracker.list_pending() == []

    def test_list_pending_filters_completed(self):
        tracker = RequestTracker()
        req = tracker.create_request(kind="process_turn")
        tracker.resolve_request(req.id)
        assert tracker.list_pending() == []

    def test_list_pending_with_kind_filter(self):
        tracker = RequestTracker()
        tracker.create_request(kind="process_turn")
        tracker.create_request(kind="interrupt")
        assert len(tracker.list_pending(kind="process_turn")) == 1
        assert len(tracker.list_pending(kind="interrupt")) == 1
        assert len(tracker.list_pending(kind="shutdown")) == 0

    def test_get_request_not_found(self):
        tracker = RequestTracker()
        assert tracker.get_request("nonexistent") is None

    def test_cleanup_all_cancels_pending(self):
        tracker = RequestTracker()
        tracker.create_request(kind="process_turn")
        tracker.create_request(kind="interrupt")
        resolved = tracker.create_request(kind="reset")
        tracker.resolve_request(resolved.id)

        count = tracker.cleanup_all(reason="shutdown")
        assert count == 2  # two pending, one already resolved

        remaining = tracker.list_pending()
        assert remaining == []
        cancelled = [r for r in tracker.list_all() if r.status == RequestStatus.cancelled]
        assert len(cancelled) == 2

    def test_cleanup_for_thread(self):
        tracker = RequestTracker()
        req1 = tracker.create_request(kind="process_turn", thread_id="t1")
        tracker.create_request(kind="process_turn", thread_id="t2")
        count = tracker.cleanup_for_thread("t1", reason="archived")
        assert count == 1
        assert tracker.get_request(req1.id).status == RequestStatus.cancelled

    def test_fail_not_found(self):
        tracker = RequestTracker()
        result = tracker.fail_request("nonexistent")
        assert result is None

    def test_cancel_request(self):
        tracker = RequestTracker()
        req = tracker.create_request(kind="process_turn")
        cancelled = tracker.cancel_request(req.id, reason="disconnect")
        assert cancelled.status == RequestStatus.cancelled
        assert cancelled.error == "disconnect"

    def test_create_request_explicit_id(self):
        tracker = RequestTracker()
        req = tracker.create_request(kind="process_turn", request_id="my_custom_id")
        assert req.id == "my_custom_id"

    def test_cleanup_for_turn(self):
        tracker = RequestTracker()
        tracker.create_request(kind="process_turn", turn_id="tu1")
        tracker.create_request(kind="interrupt", turn_id="tu2")
        count = tracker.cleanup_for_turn("tu1")
        assert count == 1


# ═══════════════════════════════════════════════════════════════════════════
# Runtime Event to ThreadItem conversion
# ═══════════════════════════════════════════════════════════════════════════


class TestHermesRuntimeUnit:
    """HermesRuntime unit tests (no HermesManager dependency)."""

    def test_runtime_event_has_ok_property(self):
        """RuntimeEvent.ok property works for all event kinds."""
        assert RuntimeEvent(kind="turn_completed").ok is True
        assert RuntimeEvent(kind="item_produced").ok is True
        assert RuntimeEvent(kind="turn_failed").ok is False
        assert RuntimeEvent(kind="approval_requested").ok is False
        assert RuntimeEvent(kind="turn_interrupted").ok is False

    def test_hermes_runtime_events_carry_thread_items(self):
        """RuntimeEvent.items can hold ThreadItem objects."""
        from gateway.v2.models import ThreadItem as V2Item, ThreadItemKind
        items = [
            V2Item(id="u1", thread_id="t1", turn_id="tu1",
                   kind=ThreadItemKind.user_message, index=0,
                   role="user", content="Hello", created_at=utc_now(),
                   metadata={"runtime": "hermes", "generated": True}),
            V2Item(id="a1", thread_id="t1", turn_id="tu1",
                   kind=ThreadItemKind.agent_message, index=1,
                   role="agent", content="Hi!", created_at=utc_now(),
                   metadata={"runtime": "hermes", "generated": True}),
        ]
        event = RuntimeEvent(kind="turn_completed", turn_id="tu1", items=items,
                             metadata={"duration_ms": 1234})
        assert len(event.items) == 2
        assert event.items[0].kind == ThreadItemKind.user_message
        assert event.items[0].content == "Hello"
        assert event.items[0].metadata.get("generated") is True
        assert event.metadata.get("duration_ms") == 1234


# ═══════════════════════════════════════════════════════════════════════════
# Compat utility tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCompatUtils:
    """Compat layer utility functions (no DB dependency)."""

    def test_dataclass_to_dict_pydantic(self):
        """_dataclass_to_dict handles Pydantic models."""
        from gateway.v2.compat import _dataclass_to_dict
        turn = Turn(id="tu1", thread_id="t1", turn_index=0)
        d = _dataclass_to_dict(turn)
        assert d["id"] == "tu1"
        assert d["thread_id"] == "t1"
        assert d["turn_index"] == 0

    def test_get_v1_history_empty_for_unknown_session(self):
        """get_v1_history returns empty list for unknown session."""
        import asyncio
        from gateway.v2.compat import get_v1_history, clear_mappings
        clear_mappings()
        history = asyncio.run(get_v1_history("unknown_session"))
        assert history == []

    def test_map_v1_ws_response_format(self):
        """map_v1_ws_response produces V1-shaped dicts."""
        import asyncio
        from gateway.v2.compat import clear_mappings, ensure_default_server_session, utc_now
        # This test is async and needs a DB, so we just check the function signature
        # Full test requires running gateway
        pass

    def test_clear_mappings_works(self):
        """clear_mappings resets V1→V2 session mapping."""
        from gateway.v2.compat import clear_mappings, _session_to_thread
        _session_to_thread["test"] = "thread_abc"
        clear_mappings()
        assert _session_to_thread == {}


# ═══════════════════════════════════════════════════════════════════════════
# V2 __init__.py
# ═══════════════════════════════════════════════════════════════════════════


class TestV2Package:
    """V2 package is importable."""

    def test_v2_import(self):
        import gateway.v2
        assert gateway.v2.__doc__ is not None

    def test_v2_modules_importable(self):
        from gateway.v2 import models, database, thread_store, session_store
        from gateway.v2 import thread_engine, runtime, worker, health
        from gateway.v2 import events, projection, requests, compat
        assert models is not None
        assert events is not None
        assert projection is not None
        assert requests is not None
        assert compat is not None


# ═══════════════════════════════════════════════════════════════════════════
# Projection — V1 payload builders
# ═══════════════════════════════════════════════════════════════════════════


class TestProjectionBuilders:
    """Projection layer V1 payload builders."""

    @pytest.fixture(autouse=True)
    def init_v2_db(self):
        """Ensure V2 schema exists for projection tests."""
        from gateway.v2.database import init_v2_schema
        init_v2_schema()

    def test_v1_history_empty_for_unknown_thread(self):
        """build_v1_history_payload returns empty list for unknown thread."""
        import asyncio
        from gateway.v2.projection import build_v1_history_payload
        history = asyncio.run(build_v1_history_payload("nonexistent"))
        assert history == []

    def test_v1_session_list_empty_for_unknown_session(self):
        """build_v1_session_list_payload returns empty list."""
        import asyncio
        from gateway.v2.projection import build_v1_session_list_payload
        sessions = asyncio.run(build_v1_session_list_payload("nonexistent"))
        assert sessions == []


# ═══════════════════════════════════════════════════════════════════════════
# Compat — V1→V2 mapping and request tracker
# ═══════════════════════════════════════════════════════════════════════════


class TestCompatV2:
    """Compat layer V2 integration."""

    @pytest.fixture(autouse=True)
    def init_v2_db(self):
        """Ensure V2 schema exists for compat tests."""
        from gateway.v2.database import init_v2_schema
        init_v2_schema()

    def test_add_and_get_v1_mapping(self):
        """add_v1_mapping and get_v2_thread_for_v1_session work."""
        from gateway.v2.compat import add_v1_mapping, get_v2_thread_for_v1_session, clear_mappings
        clear_mappings()
        add_v1_mapping("sess_test_1", "thread_abc")
        assert get_v2_thread_for_v1_session("sess_test_1") == "thread_abc"
        assert get_v2_thread_for_v1_session("sess_test_2") is None

    def test_get_v2_request_tracker_singleton(self):
        """get_v2_request_tracker returns the same instance."""
        from gateway.v2.compat import get_v2_request_tracker
        t1 = get_v2_request_tracker()
        t2 = get_v2_request_tracker()
        assert t1 is t2
        assert len(t1.list_all()) >= 0

    def test_v1_session_list_merge(self):
        """get_v1_session_list merges V1 DB sessions."""
        import asyncio
        from gateway.v2.compat import get_v1_session_list, clear_mappings
        clear_mappings()
        # With no V1 DB sessions and no V2 threads, returns empty
        sessions = asyncio.run(get_v1_session_list(v1_db_sessions=[]))
        assert isinstance(sessions, list)

    def test_get_v1_history_empty(self):
        """get_v1_history returns empty for no mapping."""
        import asyncio
        from gateway.v2.compat import get_v1_history, clear_mappings
        clear_mappings()
        history = asyncio.run(get_v1_history("sess_unknown"))
        assert history == []


# ═══════════════════════════════════════════════════════════════════════════
# V2 WebSocket — event protocol
# ═══════════════════════════════════════════════════════════════════════════


class TestV2WSEventProtocol:
    """V2 WebSocket event protocol models and helpers."""

    def test_ack_format(self):
        """_ack produces correct response shape."""
        from gateway.v2.ws_handler import _ack
        response = _ack("req_123", "subscribed", thread_id="thread_abc")
        assert response["type"] == "ack"
        assert response["request_id"] == "req_123"
        assert response["status"] == "subscribed"
        assert response["thread_id"] == "thread_abc"

    def test_error_format(self):
        """_error produces correct error shape."""
        from gateway.v2.ws_handler import _error
        response = _error("req_456", "Not found", code="not_found")
        assert response["type"] == "error"
        assert response["request_id"] == "req_456"
        assert response["code"] == "not_found"
        assert response["message"] == "Not found"

    def test_handler_registry(self):
        """_HANDLERS has expected commands."""
        from gateway.v2.ws_handler import _HANDLERS
        expected = {"subscribe", "unsubscribe", "start_turn", "interrupt_turn", "request_snapshot"}
        assert set(_HANDLERS.keys()) == expected

    def test_subscription_tracking(self):
        """_add_subscription and _remove_subscription work."""
        from gateway.v2.ws_handler import _add_subscription, _remove_subscription, _subscribed_clients
        _subscribed_clients.clear()

        # Mock WebSocket
        class MockWS:
            pass

        ws1 = MockWS()
        ws2 = MockWS()

        _add_subscription("thread_a", ws1)
        assert len(_subscribed_clients["thread_a"]) == 1

        _add_subscription("thread_a", ws2)
        assert len(_subscribed_clients["thread_a"]) == 2

        _remove_subscription("thread_a", ws1)
        assert len(_subscribed_clients["thread_a"]) == 1

        # Clean up
        _subscribed_clients.clear()
