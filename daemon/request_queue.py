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
    options: list = None  # AskUserQuestion options: [{"label": "...", "description": "..."}]
    context: str = None  # Last assistant message for session context
    message_id: int = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class RequestQueue:
    """FIFO queue with skip and priority jump capabilities."""

    EMOJI_LIST = ["🟢", "🔵", "🟡", "🔴", "🟣"]

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

    def dequeue_active(self) -> QueuedRequest | None:
        """Remove active request, return next in queue (now active)."""
        if not self._queue:
            self._active = None
            return None

        self._active = self._queue.pop(0)
        return self._active

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

    def clear(self) -> list[QueuedRequest]:
        """Remove all requests (active + queued). Returns the removed requests."""
        removed = []
        if self._active:
            removed.append(self._active)
            self._active = None
        removed.extend(self._queue)
        self._queue.clear()
        return removed
