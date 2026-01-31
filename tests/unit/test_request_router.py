"""Tests for RequestRouter and QueueRouter."""

from daemon.request_router import QueueRouter
from daemon.request_queue import RequestQueue, QueuedRequest


class TestQueueRouterButtonPress:

    def test_route_button_press_to_active(self):
        """Button press routes to active request if message_id matches."""
        queue = RequestQueue()
        req1 = QueuedRequest("s1", "permission", "Test 1", "/tmp/r1")
        req1.message_id = 123
        req2 = QueuedRequest("s2", "input", "Test 2", "/tmp/r2")
        req2.message_id = 456
        queue.enqueue(req1)
        queue.enqueue(req2)

        router = QueueRouter(queue)
        result = router.route_button_press("yes", 123)

        assert result == req1

    def test_route_button_press_wrong_message_id_returns_none(self):
        """Button press with wrong message_id returns None."""
        queue = RequestQueue()
        req = QueuedRequest("s1", "permission", "Test", "/tmp/r")
        req.message_id = 123
        queue.enqueue(req)

        router = QueueRouter(queue)
        result = router.route_button_press("yes", 999)

        assert result is None


class TestQueueRouterTextMessage:

    def test_route_text_to_active(self):
        """Text message routes to active request."""
        queue = RequestQueue()
        req1 = QueuedRequest("s1", "input", "Test 1", "/tmp/r1")
        req2 = QueuedRequest("s2", "permission", "Test 2", "/tmp/r2")
        queue.enqueue(req1)
        queue.enqueue(req2)

        router = QueueRouter(queue)
        result = router.route_text_message("my answer")

        assert result == req1

    def test_route_text_no_active_returns_none(self):
        """Text message with no active returns None."""
        queue = RequestQueue()
        router = QueueRouter(queue)

        result = router.route_text_message("my answer")

        assert result is None
