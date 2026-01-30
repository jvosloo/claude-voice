# AFK Mode: Telegram Bridge for Claude Voice

## Overview

AFK Mode is a new daemon mode alongside the existing "notify" and "narrate" modes. When activated, the daemon stops producing voice output and bridges Claude Code sessions to a Telegram bot. The user interacts from their phone.

When Claude Code needs permission or text input, the daemon sends a Telegram message labeled with the project name and recent context. Permission prompts get inline buttons (Yes/No). Text input is handled by typing a reply. The user can check on sessions at any time with `/status`.

### What it does

- Bridges Claude Code hook events to Telegram messages
- Sends rich context (last ~10 lines of Claude output) with each notification
- Supports inline buttons for permission prompts (one tap to approve/deny)
- Supports typed replies for text input requests
- Routes responses back to the correct Claude Code session via file-based response mechanism
- Labels messages with project directory name for multi-session clarity
- On-demand `/status` command to check what sessions are doing

### What it doesn't do

- No status polling or periodic updates (only messages when Claude is blocked)
- No multi-user support (single user, single bot)
- No end-to-end encryption (Telegram can see messages)
- No PIN or extra authentication beyond chat ID validation

## Architecture

### New components

1. **`daemon/telegram.py`** - Telegram bot client. Sends messages with inline keyboards, receives replies via long-polling, routes responses to the correct session. Runs its own async loop in a background thread when AFK mode is active.

2. **`daemon/afk.py`** - AFK mode manager. Tracks active Claude Code sessions, manages the mapping between sessions and pending requests, handles activation/deactivation, coordinates between the existing hook socket server and the Telegram client.

3. **Hook modifications** - Existing hooks send a session identifier (working directory basename) and context. In AFK mode, permission hooks block and poll for a response file.

### Response routing

- When a hook sends a request to the daemon, the daemon creates a response file at `/tmp/claude-voice/<session-id>/response`
- The hook polls that file for a response (with a timeout)
- When the user replies in Telegram, the daemon writes the response to the correct file
- The hook reads it, deletes it, and types the response into the terminal

No changes to Claude Code itself. Everything works through the existing hook system.

## Telegram Bot Integration

### Setup (one-time, manual)

User creates a bot via Telegram's BotFather, gets an API token. User starts a chat with the bot to establish the chat ID. Both values go into `config.yaml`.

### Sending messages

- Uses Telegram Bot API via HTTP (`sendMessage` endpoint)
- Permission prompts use `InlineKeyboardMarkup` for Yes/No buttons
- Messages include project label and last ~10 lines of Claude output as context

Permission example:
```
[my-api]
Claude edited 3 files for JWT auth.
Now wants to run a command.

Permission: Run `npm test`?
  [ Yes ]  [ No ]
```

Text input example:
```
[my-api]
Implemented two approaches for caching.

Claude asks: "Should I use Redis or in-memory
caching for the session store?"

Reply with your answer.
```

### Receiving replies

- Long-polling via `getUpdates` endpoint (no webhook server, no open ports)
- Inline button presses arrive as `callback_query`, matched to pending request by message ID
- Text replies matched to most recent pending text-input request (or the only pending request)

### Commands

- `/status` - Summary of what each active session is doing
- `/back` - Exit AFK mode, switch back to voice

### Security

- **Chat ID validation** on every incoming message; all others ignored
- **No open ports** - long-polling connects outward
- **TLS in transit** - all Telegram API calls over HTTPS
- **Config not tracked** - `config.yaml` is `.gitignore`d, only `config.yaml.example` is in git
- Not end-to-end encrypted; Telegram servers can see message content

## AFK Mode Activation & Deactivation

### Activation triggers

- **Voice command**: "going AFK" or "away from keyboard"
- **Hotkey**: Configurable key combo (e.g., `right_alt+a`)

### On activation

- Daemon suppresses all voice/TTS output
- Starts the Telegram long-polling loop in a background thread
- Sends confirmation to Telegram: "AFK mode active. You have N Claude Code sessions running."
- Plays a short audio cue locally

### Deactivation triggers

- **Voice command**: "back at keyboard" or "I'm back"
- **Hotkey**: Same hotkey toggles AFK off
- **Telegram command**: `/back`

### On deactivation

- Stops the Telegram polling loop
- Resumes previous voice mode (notify or narrate)
- Sends final Telegram message: "AFK mode off. Back to voice."
- Pending unanswered requests remain pending; hooks still waiting, can be answered locally

## Message Flow: Claude to Phone

1. Claude Code hook fires (permission, error, or response)
2. Hook sends JSON to daemon via Unix socket:
   ```json
   {
     "type": "permission",
     "session": "my-api",
     "context": "Implemented JWT auth in src/auth.ts...",
     "prompt": "Run `npm test`?"
   }
   ```
3. Daemon checks if AFK mode is active
   - If not: handles normally (voice/notify)
   - If yes: registers pending request, sends Telegram message
4. Daemon replies to hook: `{"wait": true}` (AFK) or `{"wait": false}` (voice)
5. If waiting, hook polls `/tmp/claude-voice/<session-id>/response`
6. User responds in Telegram
7. Daemon writes response to the session's response file
8. Hook reads response, deletes file, types it into terminal

## Hook Modifications

### Session identity and context

Hooks send a JSON payload instead of a simple string:
- **Session ID**: Working directory basename via `os.getcwd()`
- **Context**: Recent Claude output, truncated to last N lines per config
- **Type**: `permission`, `error`, or `input`
- **Prompt**: What Claude is asking for

### Blocking for AFK response

- Hook sends request to daemon
- Daemon replies with `{"wait": true}` or `{"wait": false}`
- If waiting, hook polls response file at `/tmp/claude-voice/<session-id>/response`
- On response: reads, deletes file, returns the answer
- On timeout: gives up, Claude Code proceeds normally (prompt stays in terminal)

Hooks remain simple Python scripts. Complexity lives in the daemon.

## Configuration

New section in `config.yaml`:

```yaml
# AFK Mode (Telegram)
afk:
  telegram:
    bot_token: ""         # From BotFather
    chat_id: ""           # Your Telegram user/chat ID

  hotkey: "right_alt+a"   # AFK toggle hotkey

  voice_commands:
    activate:
      - "going afk"
      - "away from keyboard"
    deactivate:
      - "back at keyboard"
      - "i'm back"

  context_lines: 10       # Lines of Claude output to include in messages
```

### Validation

- If `bot_token` or `chat_id` are empty, daemon announces "Telegram not configured" via voice and refuses to enter AFK mode
- On first activation, daemon sends a test message to verify the token and chat ID work

### Dependencies

- `requests` added to `requirements.txt`
- No Telegram SDK; direct HTTP calls to the Bot API

## Error Handling

### Telegram unreachable

- On activation: announces "Telegram unavailable" via voice, stays in current mode
- Mid-AFK: retries with exponential backoff; after 5 failures, falls back to voice mode and plays alert sound

### Hook timeout

- Hooks polling for a response timeout after 10 minutes (configurable)
- On timeout, hook gives up and Claude Code proceeds normally

### Multiple pending requests (same session)

- Second request from same session noted in Telegram: "[my-api] (2nd request)"
- Both remain independently answerable via inline buttons or reply

### Session disappears

- If a Claude Code session exits while a request is pending, daemon cleans up response file and marks request stale
- Tapping the button replies: "Session ended, no action taken."

### No Telegram config

- Voice command or hotkey says "Telegram not configured" and doesn't switch modes