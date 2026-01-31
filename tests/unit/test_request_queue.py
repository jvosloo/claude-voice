"""Tests for RequestQueue."""

import time
from daemon.request_queue import RequestQueue, QueuedRequest


class TestRequestQueueEnqueue:

    def test_enqueue_to_empty_makes_active(self):
        """First request becomes active immediately."""
        queue = RequestQueue()
        req = QueuedRequest(
            session="test-session",
            req_type="permission",
            prompt="Allow test?",
            response_path="/tmp/test/response"
        )

        result = queue.enqueue(req)

        assert result == "active"
        assert queue.get_active() == req
        assert queue.size() == 0  # Active doesn't count in queue

    def test_enqueue_to_nonempty_adds_to_queue(self):
        """Second request goes to queue."""
        queue = RequestQueue()
        req1 = QueuedRequest("sess1", "permission", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("sess2", "input", "Test 2", "/tmp/r2")

        queue.enqueue(req1)
        result = queue.enqueue(req2)

        assert result == "queued"
        assert queue.get_active() == req1  # Active unchanged
        assert queue.size() == 1


class TestRequestQueueDequeue:

    def test_dequeue_active_with_queue_advances(self):
        """Dequeue active, next in queue becomes active."""
        queue = RequestQueue()
        req1 = QueuedRequest("s1", "permission", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("s2", "input", "Test 2", "/tmp/r2")
        queue.enqueue(req1)
        queue.enqueue(req2)

        result = queue.dequeue_active()

        assert result == req2  # Next request
        assert queue.get_active() == req2
        assert queue.size() == 0

    def test_dequeue_active_with_empty_queue_returns_none(self):
        """Dequeue with no queued requests clears active."""
        queue = RequestQueue()
        req = QueuedRequest("s1", "permission", "Test", "/tmp/r")
        queue.enqueue(req)

        result = queue.dequeue_active()

        assert result is None
        assert queue.get_active() is None
        assert queue.size() == 0


class TestRequestQueueSkip:

    def test_skip_active_moves_to_end(self):
        """Skip moves active to end of queue, next becomes active."""
        queue = RequestQueue()
        req1 = QueuedRequest("s1", "permission", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("s2", "input", "Test 2", "/tmp/r2")
        req3 = QueuedRequest("s3", "permission", "Test 3", "/tmp/r3")
        queue.enqueue(req1)
        queue.enqueue(req2)
        queue.enqueue(req3)

        result = queue.skip_active()

        assert result == req2  # Next becomes active
        assert queue.get_active() == req2
        assert queue.size() == 2  # req3 and req1 (moved to end)

        # Verify req1 is at end
        queue.dequeue_active()  # skip req2
        assert queue.get_active() == req3
        queue.dequeue_active()  # skip req3
        assert queue.get_active() == req1


class TestRequestQueuePriorityJump:

    def test_priority_jump_finds_session(self):
        """Jump to specific session's next request."""
        queue = RequestQueue()
        req1 = QueuedRequest("sess-a", "permission", "A1", "/tmp/a1")
        req2 = QueuedRequest("sess-b", "input", "B1", "/tmp/b1")
        req3 = QueuedRequest("sess-a", "permission", "A2", "/tmp/a2")
        req4 = QueuedRequest("sess-c", "input", "C1", "/tmp/c1")
        queue.enqueue(req1)
        queue.enqueue(req2)
        queue.enqueue(req3)
        queue.enqueue(req4)

        result = queue.priority_jump("sess-a")

        assert result == req3  # Found sess-a in queue
        assert queue.get_active() == req3
        # Queue should now be: req2, req4, req1 (old active moved to end)
        assert queue.size() == 3
