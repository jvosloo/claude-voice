# Multilingual Dictation: Language Cycling

## Overview

Add a language-cycle hotkey that toggles between configured languages. The same Whisper `large-v3` model is used for all languages, with the `language` parameter switched accordingly. The overlay provides visual feedback on language switches and during recording.

## User Flow

1. **Default state**: language is `en`, recording works as today
2. **Tap `right_cmd`**: cycles to next language (e.g., `af`). Overlay flashes a pill showing "AF" in large white text, then fades
3. **Hold `right_alt` to record**: transcribes using the active language. Overlay shows green pill with "AF" label (or no label if on default)
4. **Tap `right_cmd` again**: cycles back to `en`. Overlay flashes "EN", then fades

## Configuration

```yaml
input:
  hotkey: "right_alt"
  language_hotkey: "right_cmd"    # cycle between languages

transcription:
  model: "large-v3"
  backend: "mlx"
  language: "en"                  # default language
  extra_languages: ["af"]         # additional languages to cycle through
```

Multiple extra languages example:

```yaml
transcription:
  language: "en"
  extra_languages: ["af", "de"]
  # cycle order: en -> af -> de -> en -> af -> de -> ...
```

## Overlay Behavior

| State | Display |
|---|---|
| Language switched (any) | Pill with language code ("AF", "EN") in large white text, fades after ~1.5s |
| Recording, default language | Green pill, no label |
| Recording, non-default language | Green pill with language label ("AF") |
| Transcribing | Purple pulsing pill (unchanged) |

## Implementation Scope

### Files to modify

- **`daemon/config.py`** - Add `language_hotkey` to `InputConfig`, add `extra_languages` to `TranscriptionConfig`
- **`daemon/hotkey.py`** - Register the language cycle hotkey, track active language state
- **`daemon/transcribe.py`** - Accept `language` parameter in `transcribe()` instead of hardcoding `"en"`, wire through the config `language` field
- **`daemon/overlay.py`** - Support showing a text label on the pill, support the language-switch flash notification
- **`daemon/main.py`** - Wire everything together: pass active language to transcriber, pass language state to overlay
- **`config.yaml.example`** - Document the new config fields

### Files unchanged

- `daemon/tts.py`, `daemon/audio.py`, `daemon/keyboard.py`, `daemon/cleanup.py` - no impact

### No new dependencies

Same Whisper `large-v3` model, same MLX backend. The only change is passing a different `language` parameter per recording.

## What's NOT Included

- No auto-detection fallback
- No per-language model selection (same model for all languages)
- No translation (Afrikaans in -> Afrikaans out). Translation is planned as a separate future feature
- No language-specific TTS voice switching

## Edge Cases

- **No `extra_languages` configured**: language hotkey does nothing, behaves exactly as today
- **No `language_hotkey` configured**: no cycling available, single-language mode as today
- **Model compatibility**: `.en` models (e.g., `base.en`, `small.en`) only support English. If someone configures extra languages with an English-only model, log a warning at startup suggesting they switch to a multilingual model like `large-v3`
- **Overlay disabled**: language cycling still works, no visual feedback. Print language changes to daemon console log instead

## Testing Approach

1. Configure `extra_languages: ["af"]` with `large-v3`
2. Tap language hotkey - verify overlay flashes "AF"
3. Record Afrikaans speech - verify transcription is Afrikaans (not Dutch)
4. Tap language hotkey - verify overlay flashes "EN"
5. Record English speech - verify transcription is English as before
6. Test with no `extra_languages` configured - verify no regressions
