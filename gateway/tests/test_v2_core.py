"""Tests for AFK V2 core: models, lifecycle operations, worker pattern, health."""

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
from gateway.v2.worker import WorkerCommandKind


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

        # Status transitions
        turn.status = TurnStatus.running
        assert turn.status == TurnStatus.running
        turn.status = TurnStatus.completed
        assert turn.status == TurnStatus.completed
        turn.status = TurnStatus.failed
        assert turn.status == TurnStatus.failed
        turn.status = TurnStatus.interrupted
        assert turn.status == TurnStatus.interrupted

    def test_thread_item_kinds(self):
        """All ThreadItemKind values are usable."""
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
        assert len(tid) > 10  # prefix + 12 hex chars

    def test_utc_now_format(self):
        ts = utc_now()
        assert "T" in ts
        assert ts.endswith("Z")

    def test_thread_status_enum(self):
        assert len(list(ThreadStatus)) == 4  # active, paused, completed, archived

    def test_turn_status_enum(self):
        assert len(list(TurnStatus)) == 5  # pending, running, completed, failed, interrupted

    def test_runtime_kind_enum(self):
        assert "hermes" in [k.value for k in RuntimeKind]

    def test_connection_health_enum(self):
        assert len(list(ConnectionHealth)) == 3  # connected, degraded, disconnected

    def test_worker_commands(self):
        """WorkerCommandKind has expected commands."""
        kinds = list(WorkerCommandKind)
        expected = ["process_turn", "interrupt", "reset", "get_status", "shutdown"]
        assert [k.value for k in kinds] == expected
