# AFK Queue System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement queue-based multi-session AFK management with programmatic permissions and mobile-first UX.

**Architecture:** Extract RequestQueue, RequestRouter, and SessionPresenter abstractions from AfkManager. Replace keyboard-based permission approval with PermissionRequest hook returning JSON decisions. Maintain clean separation for easy Topics migration.

**Tech Stack:** Python 3.13, pytest, PyYAML, requests (Telegram API), dataclasses

---

## Task 1: RequestQueue Core Logic

**Files:**
- Create: `daemon/request_queue.py`
- Test: `tests/unit/test_request_queue.py`

**Step 1: Write failing test for enqueue empty queue**

Create `tests/unit/test_request_queue.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueEnqueue::test_enqueue_to_empty_makes_active -v`

Expected: FAIL with "No module named 'daemon.request_queue'"

**Step 3: Write minimal RequestQueue implementation**

Create `daemon/request_queue.py`:

```python
"""Request queue for AFK mode - manages pending requests across sessions."""

import time
from dataclasses import dataclass


@dataclass
class QueuedRequest:
    """A request waiting for user response via Telegram."""
    session: str
    req_type: str  # "permission", "input", "ask_user_question"
    prompt: str
    response_path: str
    message_id: int = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class RequestQueue:
    """FIFO queue with skip and priority jump capabilities."""

    def __init__(self):
        self._queue = []  # List of QueuedRequest
        self._active = None  # Currently displayed request
        self._session_metadata = {}  # session -> {emoji, color, first_seen}

    def enqueue(self, request: QueuedRequest) -> str:
        """Add request to queue. Returns 'active' or 'queued'."""
        if self._active is None:
            self._active = request
            return "active"
        else:
            self._queue.append(request)
            return "queued"

    def get_active(self) -> QueuedRequest | None:
        """Return the active request."""
        return self._active

    def size(self) -> int:
        """Return number of queued requests (not including active)."""
        return len(self._queue)
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueEnqueue::test_enqueue_to_empty_makes_active -v`

Expected: PASS

**Step 5: Write failing test for enqueue to non-empty queue**

Add to `tests/unit/test_request_queue.py`:

```python
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
```

**Step 6: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueEnqueue::test_enqueue_to_nonempty_adds_to_queue -v`

Expected: PASS (implementation already handles this)

**Step 7: Write failing test for dequeue_active**

Add new test class:

```python
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
```

**Step 8: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueDequeue::test_dequeue_active_with_queue_advances -v`

Expected: FAIL with "RequestQueue has no attribute 'dequeue_active'"

**Step 9: Implement dequeue_active**

Add to `RequestQueue` class in `daemon/request_queue.py`:

```python
    def dequeue_active(self) -> QueuedRequest | None:
        """Remove active request, return next in queue (now active)."""
        if not self._queue:
            self._active = None
            return None

        self._active = self._queue.pop(0)
        return self._active
```

**Step 10: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueDequeue::test_dequeue_active_with_queue_advances -v`

Expected: PASS

**Step 11: Write failing test for dequeue with empty queue**

Add to `TestRequestQueueDequeue`:

```python
    def test_dequeue_active_with_empty_queue_returns_none(self):
        """Dequeue with no queued requests clears active."""
        queue = RequestQueue()
        req = QueuedRequest("s1", "permission", "Test", "/tmp/r")
        queue.enqueue(req)

        result = queue.dequeue_active()

        assert result is None
        assert queue.get_active() is None
        assert queue.size() == 0
```

**Step 12: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueDequeue::test_dequeue_active_with_empty_queue_returns_none -v`

Expected: PASS (already works)

**Step 13: Write failing test for skip_active**

Add new test class:

```python
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
```

**Step 14: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueSkip::test_skip_active_moves_to_end -v`

Expected: FAIL with "RequestQueue has no attribute 'skip_active'"

**Step 15: Implement skip_active**

Add to `RequestQueue`:

```python
    def skip_active(self) -> QueuedRequest | None:
        """Move active to end of queue, return new active."""
        if self._active is None:
            return None

        skipped = self._active

        if not self._queue:
            # No queue, active stays active
            return self._active

        # Move active to end, pop next from front
        self._queue.append(skipped)
        self._active = self._queue.pop(0)
        return self._active
```

**Step 16: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueSkip::test_skip_active_moves_to_end -v`

Expected: PASS

**Step 17: Write failing test for priority_jump**

Add new test class:

```python
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
```

**Step 18: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueuePriorityJump::test_priority_jump_finds_session -v`

Expected: FAIL with "RequestQueue has no attribute 'priority_jump'"

**Step 19: Implement priority_jump**

Add to `RequestQueue`:

```python
    def priority_jump(self, session: str) -> QueuedRequest | None:
        """Find next request from session, make it active. Returns new active."""
        # Find first matching request in queue
        for i, req in enumerate(self._queue):
            if req.session == session:
                # Found it - remove from queue
                target = self._queue.pop(i)
                # Move old active to end of queue
                if self._active:
                    self._queue.append(self._active)
                self._active = target
                return self._active

        # Not found in queue
        return None
```

**Step 20: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueuePriorityJump::test_priority_jump_finds_session -v`

Expected: PASS

**Step 21: Run all RequestQueue tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py -v`

Expected: All tests PASS

**Step 22: Commit RequestQueue**

```bash
git add daemon/request_queue.py tests/unit/test_request_queue.py
git commit -m "feat: add RequestQueue with enqueue, dequeue, skip, priority_jump

- QueuedRequest dataclass for pending requests
- FIFO queue with active/queued distinction
- Skip moves active to end
- Priority jump finds session's next request
- Full test coverage

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Session Metadata and Emoji Assignment

**Files:**
- Modify: `daemon/request_queue.py`
- Test: `tests/unit/test_request_queue.py`

**Step 1: Write failing test for emoji assignment**

Add to `tests/unit/test_request_queue.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueSessionMetadata -v`

Expected: FAIL with "RequestQueue has no attribute 'get_session_emoji'"

**Step 3: Implement session metadata tracking**

Add to `RequestQueue` in `daemon/request_queue.py`:

```python
    EMOJI_LIST = ["🟢", "🔵", "🟡", "🔴", "🟣"]

    def get_session_emoji(self, session: str) -> str:
        """Get deterministic emoji for session based on name hash."""
        if session not in self._session_metadata:
            # Assign emoji based on hash of session name
            emoji_index = hash(session) % len(self.EMOJI_LIST)
            self._session_metadata[session] = {
                'emoji': self.EMOJI_LIST[emoji_index],
                'first_seen': time.time(),
            }
        return self._session_metadata[session]['emoji']
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueSessionMetadata -v`

Expected: PASS

**Step 5: Write failing test for get_queue_summary**

Add to `TestRequestQueueSessionMetadata`:

```python
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
```

**Step 6: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueSessionMetadata::test_get_queue_summary_with_active_and_queue -v`

Expected: FAIL with "RequestQueue has no attribute 'get_queue_summary'"

**Step 7: Implement get_queue_summary**

Add to `RequestQueue`:

```python
    def get_queue_summary(self) -> list[dict]:
        """Return list of all requests (active + queued) with metadata."""
        summary = []

        if self._active:
            summary.append({
                'request': self._active,
                'session': self._active.session,
                'req_type': self._active.req_type,
                'prompt': self._active.prompt,
                'status': 'active',
                'position': 0,
                'emoji': self.get_session_emoji(self._active.session),
                'waiting_seconds': int(time.time() - self._active.timestamp),
            })

        for i, req in enumerate(self._queue, start=1):
            summary.append({
                'request': req,
                'session': req.session,
                'req_type': req.req_type,
                'prompt': req.prompt,
                'status': 'queued',
                'position': i,
                'emoji': self.get_session_emoji(req.session),
                'waiting_seconds': int(time.time() - req.timestamp),
            })

        return summary
```

**Step 8: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py::TestRequestQueueSessionMetadata::test_get_queue_summary_with_active_and_queue -v`

Expected: PASS

**Step 9: Run all tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_queue.py -v`

Expected: All tests PASS

**Step 10: Commit session metadata**

```bash
git add daemon/request_queue.py tests/unit/test_request_queue.py
git commit -m "feat: add session metadata and emoji assignment to RequestQueue

- Deterministic emoji assignment based on session name hash
- get_session_emoji() for consistent visual markers
- get_queue_summary() with full request metadata
- Tracks first_seen timestamp per session

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: RequestRouter Abstraction

**Files:**
- Create: `daemon/request_router.py`
- Test: `tests/unit/test_request_router.py`

**Step 1: Write failing test for QueueRouter button routing**

Create `tests/unit/test_request_router.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_router.py::TestQueueRouterButtonPress -v`

Expected: FAIL with "No module named 'daemon.request_router'"

**Step 3: Write RequestRouter ABC and QueueRouter**

Create `daemon/request_router.py`:

```python
"""Request routing abstractions for AFK mode."""

from abc import ABC, abstractmethod
from daemon.request_queue import RequestQueue, QueuedRequest


class RequestRouter(ABC):
    """Routes responses to pending requests. Swappable implementation."""

    @abstractmethod
    def route_button_press(self, callback_data: str, message_id: int) -> QueuedRequest | None:
        """Find the request associated with this button press."""
        pass

    @abstractmethod
    def route_text_message(self, text: str, context: dict = None) -> QueuedRequest | None:
        """Find the request that should receive this text."""
        pass


class QueueRouter(RequestRouter):
    """Routes to active request only (queue-based system)."""

    def __init__(self, queue: RequestQueue):
        self._queue = queue

    def route_button_press(self, callback_data: str, message_id: int) -> QueuedRequest | None:
        """Route button press to active request if message_id matches."""
        active = self._queue.get_active()
        if active and active.message_id == message_id:
            return active
        return None

    def route_text_message(self, text: str, context: dict = None) -> QueuedRequest | None:
        """Route text message to active request only."""
        return self._queue.get_active()
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_router.py::TestQueueRouterButtonPress -v`

Expected: PASS

**Step 5: Write failing test for text message routing**

Add to `tests/unit/test_request_router.py`:

```python
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
```

**Step 6: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_router.py::TestQueueRouterTextMessage -v`

Expected: PASS (already implemented)

**Step 7: Run all router tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_request_router.py -v`

Expected: All tests PASS

**Step 8: Commit RequestRouter**

```bash
git add daemon/request_router.py tests/unit/test_request_router.py
git commit -m "feat: add RequestRouter abstraction with QueueRouter implementation

- RequestRouter ABC defines routing interface
- QueueRouter routes to active request only
- Button press checks message_id match
- Text message always routes to active
- Clean abstraction for Topics migration later

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: SessionPresenter Abstraction

**Files:**
- Create: `daemon/session_presenter.py`
- Test: `tests/unit/test_session_presenter.py`

**Step 1: Write failing test for active request formatting**

Create `tests/unit/test_session_presenter.py`:

```python
"""Tests for SessionPresenter."""

from unittest.mock import Mock
from daemon.session_presenter import SingleChatPresenter
from daemon.request_queue import QueuedRequest


class TestSingleChatPresenterFormatting:

    def test_format_active_permission_request(self):
        """Format active permission request with buttons."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        req = QueuedRequest("test-session", "permission", "Bash execution - rm cache/*", "/tmp/r")
        req.message_id = None
        queue_info = {
            'emoji': '🟢',
            'queue_size': 2,
            'queue_sessions': ['sess-a', 'sess-b'],
        }

        text, markup = presenter.format_active_request(req, queue_info)

        assert "🟢 ACTIVE REQUEST" in text
        assert "[test-session]" in text
        assert "Bash execution - rm cache/*" in text
        assert "Queue: 2 more waiting" in text

        # Check buttons
        assert markup is not None
        keyboard = markup['inline_keyboard']
        # First row: [Yes] [Always] [No]
        assert len(keyboard[0]) == 3
        assert keyboard[0][0]['text'] == "✓ Yes"
        assert keyboard[0][0]['callback_data'] == "yes"
        assert keyboard[0][1]['text'] == "✓ Always"
        assert keyboard[0][2]['text'] == "✗ No"

        # Second row: [⏭️ Skip] [👀 Show All]
        assert len(keyboard[1]) == 2
        assert "Skip" in keyboard[1][0]['text']
        assert "Show All" in keyboard[1][1]['text']
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py::TestSingleChatPresenterFormatting::test_format_active_permission_request -v`

Expected: FAIL with "No module named 'daemon.session_presenter'"

**Step 3: Write SessionPresenter ABC and SingleChatPresenter skeleton**

Create `daemon/session_presenter.py`:

```python
"""Session presentation abstractions for AFK mode."""

from abc import ABC, abstractmethod
from daemon.request_queue import QueuedRequest


class SessionPresenter(ABC):
    """Formats and sends messages to Telegram. Swappable for Topics."""

    @abstractmethod
    def format_active_request(self, req: QueuedRequest, queue_info: dict) -> tuple[str, dict]:
        """Format active request. Returns (message_text, reply_markup)."""
        pass

    @abstractmethod
    def send_to_session(self, session: str, text: str, markup: dict = None) -> int:
        """Send a message. Returns message_id."""
        pass


class SingleChatPresenter(SessionPresenter):
    """Formats messages for single Telegram chat (queue-based)."""

    def __init__(self, telegram_client):
        self._client = telegram_client

    def format_active_request(self, req: QueuedRequest, queue_info: dict) -> tuple[str, dict]:
        """Format active request with emoji, context, and buttons."""
        emoji = queue_info.get('emoji', '🟢')
        queue_size = queue_info.get('queue_size', 0)

        # Build message text
        lines = [
            f"{emoji} ACTIVE REQUEST",
            "",
            f"[{req.session}]",
        ]

        # Add prompt based on type
        if req.req_type == "permission":
            lines.append(f"Permission: {req.prompt}")
        elif req.req_type == "ask_user_question":
            lines.append(req.prompt)
        else:
            lines.append(f"Claude asks: {req.prompt}")

        # Add queue status
        if queue_size > 0:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━")
            plural = "request" if queue_size == 1 else "requests"
            lines.append(f"Queue: {queue_size} more {plural} waiting")

        text = "\n".join(lines)

        # Build button markup
        markup = self._make_request_buttons(req.req_type, queue_size)

        return text, markup

    def _make_request_buttons(self, req_type: str, queue_size: int) -> dict:
        """Create inline keyboard buttons for request type."""
        keyboard = []

        if req_type == "permission":
            # Permission buttons: [Yes] [Always] [No]
            keyboard.append([
                {"text": "✓ Yes", "callback_data": "yes"},
                {"text": "✓ Always", "callback_data": "always"},
                {"text": "✗ No", "callback_data": "no"},
            ])
        elif req_type == "ask_user_question":
            # Options added by caller (not in this method)
            # For now, just add Other button
            keyboard.append([
                {"text": "💬 Other (type reply)", "callback_data": "opt:__other__"},
            ])
        # For "input" type, no predefined buttons (user types freely)

        # Add queue management buttons if there's a queue
        if queue_size > 0:
            keyboard.append([
                {"text": "⏭️ Skip", "callback_data": "cmd:skip"},
                {"text": "👀 Show All", "callback_data": "cmd:show_queue"},
            ])

        return {"inline_keyboard": keyboard}

    def send_to_session(self, session: str, text: str, markup: dict = None) -> int:
        """Send message to main chat. Returns message_id."""
        return self._client.send_message(text, reply_markup=markup)
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py::TestSingleChatPresenterFormatting::test_format_active_permission_request -v`

Expected: PASS

**Step 5: Write failing test for queued notification formatting**

Add to `tests/unit/test_session_presenter.py`:

```python
    def test_format_queued_notification(self):
        """Format queued notification shows position and active context."""
        client = Mock()
        presenter = SingleChatPresenter(client)
        req = QueuedRequest("myapp", "input", "Provide API key", "/tmp/r")
        queue_info = {
            'emoji': '🔵',
            'position': 3,
            'total': 5,
            'active_session': 'claude-voice',
            'active_type': 'permission',
        }

        text = presenter.format_queued_notification(req, queue_info)

        assert "⏸️ QUEUED (position 3/5)" in text
        assert "[myapp]" in text or "myapp" in text
        assert "Provide API key" in text
        assert "claude-voice" in text  # Active session context
```

**Step 6: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py::TestSingleChatPresenterFormatting::test_format_queued_notification -v`

Expected: FAIL with "SingleChatPresenter has no attribute 'format_queued_notification'"

**Step 7: Implement format_queued_notification**

Add to `SingleChatPresenter` in `daemon/session_presenter.py`:

```python
    def format_queued_notification(self, req: QueuedRequest, queue_info: dict) -> str:
        """Format notification that request was queued."""
        emoji = queue_info.get('emoji', '⏸️')
        position = queue_info.get('position', 0)
        total = queue_info.get('total', 0)
        active_session = queue_info.get('active_session', 'unknown')
        active_type = queue_info.get('active_type', 'request')

        lines = [
            f"⏸️ QUEUED (position {position}/{total})",
            "",
            f"{emoji} [{req.session}]",
            f"{req.prompt[:100]}...",  # Preview
            "",
            f"Current: [{active_session}] {active_type}",
        ]

        return "\n".join(lines)
```

**Step 8: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py::TestSingleChatPresenterFormatting::test_format_queued_notification -v`

Expected: PASS

**Step 9: Run all presenter tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py -v`

Expected: All tests PASS

**Step 10: Commit SessionPresenter**

```bash
git add daemon/session_presenter.py tests/unit/test_session_presenter.py
git commit -m "feat: add SessionPresenter abstraction with SingleChatPresenter

- SessionPresenter ABC defines formatting/sending interface
- SingleChatPresenter formats for single Telegram chat
- Active request formatting with emoji, buttons, queue status
- Queued notification formatting with position
- Permission/AskUser/Input button variants
- Clean abstraction for Topics migration later

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Refactor AfkManager to Use Abstractions

**Files:**
- Modify: `daemon/afk.py`
- Test: `tests/unit/test_afk_manager_refactor.py`

**Step 1: Write failing integration test for AfkManager with queue**

Create `tests/unit/test_afk_manager_refactor.py`:

```python
"""Tests for refactored AfkManager using RequestQueue and abstractions."""

from unittest.mock import Mock, patch
from daemon.afk import AfkManager
from daemon.config import Config, AfkConfig, AfkTelegramConfig


class TestAfkManagerQueueIntegration:

    def test_handle_hook_request_enqueues_first_request(self):
        """First hook request becomes active and is presented."""
        config = Config(afk=AfkConfig(telegram=AfkTelegramConfig(
            bot_token="test_token",
            chat_id="test_chat"
        )))

        afk = AfkManager(config)
        afk.active = True

        # Mock presenter
        afk._presenter = Mock()
        afk._presenter.format_active_request = Mock(return_value=("Test message", {}))
        afk._presenter.send_to_session = Mock(return_value=123)

        # Send request
        response = afk.handle_hook_request({
            "session": "test-session",
            "type": "permission",
            "prompt": "Allow test?",
        })

        assert response["wait"] is True
        assert "response_path" in response

        # Verify presenter was called
        afk._presenter.send_to_session.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py::TestAfkManagerQueueIntegration::test_handle_hook_request_enqueues_first_request -v`

Expected: FAIL (AfkManager doesn't use abstractions yet)

**Step 3: Refactor AfkManager.__init__ to use abstractions**

Modify `daemon/afk.py`:

```python
# Add imports at top
from daemon.request_queue import RequestQueue, QueuedRequest
from daemon.request_router import QueueRouter
from daemon.session_presenter import SingleChatPresenter

# Modify AfkManager.__init__
class AfkManager:
    def __init__(self, config):
        self.config = config
        self.active = False
        self._client = None

        # NEW: Use abstractions
        self._queue = RequestQueue()
        self._router = None  # Set when client is created
        self._presenter = None  # Set when client is created

        # OLD: Keep for compatibility during refactor
        self._pending = {}  # message_id -> PendingRequest (DEPRECATED)
        self._pending_lock = threading.Lock()

        self._session_contexts = {}
        self._sent_message_ids = []
        self._previous_mode = None
        self._on_toggle = None
```

**Step 4: Modify start_listening to initialize router and presenter**

Modify `start_listening` in `daemon/afk.py`:

```python
    def start_listening(self, on_toggle=None) -> bool:
        if not self.is_configured:
            return False

        self._on_toggle = on_toggle
        self._client = TelegramClient(
            self.config.afk.telegram.bot_token,
            self.config.afk.telegram.chat_id,
        )

        if not self._client.verify():
            self._client = None
            return False

        # NEW: Initialize router and presenter
        self._router = QueueRouter(self._queue)
        self._presenter = SingleChatPresenter(self._client)

        self._client.start_polling(
            on_callback=self._handle_callback,
            on_message=self._handle_message,
        )
        return True
```

**Step 5: Refactor handle_hook_request to use queue**

Modify `handle_hook_request` in `daemon/afk.py`:

```python
    def handle_hook_request(self, request: dict) -> dict:
        """Handle a request from a hook. Returns response for the hook."""
        if not self.active:
            return {"wait": False}

        session = request.get("session", "unknown")
        req_type = request.get("type", "input")
        prompt = request.get("prompt", "")
        context = request.get("context", "")
        raw_text = request.get("raw_text", "")

        # Update session context
        display_context = raw_text or context
        if display_context:
            self._session_contexts[session] = display_context
        elif session in self._session_contexts:
            display_context = self._session_contexts[session]

        # Handle context-only updates
        if req_type == "context":
            # Just update context, don't queue
            emoji = self._queue.get_session_emoji(session)
            text = f"{emoji} [{session}]\n{_markdown_to_telegram_html(display_context[:3900])}"
            self._presenter.send_to_session(session, text)
            return {"wait": False}

        # Create response path
        response_path = self._response_path(session, suffix=req_type)

        # Create queued request
        queued_req = QueuedRequest(
            session=session,
            req_type=req_type,
            prompt=prompt,
            response_path=response_path,
        )

        # Enqueue request
        status = self._queue.enqueue(queued_req)

        if status == "active":
            # Present immediately
            self._present_active_request()
        else:
            # Send queued notification
            self._send_queued_notification(queued_req)

        return {"wait": True, "response_path": response_path}
```

**Step 6: Add helper methods _present_active_request and _send_queued_notification**

Add to `AfkManager` in `daemon/afk.py`:

```python
    def _present_active_request(self) -> None:
        """Present the active request to user."""
        active = self._queue.get_active()
        if not active:
            return

        summary = self._queue.get_queue_summary()
        active_info = summary[0] if summary else {}

        queue_info = {
            'emoji': active_info.get('emoji', '🟢'),
            'queue_size': self._queue.size(),
            'queue_sessions': [s['session'] for s in summary[1:]] if len(summary) > 1 else [],
        }

        text, markup = self._presenter.format_active_request(active, queue_info)
        msg_id = self._presenter.send_to_session(active.session, text, markup)

        # Store message_id for routing
        if msg_id:
            active.message_id = msg_id
            self._sent_message_ids.append(msg_id)

    def _send_queued_notification(self, req: QueuedRequest) -> None:
        """Send notification that request was queued."""
        summary = self._queue.get_queue_summary()

        # Find this request in summary
        req_info = None
        active_info = summary[0] if summary else {}
        for item in summary:
            if item['request'] == req:
                req_info = item
                break

        if not req_info:
            return

        queue_info = {
            'emoji': req_info.get('emoji', '⏸️'),
            'position': req_info.get('position', 0),
            'total': len(summary),
            'active_session': active_info.get('session', 'unknown'),
            'active_type': active_info.get('req_type', 'request'),
        }

        text = self._presenter.format_queued_notification(req, queue_info)
        self._presenter.send_to_session(req.session, text)
```

**Step 7: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py::TestAfkManagerQueueIntegration::test_handle_hook_request_enqueues_first_request -v`

Expected: PASS

**Step 8: Commit AfkManager refactor**

```bash
git add daemon/afk.py tests/unit/test_afk_manager_refactor.py
git commit -m "refactor: integrate RequestQueue abstractions into AfkManager

- Use RequestQueue, QueueRouter, SingleChatPresenter
- handle_hook_request enqueues requests
- Present active request immediately, notify for queued
- Keep old _pending dict for callback routing (temp)
- Helper methods: _present_active_request, _send_queued_notification

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Refactor Callback and Message Handlers

**Files:**
- Modify: `daemon/afk.py`
- Test: `tests/unit/test_afk_manager_refactor.py`

**Step 1: Write failing test for callback routing via QueueRouter**

Add to `tests/unit/test_afk_manager_refactor.py`:

```python
class TestAfkManagerCallbackRouting:

    def test_handle_callback_routes_via_queue_router(self):
        """Callback query routes through QueueRouter to active request."""
        config = Config(afk=AfkConfig(telegram=AfkTelegramConfig(
            bot_token="test_token",
            chat_id="test_chat"
        )))

        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._router = Mock()
        afk._presenter = Mock()

        # Mock active request
        active_req = QueuedRequest("sess1", "permission", "Test", "/tmp/r1")
        active_req.message_id = 123
        afk._router.route_button_press = Mock(return_value=active_req)

        # Mock queue operations
        afk._queue = Mock()
        afk._queue.dequeue_active = Mock(return_value=None)

        # Handle callback
        afk._handle_callback("callback_123", "yes", 123)

        # Verify routing was used
        afk._router.route_button_press.assert_called_once_with("yes", 123)
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py::TestAfkManagerCallbackRouting::test_handle_callback_routes_via_queue_router -v`

Expected: FAIL (_handle_callback still uses old _pending dict)

**Step 3: Refactor _handle_callback to use router**

Modify `_handle_callback` in `daemon/afk.py`:

```python
    def _handle_callback(self, callback_id: str, data: str, message_id: int | None) -> None:
        """Handle an inline button press from Telegram."""
        self._client.answer_callback(callback_id, text=f"Sent: {data}")

        # Route via QueueRouter
        pending = self._router.route_button_press(data, message_id)

        if not pending:
            return

        # Remove buttons from the message
        self._client.edit_message_reply_markup(message_id)

        # Handle commands (skip, show queue)
        if data.startswith("cmd:"):
            self._handle_queue_command(data[4:])
            return

        # Write response for the hook
        self._write_response(pending.response_path, data)

        # Send confirmation
        self._send_confirmation(pending.session, data)

        # Advance queue
        next_req = self._queue.dequeue_active()
        if next_req:
            self._present_active_request()
        else:
            self._presenter.send_to_session(pending.session, "✅ All requests handled!")
```

**Step 4: Add helper method _send_confirmation**

Add to `AfkManager` in `daemon/afk.py`:

```python
    def _send_confirmation(self, session: str, data: str) -> None:
        """Send confirmation that response was sent."""
        emoji = self._queue.get_session_emoji(session)
        text = f"✓ Sent to {emoji} [{session}]: {_escape_html(data)}"
        self._presenter.send_to_session(session, text)
```

**Step 5: Add stub for _handle_queue_command**

Add to `AfkManager` in `daemon/afk.py`:

```python
    def _handle_queue_command(self, cmd: str) -> None:
        """Handle queue management commands (skip, show_queue)."""
        if cmd == "skip":
            next_req = self._queue.skip_active()
            if next_req:
                self._presenter.send_to_session(
                    next_req.session,
                    "⏭️ Skipped. Next request:"
                )
                self._present_active_request()

        elif cmd == "show_queue":
            self._send_queue_summary()
```

**Step 6: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py::TestAfkManagerCallbackRouting::test_handle_callback_routes_via_queue_router -v`

Expected: PASS

**Step 7: Write failing test for text message routing**

Add to `tests/unit/test_afk_manager_refactor.py`:

```python
class TestAfkManagerTextRouting:

    def test_handle_message_routes_text_via_queue_router(self):
        """Text message routes through QueueRouter to active request."""
        config = Config(afk=AfkConfig(telegram=AfkTelegramConfig(
            bot_token="test_token",
            chat_id="test_chat"
        )))

        afk = AfkManager(config)
        afk.active = True
        afk._client = Mock()
        afk._router = Mock()
        afk._presenter = Mock()

        # Mock active request
        active_req = QueuedRequest("sess1", "input", "Provide key", "/tmp/r1")
        afk._router.route_text_message = Mock(return_value=active_req)

        # Mock queue operations
        afk._queue = Mock()
        afk._queue.dequeue_active = Mock(return_value=None)

        # Handle text message
        afk._handle_message("my-api-key-123")

        # Verify routing was used
        afk._router.route_text_message.assert_called_once_with("my-api-key-123")
```

**Step 8: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py::TestAfkManagerTextRouting::test_handle_message_routes_text_via_queue_router -v`

Expected: FAIL (_handle_message still uses old logic)

**Step 9: Refactor _handle_message to use router**

Modify `_handle_message` in `daemon/afk.py`:

```python
    def _handle_message(self, text: str) -> None:
        """Handle a text message from Telegram."""
        cmd = text.strip().lower()

        # Handle commands (work regardless of AFK state)
        if cmd == "/afk":
            if self._on_toggle:
                self._on_toggle()
            return

        if cmd == "/back":
            if self.active:
                if self._on_toggle:
                    self._on_toggle()
                else:
                    self.deactivate()
            else:
                self._presenter.send_to_session("", "Not in AFK mode. Send /afk to activate.")
            return

        if cmd == "/status":
            self.handle_status_request()
            return

        if cmd == "/clear":
            self._handle_clear()
            return

        if cmd == "/queue":
            self._send_queue_summary()
            return

        if cmd == "/skip":
            self._handle_queue_command("skip")
            return

        # Not in AFK mode
        if not self.active:
            self._presenter.send_to_session("", "Not in AFK mode. Send /afk to activate.")
            return

        # Route text to active request
        pending = self._router.route_text_message(text)

        if not pending:
            self._presenter.send_to_session("", "No active request. Queue is empty.")
            return

        # For permission requests, treat text as a question/comment
        if pending.req_type == "permission":
            self._type_into_terminal(text)
            self._presenter.send_to_session(
                pending.session,
                f"💬 Sent question to [{pending.session}]: {_escape_html(text)}\n\n"
                "Permission will be re-requested after Claude responds."
            )
            # Deny this permission request (user wants more info)
            self._write_response(pending.response_path, "deny_for_question")
            # Dequeue and present next
            next_req = self._queue.dequeue_active()
            if next_req:
                self._present_active_request()
        else:
            # Normal text response
            self._write_response(pending.response_path, text)
            self._send_confirmation(pending.session, text)

            # Advance queue
            next_req = self._queue.dequeue_active()
            if next_req:
                self._present_active_request()
            else:
                self._presenter.send_to_session(pending.session, "✅ All requests handled!")
```

**Step 10: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py::TestAfkManagerTextRouting::test_handle_message_routes_text_via_queue_router -v`

Expected: PASS

**Step 11: Run all AfkManager refactor tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_afk_manager_refactor.py -v`

Expected: All tests PASS

**Step 12: Commit callback and message handler refactor**

```bash
git add daemon/afk.py tests/unit/test_afk_manager_refactor.py
git commit -m "refactor: use QueueRouter for callback and message routing

- _handle_callback routes via router.route_button_press()
- _handle_message routes via router.route_text_message()
- Add queue commands: /skip, /queue
- Text on permission = question/comment pattern
- Remove old _pending dict routing logic
- Add _send_confirmation helper

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Queue Summary Display

**Files:**
- Modify: `daemon/afk.py`
- Modify: `daemon/session_presenter.py`
- Test: `tests/unit/test_session_presenter.py`

**Step 1: Write failing test for queue summary formatting**

Add to `tests/unit/test_session_presenter.py`:

```python
class TestSingleChatPresenterQueueSummary:

    def test_format_queue_summary_with_multiple_requests(self):
        """Format full queue summary with active and queued requests."""
        client = Mock()
        presenter = SingleChatPresenter(client)

        summary = [
            {
                'session': 'sess-a',
                'req_type': 'permission',
                'prompt': 'Bash execution',
                'status': 'active',
                'position': 0,
                'emoji': '🟢',
                'waiting_seconds': 125,
            },
            {
                'session': 'sess-b',
                'req_type': 'input',
                'prompt': 'Provide API key',
                'status': 'queued',
                'position': 1,
                'emoji': '🔵',
                'waiting_seconds': 45,
            },
            {
                'session': 'sess-a',
                'req_type': 'ask_user_question',
                'prompt': 'Choose method',
                'status': 'queued',
                'position': 2,
                'emoji': '🟢',
                'waiting_seconds': 12,
            },
        ]

        text, markup = presenter.format_queue_summary(summary)

        assert "📋 QUEUE (3 total)" in text
        assert "🟢 Active: [sess-a] permission" in text
        assert "Waiting: 2m 5s" in text

        assert "Position 1: 🔵 [sess-b] input" in text
        assert "Waiting: 45s" in text

        assert "Position 2: 🟢 [sess-a]" in text

        # Check buttons
        assert markup is not None
        keyboard = markup['inline_keyboard']
        # First button: Skip active
        assert "Skip" in keyboard[0][0]['text']
        # Other buttons: Handle Now for queued items
        assert "Handle Now" in keyboard[1][0]['text']
        assert keyboard[1][0]['callback_data'] == "cmd:priority:sess-b"
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py::TestSingleChatPresenterQueueSummary::test_format_queue_summary_with_multiple_requests -v`

Expected: FAIL with "SingleChatPresenter has no attribute 'format_queue_summary'"

**Step 3: Implement format_queue_summary**

Add to `SingleChatPresenter` in `daemon/session_presenter.py`:

```python
    def format_queue_summary(self, summary: list[dict]) -> tuple[str, dict]:
        """Format full queue summary. Returns (message_text, reply_markup)."""
        if not summary:
            return ("Queue is empty.", None)

        total = len(summary)
        lines = [f"📋 QUEUE ({total} total)", ""]

        keyboard = []

        for item in summary:
            emoji = item['emoji']
            session = item['session']
            req_type = item['req_type']
            status = item['status']
            position = item['position']
            waiting_sec = item['waiting_seconds']

            # Format waiting time
            if waiting_sec < 60:
                wait_str = f"{waiting_sec}s"
            elif waiting_sec < 3600:
                wait_str = f"{waiting_sec // 60}m {waiting_sec % 60}s"
            else:
                wait_str = f"{waiting_sec // 3600}h {(waiting_sec % 3600) // 60}m"

            if status == 'active':
                lines.append(f"{emoji} Active: [{session}] {req_type}")
                lines.append(f"  Waiting: {wait_str}")
                # Add skip button
                keyboard.append([{"text": "⏭️ Skip This", "callback_data": "cmd:skip"}])
            else:
                lines.append(f"Position {position}: {emoji} [{session}] {req_type}")
                lines.append(f"  Waiting: {wait_str}")
                # Add handle now button
                keyboard.append([{
                    "text": f"🔼 Handle Now",
                    "callback_data": f"cmd:priority:{session}"
                }])

            lines.append("")  # Blank line between items

        text = "\n".join(lines).rstrip()
        markup = {"inline_keyboard": keyboard} if keyboard else None

        return text, markup
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_session_presenter.py::TestSingleChatPresenterQueueSummary::test_format_queue_summary_with_multiple_requests -v`

Expected: PASS

**Step 5: Implement _send_queue_summary in AfkManager**

Add to `AfkManager` in `daemon/afk.py`:

```python
    def _send_queue_summary(self) -> None:
        """Send full queue summary to user."""
        summary = self._queue.get_queue_summary()

        if not summary:
            self._presenter.send_to_session("", "Queue is empty.")
            return

        text, markup = self._presenter.format_queue_summary(summary)
        self._presenter.send_to_session("", text, markup)
```

**Step 6: Implement priority jump command handling**

Modify `_handle_queue_command` in `daemon/afk.py`:

```python
    def _handle_queue_command(self, cmd: str) -> None:
        """Handle queue management commands (skip, show_queue, priority:<session>)."""
        if cmd == "skip":
            next_req = self._queue.skip_active()
            if next_req:
                emoji = self._queue.get_session_emoji(next_req.session)
                self._presenter.send_to_session(
                    "",
                    f"⏭️ Skipped. Next: {emoji} [{next_req.session}]"
                )
                self._present_active_request()

        elif cmd == "show_queue":
            self._send_queue_summary()

        elif cmd.startswith("priority:"):
            session = cmd[9:]  # Extract session name
            jumped = self._queue.priority_jump(session)
            if jumped:
                emoji = self._queue.get_session_emoji(session)
                self._presenter.send_to_session(
                    "",
                    f"⏭️ Jumped to {emoji} [{session}]"
                )
                self._present_active_request()
            else:
                self._presenter.send_to_session(
                    "",
                    f"No pending requests from [{session}]"
                )
```

**Step 7: Run all tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/ -v`

Expected: All tests PASS

**Step 8: Commit queue summary display**

```bash
git add daemon/afk.py daemon/session_presenter.py tests/unit/test_session_presenter.py
git commit -m "feat: add queue summary display with priority jump

- format_queue_summary() in SingleChatPresenter
- Shows all requests with emoji, type, waiting time
- Buttons: Skip This, Handle Now (priority jump)
- _send_queue_summary() in AfkManager
- Handle priority:<session> command for jumps

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: PermissionRequest Hook (Programmatic Approval)

**Files:**
- Create: `hooks/permission-request.py`
- Modify: `hooks/_common.py` (add rule storage helpers)
- Test: Manual testing (hook integration tests require Claude Code)

**Step 1: Create permission-request.py hook**

Create `hooks/permission-request.py`:

```python
#!/bin/bash
# -*- mode: python -*-
''''exec "$HOME/.claude-voice/venv/bin/python3" "$0" "$@" # '''
"""Claude Code PermissionRequest hook for AFK mode.

Intercepts permission requests to route through Telegram for approval.
Returns JSON decision (allow/deny) instead of keyboard simulation.
"""

import json
import os
import sys
import time

# Allow importing _common from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from _common import (
    send_to_daemon, wait_for_response, make_debug_logger, read_mode,
    SILENT_FLAG, store_permission_rule, check_permission_rules,
)

debug = make_debug_logger(os.path.expanduser("/tmp/claude-voice/logs/permission_hook.log"))


def main():
    # Check mode
    mode = read_mode()

    if mode not in ("notify", "afk"):
        return

    # Check if silent (but not in AFK mode - AFK overrides silent)
    if mode != "afk" and os.path.exists(SILENT_FLAG):
        return

    # Read hook input
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        debug("Failed to parse hook input")
        return

    tool_input = hook_input.get("tool_input", {})
    message = str(tool_input)  # Permission message from Claude Code

    debug(f"Permission request: {message}")

    # Check permission rules first
    rule_decision = check_permission_rules(message)
    if rule_decision:
        debug(f"Auto-approved by rule: {rule_decision}")
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {"behavior": rule_decision}
            }
        }
        print(json.dumps(output))
        return

    session = os.path.basename(os.getcwd())

    # Send to daemon
    debug("Sending to daemon...")
    response = send_to_daemon({
        "session": session,
        "type": "permission",
        "prompt": message,
    })
    debug(f"Daemon response: {response}")

    # Default: ask (show local permission dialog)
    decision = "ask"

    # If daemon says to wait (AFK mode), poll for response
    if response and response.get("wait"):
        response_path = response.get("response_path", "")
        debug(f"Waiting for response at: {response_path}")
        if response_path:
            answer = wait_for_response(response_path)
            debug(f"Got answer: {answer!r}")

            if answer:
                answer_lower = answer.lower()

                if answer_lower in ("always",):
                    decision = "allow"
                    store_permission_rule(message)
                    debug("Stored 'always allow' rule")

                elif answer_lower in ("yes", "y"):
                    decision = "allow"
                    debug("Allowing once")

                elif answer_lower in ("no", "n", "deny"):
                    decision = "deny"
                    debug("Denying")

                elif answer == "deny_for_question":
                    # User asked a question, deny so Claude can explain
                    decision = "deny"
                    debug("Denying (user asked question)")
            else:
                debug("No answer received (timeout)")

    # Return programmatic decision
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": decision}
        }
    }

    debug(f"Returning decision: {decision}")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
```

**Step 2: Add permission rule helpers to _common.py**

Add to `hooks/_common.py`:

```python
import json

PERMISSION_RULES_FILE = os.path.expanduser("~/.claude-voice/permission_rules.json")


def load_permission_rules() -> list[dict]:
    """Load permission rules from file."""
    if not os.path.exists(PERMISSION_RULES_FILE):
        return []
    try:
        with open(PERMISSION_RULES_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def store_permission_rule(pattern: str) -> None:
    """Store a new 'always allow' rule."""
    rules = load_permission_rules()

    # Check if pattern already exists
    for rule in rules:
        if rule.get("pattern") == pattern:
            return  # Already exists

    # Add new rule
    rules.append({
        "pattern": pattern,
        "behavior": "allow",
        "added": time.time(),
    })

    # Save
    os.makedirs(os.path.dirname(PERMISSION_RULES_FILE), exist_ok=True)
    with open(PERMISSION_RULES_FILE, "w") as f:
        json.dump(rules, f, indent=2)


def check_permission_rules(message: str) -> str | None:
    """Check if message matches any permission rules. Returns behavior or None."""
    rules = load_permission_rules()

    for rule in rules:
        pattern = rule.get("pattern", "")
        behavior = rule.get("behavior", "ask")

        # Simple substring match for now
        if pattern and pattern in message:
            return behavior

    return None
```

**Step 3: Make permission-request.py executable**

```bash
chmod +x hooks/permission-request.py
```

**Step 4: Manual test plan (document in comments)**

Add comment to top of `hooks/permission-request.py`:

```python
"""
MANUAL TEST PLAN:
1. Install this hook to ~/.claude/hooks/
2. Start daemon in AFK mode
3. In a Claude Code session, trigger a permission request (e.g., Bash tool)
4. Verify Telegram receives the request with [Yes] [Always] [No] buttons
5. Tap [Yes] → verify tool executes
6. Trigger same permission again, tap [Always] → verify rule stored
7. Trigger same permission third time → verify auto-approved (no Telegram message)
8. Send text question instead of button → verify deny + question typed to terminal
"""
```

**Step 5: Commit PermissionRequest hook**

```bash
git add hooks/permission-request.py hooks/_common.py
git commit -m "feat: add PermissionRequest hook with programmatic approval

- Returns JSON decision (allow/deny/ask) instead of keyboard simulation
- Routes through Telegram in AFK mode
- Supports 'always allow' rules stored in permission_rules.json
- Check rules before sending to Telegram (auto-approve if matched)
- Handle deny_for_question for text-based clarifications
- Replaces notify-permission.py (old keyboard simulation)

Manual testing required for full validation.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Integration Testing

**Files:**
- Create: `tests/integration/test_afk_multi_session.py`

**Step 1: Write multi-session integration test**

Create `tests/integration/test_afk_multi_session.py`:

```python
"""Integration tests for multi-session AFK queue handling."""

import os
import tempfile
from unittest.mock import Mock, patch
from daemon.afk import AfkManager
from daemon.config import Config, AfkConfig, AfkTelegramConfig


class TestMultiSessionQueue:

    def test_three_sessions_permission_requests(self):
        """Three sessions send permission requests, queued correctly."""
        config = Config(afk=AfkConfig(telegram=AfkTelegramConfig(
            bot_token="test_token",
            chat_id="test_chat"
        )))

        # Create AfkManager with mocked client
        afk = AfkManager(config)
        afk._client = Mock()
        afk._client.send_message = Mock(side_effect=[101, 102, 103])  # message_ids
        afk.active = True

        # Initialize abstractions manually (normally done in start_listening)
        from daemon.request_router import QueueRouter
        from daemon.session_presenter import SingleChatPresenter
        afk._router = QueueRouter(afk._queue)
        afk._presenter = SingleChatPresenter(afk._client)

        # Session 1 sends permission request
        with tempfile.TemporaryDirectory() as tmpdir:
            resp1_path = os.path.join(tmpdir, "resp1")
            resp1 = afk.handle_hook_request({
                "session": "session-a",
                "type": "permission",
                "prompt": "Bash execution - npm install",
            })

            assert resp1["wait"] is True
            assert afk._queue.get_active().session == "session-a"

            # Session 2 sends permission request
            resp2 = afk.handle_hook_request({
                "session": "session-b",
                "type": "permission",
                "prompt": "File write - config.json",
            })

            assert resp2["wait"] is True
            assert afk._queue.size() == 1  # session-b queued
            assert afk._queue.get_active().session == "session-a"  # Still active

            # Session 3 sends permission request
            resp3 = afk.handle_hook_request({
                "session": "session-c",
                "type": "input",
                "prompt": "Provide API key",
            })

            assert resp3["wait"] is True
            assert afk._queue.size() == 2  # session-b and session-c queued

            # Simulate button press on session-a (approve)
            active = afk._queue.get_active()
            afk._handle_callback("cb_1", "yes", active.message_id)

            # Verify session-a response written
            # (would check file in real test, but mocking for now)

            # Verify session-b is now active
            assert afk._queue.get_active().session == "session-b"
            assert afk._queue.size() == 1  # Only session-c queued
```

**Step 2: Run integration test**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/test_afk_multi_session.py -v`

Expected: PASS

**Step 3: Write test for priority jump**

Add to `tests/integration/test_afk_multi_session.py`:

```python
    def test_priority_jump_to_specific_session(self):
        """User can jump to specific session's request."""
        config = Config(afk=AfkConfig(telegram=AfkTelegramConfig(
            bot_token="test_token",
            chat_id="test_chat"
        )))

        afk = AfkManager(config)
        afk._client = Mock()
        afk._client.send_message = Mock(return_value=999)
        afk.active = True

        from daemon.request_router import QueueRouter
        from daemon.session_presenter import SingleChatPresenter
        afk._router = QueueRouter(afk._queue)
        afk._presenter = SingleChatPresenter(afk._client)

        # Enqueue 3 requests
        afk.handle_hook_request({"session": "sess-a", "type": "permission", "prompt": "Test 1"})
        afk.handle_hook_request({"session": "sess-b", "type": "input", "prompt": "Test 2"})
        afk.handle_hook_request({"session": "sess-c", "type": "permission", "prompt": "Test 3"})

        assert afk._queue.get_active().session == "sess-a"
        assert afk._queue.size() == 2

        # Jump to sess-c (skip sess-b)
        afk._handle_queue_command("priority:sess-c")

        assert afk._queue.get_active().session == "sess-c"
        # Queue should have sess-b and sess-a (moved to end)
        assert afk._queue.size() == 2
```

**Step 4: Run all integration tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/integration/ -v`

Expected: All tests PASS

**Step 5: Commit integration tests**

```bash
git add tests/integration/test_afk_multi_session.py
git commit -m "test: add multi-session integration tests for AFK queue

- Three sessions sending permission requests
- Queue ordering and advancement
- Priority jump to specific session
- Button routing and response writing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Deployment and Manual Testing

**Files:**
- Modify: None (deployment only)
- Manual testing checklist

**Step 1: Copy daemon files to ~/.claude-voice/**

```bash
cp daemon/request_queue.py ~/.claude-voice/daemon/
cp daemon/request_router.py ~/.claude-voice/daemon/
cp daemon/session_presenter.py ~/.claude-voice/daemon/
cp daemon/afk.py ~/.claude-voice/daemon/
```

**Step 2: Copy hooks to ~/.claude/hooks/**

```bash
cp hooks/permission-request.py ~/.claude/hooks/
cp hooks/_common.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/permission-request.py
```

**Step 3: Restart daemon**

```bash
pkill -f claude-voice-daemon
claude-voice-daemon &
```

**Step 4: Manual testing checklist**

Execute this checklist:

```
MANUAL TEST CHECKLIST:

[ ] Start 3 Claude Code sessions in different directories
[ ] Activate AFK mode (daemon should show "AFK mode active")
[ ] In session 1, trigger Bash tool (permission request)
[ ] Verify Telegram shows: 🟢 ACTIVE REQUEST [session-1] with [Yes][Always][No] buttons
[ ] In session 2, trigger Bash tool (permission request)
[ ] Verify Telegram shows: ⏸️ QUEUED notification
[ ] In session 3, send AskUserQuestion
[ ] Verify Telegram shows: ⏸️ QUEUED notification
[ ] Send /queue in Telegram
[ ] Verify: Shows all 3 requests with positions and emoji
[ ] Tap [🔼 Handle Now] for session 3
[ ] Verify: Session 3 becomes active, session 1 moved to queue
[ ] Tap [Yes] on session 3
[ ] Verify: Response sent, session 1 becomes active again
[ ] Send text: "Why do you need to do this?"
[ ] Verify: Text typed into Claude Code terminal, permission denied with reason
[ ] Claude responds with explanation
[ ] Permission re-requested
[ ] Verify: New permission request appears in Telegram
[ ] Tap [Always]
[ ] Verify: Rule stored, tool executes
[ ] Trigger same Bash command again in same session
[ ] Verify: Auto-approved, NO Telegram message (rule matched)
[ ] Tap [⏭️ Skip] on active request
[ ] Verify: Request moved to end, next request becomes active
[ ] Handle all remaining requests
[ ] Verify: "✅ All requests handled!" message

All tests passed: [ ]
```

**Step 5: Document deployment**

No commit needed (deployment only).

---

## Task 11: Remove Old Code and Final Cleanup

**Files:**
- Modify: `daemon/afk.py`
- Modify: `hooks/notify-permission.py` → Delete or rename to .bak

**Step 1: Remove deprecated _pending dict from AfkManager**

Modify `daemon/afk.py`:

Remove these lines from `__init__`:
```python
# OLD: Keep for compatibility during refactor
self._pending = {}  # message_id -> PendingRequest (DEPRECATED)
self._pending_lock = threading.Lock()
```

Remove any remaining references to `self._pending` throughout the file.

**Step 2: Run all tests to verify nothing broke**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`

Expected: All tests PASS

**Step 3: Rename old permission hook**

```bash
mv hooks/notify-permission.py hooks/notify-permission.py.bak
```

**Step 4: Run tests again**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`

Expected: All tests PASS

**Step 5: Commit cleanup**

```bash
git add daemon/afk.py
git rm hooks/notify-permission.py
git commit -m "refactor: remove deprecated code from AFK manager

- Remove _pending dict (fully replaced by RequestQueue)
- Remove _pending_lock (no longer needed)
- Delete old notify-permission.py hook (replaced by permission-request.py)
- Clean abstractions fully in place

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Success Criteria Verification

After completing all tasks, verify these criteria:

- ✅ Multiple Claude Code sessions can request permissions simultaneously without collisions
- ✅ Text responses always go to the correct session (no mis-routing via QueueRouter)
- ✅ Permission approval works reliably (PermissionRequest hook, no keyboard simulation)
- ✅ Mobile UX requires minimal typing (button-driven via SingleChatPresenter)
- ✅ Users can ask clarifying questions before approving permissions (text-as-question pattern)
- ✅ Clean abstractions enable Topics migration with <30% code change (RequestRouter, SessionPresenter swappable)
- ✅ All existing hooks continue working unchanged (response file mechanism preserved)

---

## Next Steps (Optional)

If all success criteria are met:

1. **Monitor production usage** - Gather metrics on queue size, skip rate, priority jumps
2. **Tune UX** - Adjust emoji, formatting, button labels based on feedback
3. **Add analytics** - Track requests per session, response times, auto-approval rate
4. **Plan Topics migration** - When ready, implement TopicRouter and TopicPresenter
