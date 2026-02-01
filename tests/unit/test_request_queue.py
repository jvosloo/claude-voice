"""Tests for RequestQueue."""

import time
from daemon.request_queue import RequestQueue, QueuedRequest


class TestQueuedRequestOptions:

    def test_options_default_none(self):
        """QueuedRequest without options defaults to None."""
        req = QueuedRequest("sess", "permission", "Test", "/tmp/r")
        assert req.options is None

    def test_options_stored(self):
        """QueuedRequest stores provided options."""
        opts = [{"label": "A", "description": "first"}, {"label": "B", "description": "second"}]
        req = QueuedRequest("sess", "ask_user_question", "Pick?", "/tmp/r", options=opts)
        assert req.options == opts
        assert len(req.options) == 2
        assert req.options[0]["label"] == "A"


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


class TestRequestQueueSessionMetadata:

    def test_get_session_emoji_deterministic(self):
        """Same session always gets same emoji."""
        queue = RequestQueue()

        emoji1 = queue.get_session_emoji("test-session")
        emoji2 = queue.get_session_emoji("test-session")

        assert emoji1 == emoji2
        assert emoji1 in ["🟢", "🔵", "🟡", "🔴", "🟣"]

    def test_different_sessions_may_differ(self):
        """Different sessions may get different emoji (hash-based)."""
        queue = RequestQueue()

        emoji_a = queue.get_session_emoji("session-a")
        emoji_b = queue.get_session_emoji("session-b")

        # They're both valid emoji
        assert emoji_a in ["🟢", "🔵", "🟡", "🔴", "🟣"]
        assert emoji_b in ["🟢", "🔵", "🟡", "🔴", "🟣"]

    def test_get_queue_summary_with_active_and_queue(self):
        """Summary includes active and queued requests with metadata."""
        queue = RequestQueue()
        req1 = QueuedRequest("sess-a", "permission", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("sess-b", "input", "Test 2", "/tmp/r2")
        req3 = QueuedRequest("sess-a", "ask_user_question", "Test 3", "/tmp/r3")
        queue.enqueue(req1)
        queue.enqueue(req2)
        queue.enqueue(req3)

        summary = queue.get_queue_summary()

        assert len(summary) == 3
        assert summary[0]['session'] == 'sess-a'
        assert summary[0]['status'] == 'active'
        assert summary[0]['position'] == 0
        assert 'emoji' in summary[0]

        assert summary[1]['session'] == 'sess-b'
        assert summary[1]['status'] == 'queued'
        assert summary[1]['position'] == 1

        assert summary[2]['session'] == 'sess-a'
        assert summary[2]['status'] == 'queued'
        assert summary[2]['position'] == 2
