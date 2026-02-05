# Narrate Mode Summarization Design

**Date:** 2026-02-05
**Status:** Approved

## Overview

Transform narrate mode from verbatim TTS to LLM-summarized TTS. Instead of reading full responses aloud (which is tedious with code and technical content), summarize what Claude did using a local Ollama model, then speak the summary.

## Config Changes

New option in `speech` section of `config.yaml`:

```yaml
speech:
  mode: "notify"              # existing: "notify" or "narrate"
  narrate_style: "brief"      # NEW: "brief", "conversational", or "bullets"
```

### Summarization Styles

| Style | Description | Example |
|-------|-------------|---------|
| **brief** (default) | 1-2 sentence status update | "I fixed the login bug and added a test." |
| **conversational** | Natural spoken recap, 2-4 sentences | "So I looked at your code and found the issue was in the auth flow..." |
| **bullets** | Structured bullet points | "First, fixed the bug. Second, added tests. Finally, updated docs." |

The Ollama model is shared with transcription cleanup (`input.cleanup_model`, default: `qwen3:1.7b`).

## Implementation Flow

When narrate mode receives text from the speak-response hook:

1. **Filter** — Remove code blocks, file paths, tool outputs, stack traces
   - Reuse/enhance `clean_text_for_speech()` from `daemon/text_processing.py`

2. **Summarize** — Send filtered text to Ollama with style-specific prompt
   - New `ResponseSummarizer` class in `daemon/summarize.py`
   - Pattern matches existing `TranscriptionCleaner`
   - Timeout: 10 seconds

3. **Speak** — Pass summary to `tts_engine.speak()`

4. **Fallback** — If summarization fails, play notify phrase ("Over to you")

### Code Location

The change happens in `daemon/main.py` around line 497. Currently:

```python
if mode == "notify":
    category = classify(text)
    play_phrase(category, self.config.speech.notify_phrases)
else:
    self.tts_engine.speak(text, ...)  # <-- narrate: speaks verbatim
```

After change:

```python
if mode == "notify":
    category = classify(text)
    play_phrase(category, self.config.speech.notify_phrases)
else:
    summary = self.summarizer.summarize(text, style=self.config.speech.narrate_style)
    if summary:
        self.tts_engine.speak(summary, ...)
    else:
        play_phrase("done", self.config.speech.notify_phrases)  # fallback
```

## Summarization Prompts

### Brief Style
```
Summarize what was done in 1-2 short sentences. Focus on actions and outcomes.
Be direct: "I did X" not "The assistant did X". Omit technical details.
```

### Conversational Style
```
Give a natural, spoken recap of what happened. Use casual language like you're
explaining to a colleague. Start with context if helpful. 2-4 sentences max.
Be direct: "I did X" not "The assistant did X".
```

### Bullets Style
```
Summarize as 2-4 brief spoken bullet points. Start each with "First," "Second,"
"Then," "Finally," etc. Keep each point under 10 words.
Be direct: "Fixed the bug" not "The assistant fixed the bug".
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Ollama not running | Fall back to notify mode, log warning |
| Model not found | Fall back to notify mode, log warning |
| Timeout (>10s) | Fall back to notify mode, log warning |
| Empty summary returned | Fall back to notify mode, log warning |
| Filtered text too short (<20 chars) | Skip summarization, speak filtered text directly |

## File Changes

| File | Change |
|------|--------|
| `daemon/config.py` | Add `narrate_style: str = "brief"` to `SpeechConfig` |
| `daemon/summarize.py` | **New file** — `ResponseSummarizer` class |
| `daemon/main.py` | Import summarizer, call it in narrate mode branch |
| `daemon/main.py` | Add summarizer to `reload_config()` |
| `daemon/text_processing.py` | Enhance `clean_text_for_speech()` if needed |
| `config.yaml.example` | Document new `narrate_style` option |
| `tests/unit/test_summarize.py` | Unit tests for `ResponseSummarizer` |
| `~/.claude-voice/dev/coordination.md` | Settings app coordination entry |

## Settings App Coordination

Entry to add to `~/.claude-voice/dev/coordination.md`:

```markdown
### Add narrate style selector to Voice Output settings
**Status:** [PENDING]
**Date:** 2026-02-05

Narrate mode now summarizes responses instead of reading verbatim. Add UI to select the summarization style.

**Config key:** `speech.narrate_style`
**Options:**
- "brief" (default) — 1-2 sentence status update
- "conversational" — Natural spoken recap
- "bullets" — Structured bullet points

Display as a segmented control or dropdown below the Mode selector, only visible when Mode is set to "Narrate".
```

## Not Changing

- Settings app (separate repo, coordination doc handles this)
- Notify mode (unchanged)
- AFK mode (unchanged)
- Transcription cleanup (separate feature, just shares the model)
