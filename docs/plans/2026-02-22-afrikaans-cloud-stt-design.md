# Afrikaans Cloud Speech-to-Text Integration

**Date:** 2026-02-22
**Status:** Approved

## Problem

Whisper's zero-shot Afrikaans transcription has ~30-35% word error rate. The model frequently confuses Afrikaans with Dutch due to lexical similarity and insufficient training data. This makes Afrikaans unusable as a dictation language.

## Solution

Add Google Cloud Speech-to-Text as a per-language backend override. English continues using free local Whisper; Afrikaans routes to Google Cloud STT which has proven `af-ZA` support through their FLEURS dataset investment.

## Config Schema

```yaml
transcription:
  model: "large-v3-turbo"
  language: "en"
  backend: "mlx"
  extra_languages: ["af"]

  # Per-language backend overrides (optional)
  language_backends:
    af:
      backend: "google"
      google_credentials: "~/.claude-voice/google-credentials.json"
```

When no override exists for a language, the default backend is used.

## Architecture

### Routing

```
Transcriber.transcribe(audio, language="af")
    |
    +-- language in language_backends?
    |   +-- Yes -> GoogleCloudTranscriber.transcribe()
    |
    +-- No -> existing mlx / faster-whisper path
```

### New File: `daemon/transcribe_google.py`

`GoogleCloudTranscriber` class:
- Lazy-loads `google.cloud.speech_v1.SpeechClient` on first use
- Authenticates via service account JSON credentials file
- Sends raw PCM 16-bit 16kHz audio to `recognize()` (synchronous, for <1min recordings)
- Maps language codes to Google format (e.g., `af` -> `af-ZA`)
- Returns transcribed text string

### Changes to Existing Files

**`daemon/transcribe.py`:**
- `Transcriber.__init__` accepts `language_backends` dict from config
- `Transcriber.transcribe()` checks for language override before dispatching
- Lazy-creates backend-specific transcriber instances on first use

**`daemon/main.py`:**
- Passes `language_backends` from config to `Transcriber` constructor

**`daemon/config.py`:**
- Parses new `language_backends` section from config YAML
- Validates backend names and credential paths

**`config.yaml.example`:**
- Documents new config options with setup instructions

## Google Cloud STT Details

- **API:** `google.cloud.speech_v1` (synchronous `recognize()`)
- **Language code:** `af-ZA`
- **Audio format:** Linear PCM, 16-bit, 16kHz mono
- **Max audio:** 1 minute (sync API) — sufficient for push-to-talk
- **Pricing:** $0.024/min ($1.44/hr), 60 min/month free tier
- **Auth:** Service account JSON key file

## Dependencies

- `google-cloud-speech` pip package (added to `~/.claude-voice/venv/`)
- Google Cloud project with Speech-to-Text API enabled
- Service account key JSON downloaded to configured path

## Testing

- Unit tests for `GoogleCloudTranscriber` with mocked `SpeechClient`
- Unit tests for per-language routing in `Transcriber`
- Unit tests for config parsing of `language_backends`
- Manual integration test with real Google credentials

## Future Extensibility

The `language_backends` architecture supports adding more cloud providers (Soniox, ElevenLabs, Azure) as additional backend types. Each would get its own `transcribe_*.py` module and backend name.