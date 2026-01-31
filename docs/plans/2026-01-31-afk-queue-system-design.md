# AFK Queue System Design

**Date:** 2026-01-31
**Status:** Approved
**Migration Path:** Designed for easy migration to Telegram Topics (Group Chat)

---

## Overview

Redesign the AFK (away from keyboard) system to handle multiple Claude Code sessions reliably through a single Telegram chat. The current system has session ambiguity, button collisions, and unreliable keyboard-based permission approval. This design introduces a **queue-based approach** with programmatic permission handling and mobile-first UX.

### Current Problems

1. **Session Ambiguity** - Text replies route to "most recent" request via heuristics, often the wrong session
2. **Button Collision** - Multiple permission requests can't coexist; only one gets buttons
3. **Keyboard Navigation Failures** - Using pynput to press Down+Enter is unreliable for permission approval
4. **Context Confusion** - With multiple sessions sending requests rapidly, users lose track of which session they're answering
5. **Lost Responses** - Misrouted responses cause 10-minute timeouts

### Design Goals

- **Mobile-first UX** - Button-driven, minimal typing, clear visual feedback
- **Session Safety** - Impossible to send responses to wrong session
- **Programmatic Permissions** - Use PermissionRequest hook API instead of keyboard simulation
- **Clean Abstractions** - **CRITICAL:** Maintain clean separation between routing logic and presentation to enable easy migration to Telegram Topics later
- **Backward Compatibility** - Hooks continue using same response file mechanism

---

## Architecture

### Queue System

**Core Concept:**
Maintain a single FIFO queue of pending requests across all sessions. One request is "active" (presented with buttons), others wait. After handling the active request, the next is automatically presented.

**Queue Structure:**
```python
class RequestQueue:
    """FIFO queue with skip and priority jump capabilities."""

    def __init__(self):
        self._queue = []  # List of PendingRequest objects
        self._active = None  # Currently displayed request
        self._session_metadata = {}  # session -> {emoji, color, first_seen}

    def enqueue(self, request: PendingRequest):
        """Add to end of queue. If empty, immediately make active."""

    def dequeue_active(self):
        """Remove active request, present next in queue."""

    def skip_active(self):
        """Move active to end of queue, present next."""

    def priority_jump(self, session: str):
        """Find next request from session, make it active."""

    def get_queue_summary(self) -> list[dict]:
        """Return list of all pending requests with metadata."""
```

**Session Identification:**
Each session gets auto-assigned visual markers:
- **Emoji** (🟢 🔵 🟡 🔴 🟣) - cycles through fixed list based on session name hash
- **Header format**: `🟢 ACTIVE: [claude-voice]` or `⏸️ QUEUED: [myapp] (position 3/5)`

---

## Request Flow

### Incoming Requests

1. **Hook sends request** → `AfkManager.handle_hook_request(request)`
   - Contains: `session`, `type` (permission/input/ask_user_question), `prompt`, `context`

2. **Session registration** (first-time):
   ```python
   if session not in self._session_metadata:
       self._session_metadata[session] = {
           'emoji': self._assign_emoji(session),
           'color': self._assign_color(session),
           'first_seen': time.time(),
       }
   ```

3. **Create & enqueue**:
   - Build `PendingRequest` with session metadata
   - `RequestQueue.enqueue(request)`
   - If queue was empty → immediately present as active
   - If queue has items → send queued notification:
     ```
     ⏸️ QUEUED (position 3/5)

     [myapp]
     <context preview>

     Current: [claude-voice] Permission request
     ```

4. **Response received** (button or text):
   - Write to `/tmp/claude-voice/sessions/<session>/response_<type>`
   - Send confirmation: `✓ Sent to [claude-voice]: "yes"`
   - `RequestQueue.dequeue_active()` to present next
   - If queue empty: `✅ All requests handled!`

### Response Routing

**Button Press (Callback Query):**
- Always routes to active request (message_id match)
- Callback data: `"yes"`, `"always"`, `"no"`, or `"opt:<label>"`
- Removes buttons after press
- No routing ambiguity

**Text Reply:**
- Routes to active request ONLY
- If no active request: "No active request. Queue is empty."
- Prevents mis-routing

**Text as Question/Comment:**
- If user sends text instead of tapping button on permission request
- Text is typed into Claude Code terminal (via `_type_into_terminal`)
- Hook returns `deny` with reason: `"User question: <text>"`
- Claude sees denial + question, responds with explanation
- Claude re-requests permission (with explanation in context)
- Permission re-appears in queue, user can now tap [Yes] with full understanding

---

## Permission Handling (Programmatic)

### Migration from Keyboard Simulation

**Old approach (unreliable):**
- Notification hook fires when permission dialog appears
- Use pynput to simulate Down arrow + Enter keypresses
- Fails due to timing issues, focus issues, race conditions

**New approach (programmatic):**
- Use **PermissionRequest hook** (introduced in Claude Code v2.0.45)
- Hook returns JSON decision before permission dialog appears
- No keyboard simulation needed

### Implementation

**Hook: `permission-request.py` (replaces `notify-permission.py`)**

```python
# Wait for Telegram response
response = send_to_daemon({
    "session": session,
    "type": "permission",
    "prompt": message,
})

if response and response.get("wait"):
    answer = wait_for_response(response["response_path"])

    # Return programmatic decision
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": "allow" if answer in ("yes", "always") else "deny"
            }
        }
    }

    # Store "always" rules
    if answer == "always":
        store_permission_rule(message)

    print(json.dumps(output))
```

**"Always Allow" Rules:**
- Stored in `~/.claude-voice/permission_rules.json`
- Format: `[{"pattern": "Bash execution - npm install", "behavior": "allow"}, ...]`
- Future requests check rules first, auto-approve without Telegram if match found

---

## Mobile-First UX

### Default Flow (No Commands Needed)

**90% use case:** Open Telegram → Tap button → Done

**Active request message:**
```
🟢 ACTIVE REQUEST

[claude-voice]
Permission: Bash execution - rm old_cache/*

[Yes] [Always] [No]

━━━━━━━━━━━━━━━━━━
Queue: 2 more waiting
[⏭️ Skip] [👀 Show All]
```

**After tapping button:**
```
✓ Sent "yes" to [claude-voice]

🔵 NEXT REQUEST

[myapp]
Choose authentication method:
• OAuth2 - Industry standard...
• JWT - Lightweight tokens...

[OAuth2] [JWT] [Other]
```

### Queue Management (Button-Driven)

**Show All Queue:**
```
📋 QUEUE (3 total)

🟢 Active: [claude-voice] Permission
[⏭️ Skip This]

Position 2: 🔵 [myapp] AskUserQuestion
[🔼 Handle Now]

Position 3: 🟡 [backend] Permission
[🔼 Handle Now]
```

**Commands (Fallback):**
- `/queue` - Same as tapping "👀 Show All"
- `/skip` - Same as tapping "⏭️ Skip"
- `/clear` - Clear message history
- `/status` - Enhanced session overview

Most users never need to type commands.

---

## Clean Abstractions (Critical for Topics Migration)

**Why this matters:**
This queue-based design is optimized for a single Telegram chat. Later, we may want to migrate to **Telegram Topics** (group chat with threads), where each session gets its own topic/thread. Clean abstractions make this migration a small refactor instead of a rewrite.

### Key Abstractions

**1. RequestRouter** (routing logic)

```python
class RequestRouter(ABC):
    """Routes responses to pending requests. Swappable implementation."""

    @abstractmethod
    def route_button_press(self, callback_data: str, message_id: int) -> PendingRequest:
        """Find the request associated with this button press."""

    @abstractmethod
    def route_text_message(self, text: str, context: dict = None) -> PendingRequest:
        """Find the request that should receive this text."""
```

**Implementations:**
- `QueueRouter` (current design) - routes to active request only
- `TopicRouter` (future) - routes by `message.message_thread_id`

**2. SessionPresenter** (message formatting)

```python
class SessionPresenter(ABC):
    """Formats and sends messages to Telegram. Swappable for Topics."""

    @abstractmethod
    def format_active_request(self, req: PendingRequest, queue_info: dict) -> tuple[str, dict]:
        """Returns (message_text, reply_markup)."""

    @abstractmethod
    def send_to_session(self, session: str, text: str, markup: dict = None) -> int:
        """Send a message. Returns message_id."""
```

**Implementations:**
- `SingleChatPresenter` (current design) - sends to main chat with session labels
- `TopicPresenter` (future) - sends to session's topic via `message_thread_id`

**3. AfkManager coordination**

```python
class AfkManager:
    def __init__(self, config):
        self.config = config
        self._client = TelegramClient(...)
        self._queue = RequestQueue()
        self._router = QueueRouter(self._queue)  # Swappable
        self._presenter = SingleChatPresenter(self._client)  # Swappable
```

### Migration Path to Topics

To migrate to Telegram Topics later:

1. Implement `TopicRouter` (routes by thread_id instead of active-only)
2. Implement `TopicPresenter` (adds `message_thread_id` to send calls, auto-creates topics)
3. Swap in `AfkManager.__init__`:
   ```python
   self._router = TopicRouter(self._queue)
   self._presenter = TopicPresenter(self._client)
   ```
4. Core logic (RequestQueue, hooks, response files) **unchanged**

**Estimated effort:** ~20-30% of AFK code, mostly in `afk.py`. Hooks unchanged.

### Abstraction Requirements

**CRITICAL:** During implementation, maintain these boundaries:
- **Never** let AfkManager call `self._client.send_message()` directly → always use `self._presenter.send_to_session()`
- **Never** hard-code routing logic in message handlers → always use `self._router.route_*()`
- **Never** mix presentation logic (message formatting) with routing logic
- All session-specific state lives in `RequestQueue` and `SessionPresenter`, not scattered in AfkManager

**Refactoring litmus test:** If swapping `QueueRouter` → `TopicRouter` requires changing code outside of the router class, abstractions are too leaky.

---

## Testing Strategy

### Unit Tests

**RequestQueue:**
- Enqueue/dequeue operations
- Skip moves to end correctly
- Priority jump finds correct session
- Empty queue edge cases

**QueueRouter:**
- Button press routes to active request only
- Text message routes to active request only
- Returns None when queue empty

**SingleChatPresenter:**
- Message formatting includes queue status
- Session emoji assignment is deterministic
- Active vs queued request formatting differs

### Integration Tests

**Multi-session flow:**
- Mock TelegramClient
- Simulate 3 sessions sending permission requests
- Verify queue order, button routing, response files written correctly

**Permission approval:**
- Mock PermissionRequest hook input
- Verify JSON output format matches Claude Code spec
- Test "always" rule storage and retrieval

### Manual Testing

**Pre-deployment checklist:**
- [ ] Start 3 Claude Code sessions in different directories
- [ ] Trigger permission requests from each
- [ ] Verify queue shows all 3 with correct emoji/labels
- [ ] Tap buttons, verify responses go to correct sessions
- [ ] Test /skip, /queue, /priority commands
- [ ] Send text question on permission, verify deny+comment flow
- [ ] Test "Always allow", verify rule stored and applied next time

---

## Rollout Plan

### Phase 1: Implementation (This Design)

1. **Refactor `afk.py`:**
   - Extract `RequestQueue` class
   - Create `RequestRouter` and `QueueRouter`
   - Create `SessionPresenter` and `SingleChatPresenter`
   - Update `AfkManager` to use abstractions

2. **Migrate permission hook:**
   - Rename `notify-permission.py` → `permission-request.py`
   - Change hook type from Notification → PermissionRequest
   - Return JSON decision instead of keyboard simulation
   - Add permission rules storage (`~/.claude-voice/permission_rules.json`)

3. **Add queue commands:**
   - Implement `/skip`, `/queue`, `/priority` handlers
   - Add inline buttons: [⏭️ Skip], [👀 Show All], [🔼 Handle Now]

4. **Update hooks:**
   - Verify `handle-ask-user.py` works with queue
   - Update `speak-response.py` if needed (likely unchanged)

5. **Testing:**
   - Run unit tests
   - Run integration tests
   - Manual multi-session testing

6. **Deploy:**
   - Copy to `~/.claude-voice/daemon/`
   - Copy hooks to `~/.claude/hooks/`
   - Restart daemon
   - Test with live Claude Code sessions

### Phase 2: Stabilization

- Monitor logs for routing errors
- Gather user feedback on mobile UX
- Tune queue presentation (emoji, formatting)
- Add analytics (requests handled, skip rate, etc.)

### Phase 3: Optional Migration to Topics

- Implement `TopicRouter` and `TopicPresenter`
- Test in isolated group chat
- Migrate when ready (or stay on queue system if preferred)

---

## Files to Modify

### Daemon

- `daemon/afk.py` - Major refactor (queue, abstractions)
- `daemon/telegram.py` - Minor changes (expose thread_id in future)

### Hooks

- `hooks/notify-permission.py` → `hooks/permission-request.py` - Rewrite for PermissionRequest hook
- `hooks/handle-ask-user.py` - Verify unchanged (should work as-is)
- `hooks/speak-response.py` - Verify unchanged
- `hooks/_common.py` - Possibly add queue-related helpers

### New Files

- `daemon/request_queue.py` - RequestQueue implementation
- `daemon/request_router.py` - RequestRouter ABC + QueueRouter
- `daemon/session_presenter.py` - SessionPresenter ABC + SingleChatPresenter
- `~/.claude-voice/permission_rules.json` - "Always allow" rules storage

### Tests

- `tests/unit/test_request_queue.py`
- `tests/unit/test_queue_router.py`
- `tests/unit/test_session_presenter.py`
- `tests/integration/test_afk_multi_session.py`

---

## Success Criteria

- ✅ Multiple Claude Code sessions can request permissions simultaneously without collisions
- ✅ Text responses always go to the correct session (no mis-routing)
- ✅ Permission approval works reliably (no keyboard simulation)
- ✅ Mobile UX requires minimal typing (button-driven)
- ✅ Users can ask clarifying questions before approving permissions
- ✅ Clean abstractions enable Topics migration with <30% code change
- ✅ All existing hooks continue working unchanged (response file mechanism)

---

## References

- [PermissionRequest Hook - Claude Code Docs](https://code.claude.com/docs/en/hooks)
- [Configure permissions - Claude API Docs](https://platform.claude.com/docs/en/agent-sdk/permissions)
- [Universal Permission Request Hook for Claude Code](https://gist.github.com/doobidoo/fa84d31c0819a9faace345ca227b268f)
