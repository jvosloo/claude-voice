# Transcription Overlay Indicator

## Problem

After releasing the push-to-talk hotkey, there is a 2-3 second delay while speech is transcribed to text. During this gap there is no visual feedback, leaving the user uncertain whether the system is working.

## Solution

A floating macOS overlay capsule that provides continuous visual feedback for the full voice input lifecycle: recording and transcription. The capsule appears centered below the notch/menu bar using PyObjC, running inside the existing daemon process.

## Visual Design

A small rounded pill (40pt tall, 100pt wide, fully rounded ends) centered horizontally on the primary display, ~10px below the menu bar.

### States

| State | Color | Animation |
|-------|-------|-----------|
| Idle | — | Hidden |
| Recording | Green `#34C759` | Appears with quick scale-up (0.15s ease-out) |
| Transcribing | Purple `#A855F7` | Color transitions over 0.3s, then repeating glow pulse (~1.5s cycle) |
| Dismissal | — | Fade-out + scale-down (0.2s) |

No text or icons. Color and animation communicate state.

The pill has a subtle dark border (1px, `rgba(0,0,0,0.2)`) and soft drop shadow. Background at 90% opacity for native feel.

## Architecture

The overlay runs on a dedicated thread inside the existing daemon using PyObjC. It creates a borderless, transparent, always-on-top NSWindow.

Window properties:
- `NSBorderlessWindowMask`, transparent background
- Status bar window level (floats above everything)
- Non-activating (does not steal focus)
- Ignores mouse events (click-through)

### State Machine

```
Idle → [hotkey pressed] → Recording → [hotkey released] → Transcribing → [text typed] → Idle
```

### Threading

PyObjC requires the Cocoa run loop on the main thread. The daemon may need to run the Cocoa app on the main thread and move hotkey/audio logic to a background thread. If not required, the overlay runs on its own thread with state changes dispatched via `performSelectorOnMainThread` or GCD.

## Integration

### New File

`daemon/overlay.py` — exposes three functions:

```python
overlay.show_recording()
overlay.show_transcribing()
overlay.hide()
```

### Changes to `daemon/main.py`

Call overlay state transitions at existing control flow points:
- Hotkey pressed → `overlay.show_recording()`
- Hotkey released (recording stops) → `overlay.show_transcribing()`
- Transcription complete (text typed out) → `overlay.hide()`

### Configuration

In `config.yaml`:

```yaml
overlay:
  enabled: true
  recording_color: "#34C759"
  transcribing_color: "#A855F7"
```

### Dependencies

Add `pyobjc-framework-Cocoa` to `requirements.txt`.

## Error Handling

- **Multiple rapid press/release** — Cancel in-progress animations, snap to latest state. No queuing.
- **PyObjC not available** — Import fails silently, overlay disables itself, voice input works normally. Warning logged at startup.
- **Multi-monitor** — Capsule appears on the primary display via `NSScreen.mainScreen()`.
- **Transcription failure** — Overlay hides regardless of success or failure. State always returns to idle.
- **Long transcription** — No timeout. Pulse continues until transcription completes.

## Scope

- One new file: `daemon/overlay.py`
- Small changes to `daemon/main.py`
- New config options in `config.yaml`
- New dependency: `pyobjc-framework-Cocoa`
- Graceful fallback if PyObjC unavailable
