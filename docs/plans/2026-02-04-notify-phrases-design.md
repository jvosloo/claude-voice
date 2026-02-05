# Notify Phrases: Add Question Category & Fix AskUserQuestion Routing

## Problem

Notify mode has two phrases ("Ready for input" and "Permission needed"), but AskUserQuestion prompts incorrectly trigger "Permission needed" because Claude Code emits a `permission_prompt` notification for them. The `ASK_USER_FLAG` suppression only works in AFK mode.

Additionally, the "done" phrase text ("Ready for input") is being changed to better fit the conversational tone.

## Design

### Phrase Taxonomy

| Category | Phrase text | Trigger | User action |
|----------|-----------|---------|-------------|
| `done` | "Over to you" | Claude finished responding (Stop hook) | Read response, speak next command |
| `permission` | "Permission needed" | Claude needs tool permission (Notification hook) | Allow/deny in UI |
| `question` | "Please choose an option" | Claude uses AskUserQuestion (PreToolUse hook) | Pick an option in UI |

### Changes

#### 1. Add `question` category

- Add `"question"` to `DEFAULT_NOTIFY_PHRASES` in `daemon/config.py`
- Ship a default `daemon/notify_phrases/question.wav` (generated from Kokoro TTS)
- Regeneration logic in `daemon/notify.py` already handles arbitrary categories — no changes needed there

#### 2. Update `done` phrase text

- Change `DEFAULT_NOTIFY_PHRASES["done"]` from "Ready for input" to "Over to you"
- Ship updated `daemon/notify_phrases/done.wav`

#### 3. Play "question" phrase for AskUserQuestion in notify mode

In `handle-ask-user.py`, before returning early for non-AFK mode, send a `notify_category: "question"` message to the daemon. This gives AskUserQuestion its own audio cue in notify mode.

#### 4. Suppress "permission needed" for AskUserQuestion

Set the `ASK_USER_FLAG` in notify mode too (not just AFK), so `notify-permission.py` skips the "permission needed" phrase when AskUserQuestion is active. Clear it after a short delay or on next Stop event.

Alternatively, since change #3 makes `handle-ask-user.py` send its own notification in notify mode, the flag approach can be simplified: set the flag before sending the question notification, and `notify-permission.py` will see it and skip.

### Files Modified

- `daemon/config.py` — update `DEFAULT_NOTIFY_PHRASES`
- `daemon/notify_phrases/done.wav` — regenerated with new text
- `daemon/notify_phrases/question.wav` — new file
- `hooks/handle-ask-user.py` — send question notification in notify mode
- `hooks/notify-permission.py` — no changes needed (existing `ASK_USER_FLAG` check suffices)

### Testing

- Unit test: verify `DEFAULT_NOTIFY_PHRASES` contains all three categories
- Unit test: `handle-ask-user.py` in notify mode sends `notify_category: "question"` and sets `ASK_USER_FLAG`
- Manual: trigger AskUserQuestion in notify mode, confirm "Please choose an option" plays (not "Permission needed")
