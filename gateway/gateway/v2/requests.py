"""Request correlation — tracks pending operations for clean lifecycle management.

Provides a lightweight request_id-based correlation mechanism:
- RequestTracker — map of request_id → PendingRequest
- create_request() — register a new pending operation
- resolve_request() / fail_request() — close the operation
- list_pending() — find unresolved operations (for cleanup on shutdown)

Inspired by Litter-style IPC where every operation has a correlation ID
and pending requests are resolved on success, failure, or disconnect.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("gateway.v2.requests")


class RequestStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class PendingRequest:
    """A tracked operation with request_id correlation."""
    id: str
    kind: str  # e.g. "process_turn", "interrupt", "approval"
    thread_id: str = ""
    turn_id: str = ""
    status: RequestStatus = RequestStatus.pending
    metadata: dict = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


class RequestTracker:
    """Tracks pending operations by request_id.

    Provides:
    - create_request() — register a new operation
    - resolve_request() — mark as completed
    - fail_request() — mark as failed
    - cancel_request() — mark as cancelled
    - get_request() — retrieve by ID
    - list_pending() — find all unresolved
    - cleanup_all() — resolve remaining on shutdown
    """

    def __init__(self):
        self._requests: dict[str, PendingRequest] = {}

    def create_request(
        self,
        kind: str,
        thread_id: str = "",
        turn_id: str = "",
        request_id: str | None = None,
        metadata: dict | None = None,
    ) -> PendingRequest:
        """Create a new pending request.

        Args:
            kind: Operation kind (e.g. "process_turn").
            thread_id: Associated V2 thread ID.
            turn_id: Associated V2 turn ID.
            request_id: Optional explicit ID. Auto-generated if not provided.
            metadata: Optional extra context.

        Returns:
            The created PendingRequest.
        """
        import uuid
        rid = request_id or f"req_{uuid.uuid4().hex[:12]}"
        req = PendingRequest(
            id=rid,
            kind=kind,
            thread_id=thread_id,
            turn_id=turn_id,
            status=RequestStatus.pending,
            metadata=metadata or {},
            created_at=time.monotonic(),
        )
        self._requests[rid] = req
        logger.debug("Request created: id=%s kind=%s", rid, kind)
        return req

    def resolve_request(self, request_id: str, metadata: dict | None = None) -> PendingRequest | None:
        """Mark a pending request as completed.

        Args:
            request_id: The request ID to resolve.
            metadata: Optional metadata to merge into the request.

        Returns:
            The updated PendingRequest, or None if not found.
        """
        req = self._requests.get(request_id)
        if req is None:
            logger.warning("Request not found for resolve: id=%s", request_id)
            return None
        req.status = RequestStatus.completed
        req.completed_at = time.monotonic()
        if metadata:
            req.metadata.update(metadata)
        logger.debug("Request resolved: id=%s kind=%s", request_id, req.kind)
        return req

    def fail_request(self, request_id: str, error: str = "", metadata: dict | None = None) -> PendingRequest | None:
        """Mark a pending request as failed.

        Args:
            request_id: The request ID to fail.
            error: Error description.
            metadata: Optional metadata to merge.

        Returns:
            The updated PendingRequest, or None if not found.
        """
        req = self._requests.get(request_id)
        if req is None:
            logger.warning("Request not found for fail: id=%s", request_id)
            return None
        req.status = RequestStatus.failed
        req.completed_at = time.monotonic()
        req.error = error
        if metadata:
            req.metadata.update(metadata)
        logger.warning("Request failed: id=%s kind=%s error=%s", request_id, req.kind, error[:100])
        return req

    def cancel_request(self, request_id: str, reason: str = "") -> PendingRequest | None:
        """Cancel a pending request (e.g. on disconnect/shutdown).

        Args:
            request_id: The request ID to cancel.
            reason: Optional cancellation reason.

        Returns:
            The updated PendingRequest, or None if not found.
        """
        req = self._requests.get(request_id)
        if req is None:
            return None
        req.status = RequestStatus.cancelled
        req.completed_at = time.monotonic()
        req.error = reason
        logger.info("Request cancelled: id=%s reason=%s", request_id, reason)
        return req

    def get_request(self, request_id: str) -> PendingRequest | None:
        """Get a request by ID."""
        return self._requests.get(request_id)

    def list_pending(self, kind: str | None = None) -> list[PendingRequest]:
        """List all pending (unresolved) requests.

        Args:
            kind: Optional filter by request kind.

        Returns:
            List of pending PendingRequests.
        """
        result = []
        for req in self._requests.values():
            if req.status != RequestStatus.pending:
                continue
            if kind and req.kind != kind:
                continue
            result.append(req)
        return result

    def list_all(self) -> list[PendingRequest]:
        """List all tracked requests."""
        return list(self._requests.values())

    def cleanup_all(self, reason: str = "shutdown") -> int:
        """Cancel all pending requests.

        Call this during gateway shutdown to ensure no orphaned operations.

        Args:
            reason: Cancellation reason (e.g. "gateway_shutdown").

        Returns:
            Number of requests cancelled.
        """
        count = 0
        for req in list(self._requests.values()):
            if req.status == RequestStatus.pending:
                self.cancel_request(req.id, reason=reason)
                count += 1
        logger.info("RequestTracker cleanup: cancelled %d pending requests (reason=%s)", count, reason)
        return count

    def cleanup_for_thread(self, thread_id: str, reason: str = "thread_archived") -> int:
        """Cancel all pending requests for a given thread.

        Args:
            thread_id: Thread ID to clean up.
            reason: Cancellation reason.

        Returns:
            Number of requests cancelled.
        """
        count = 0
        for req in list(self._requests.values()):
            if req.thread_id == thread_id and req.status == RequestStatus.pending:
                self.cancel_request(req.id, reason=reason)
                count += 1
        if count > 0:
            logger.info("RequestTracker: cleaned %d requests for thread=%s", count, thread_id)
        return count

    def cleanup_for_turn(self, turn_id: str, reason: str = "turn_completed") -> int:
        """Cancel all pending requests for a given turn.

        Args:
            turn_id: Turn ID to clean up.
            reason: Cancellation reason.

        Returns:
            Number of requests cancelled.
        """
        count = 0
        for req in list(self._requests.values()):
            if req.turn_id == turn_id and req.status == RequestStatus.pending:
                self.cancel_request(req.id, reason=reason)
                count += 1
        return count
