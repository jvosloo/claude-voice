# Afrikaans Cloud STT Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Google Cloud Speech-to-Text as a per-language transcription backend so Afrikaans routes to Google Cloud while English stays on free local Whisper.

**Architecture:** The `Transcriber` class gains a `language_backends` config dict. When `transcribe()` is called with a language that has a backend override, it delegates to a lazy-loaded `GoogleCloudTranscriber` instead of the local Whisper path. A new `daemon/transcribe_google.py` module encapsulates all Google Cloud API interaction.

**Tech Stack:** `google-cloud-speech` Python SDK, service account JSON auth, synchronous `recognize()` API for <1min push-to-talk audio.

---

### Task 1: Add `language_backends` to Config Dataclass

**Files:**
- Modify: `daemon/config.py:20-26` (TranscriptionConfig dataclass)
- Test: `tests/unit/test_config.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
class TestLanguageBackends:

    def test_language_backends_default_empty(self):
        """No language_backends configured by default."""
        with patch("daemon.config.os.path.exists", return_value=False):
            cfg = load_config()
        assert cfg.transcription.language_backends == {}

    def test_language_backends_parsed_from_yaml(self):
        yaml_content = """
transcription:
  language_backends:
    af:
      backend: "google"
      google_credentials: "~/.claude-voice/google-creds.json"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.transcription.language_backends == {
            "af": {
                "backend": "google",
                "google_credentials": "~/.claude-voice/google-creds.json",
            }
        }

    def test_language_backends_ignored_when_absent(self):
        """Existing configs without language_backends still work."""
        yaml_content = """
transcription:
  model: "large-v3-turbo"
  language: "en"
"""
        with patch("daemon.config.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml_content)):
                cfg = load_config()
        assert cfg.transcription.language_backends == {}
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_config.py::TestLanguageBackends -v`
Expected: FAIL — `TranscriptionConfig` does not have `language_backends` field.

**Step 3: Write minimal implementation**

In `daemon/config.py`, add the field to `TranscriptionConfig`:

```python
@dataclass
class TranscriptionConfig:
    model: str = "large-v3-turbo"
    language: str = "en"
    device: str = "cpu"
    backend: str = "mlx"
    extra_languages: list = field(default_factory=list)
    word_replacements: dict = field(default_factory=lambda: {"clawd": "Claude"})
    language_backends: dict = field(default_factory=dict)
```

No changes needed to `load_config()` — the `**data.get('transcription', {})` unpacking already forwards any YAML keys to the dataclass constructor, and the `field(default_factory=dict)` handles the missing case.

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_config.py -v`
Expected: ALL PASS (including existing tests).

**Step 5: Commit**

```
feat: add language_backends config field for per-language transcription
```

---

### Task 2: Create GoogleCloudTranscriber

**Files:**
- Create: `daemon/transcribe_google.py`
- Test: `tests/unit/test_transcribe_google.py`

**Step 1: Write the failing test**

Create `tests/unit/test_transcribe_google.py`:

```python
"""Tests for daemon/transcribe_google.py — Google Cloud STT backend."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from daemon.transcribe_google import GoogleCloudTranscriber


class TestGoogleCloudTranscriber:

    def test_transcribe_returns_text(self):
        """Basic transcription returns recognized text."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_alternative = MagicMock()
        mock_alternative.transcript = "hallo wêreld"
        mock_result.alternatives = [mock_alternative]
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == "hallo wêreld"

    def test_transcribe_empty_audio_returns_empty(self):
        """Empty audio returns empty string without calling API."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")
        result = t.transcribe(np.array([], dtype=np.float32), language="af")
        assert result == ""

    def test_transcribe_no_results_returns_empty(self):
        """API returning no results gives empty string."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == ""

    def test_language_code_mapping(self):
        """Language codes are mapped to Google format (e.g., af -> af-ZA)."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        call_args = mock_client.recognize.call_args
        config = call_args[1]["config"] if "config" in call_args[1] else call_args[0][0]
        assert config.language_code == "af-ZA"

    def test_audio_converted_to_pcm_16bit(self):
        """Float32 audio is converted to LINEAR16 PCM bytes for the API."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.results = []
        mock_client.recognize.return_value = mock_response

        audio = np.array([0.5, -0.5, 0.0], dtype=np.float32)

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            t.transcribe(audio, language="af")

        call_args = mock_client.recognize.call_args
        audio_arg = call_args[1]["audio"] if "audio" in call_args[1] else call_args[0][1]
        # Audio content should be bytes (LINEAR16)
        assert isinstance(audio_arg.content, bytes)
        # 3 samples * 2 bytes per sample (int16) = 6 bytes
        assert len(audio_arg.content) == 6

    def test_client_lazy_loaded(self):
        """Client is not created until first transcribe call."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")
        assert t._client is None

    def test_multiple_results_concatenated(self):
        """Multiple recognition results are joined with spaces."""
        t = GoogleCloudTranscriber(credentials_path="/fake/creds.json")

        mock_client = MagicMock()
        result1 = MagicMock()
        alt1 = MagicMock()
        alt1.transcript = "hallo"
        result1.alternatives = [alt1]
        result2 = MagicMock()
        alt2 = MagicMock()
        alt2.transcript = "wêreld"
        result2.alternatives = [alt2]
        mock_response = MagicMock()
        mock_response.results = [result1, result2]
        mock_client.recognize.return_value = mock_response

        with patch.object(t, '_ensure_client', return_value=mock_client):
            t._client = mock_client
            result = t.transcribe(np.zeros(16000, dtype=np.float32), language="af")

        assert result == "hallo wêreld"
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe_google.py -v`
Expected: FAIL — `daemon.transcribe_google` module does not exist.

**Step 3: Write minimal implementation**

Create `daemon/transcribe_google.py`:

```python
"""Google Cloud Speech-to-Text transcription backend."""

import numpy as np
from typing import Optional


# Language code mapping: short code -> Google BCP-47 code
LANGUAGE_MAP = {
    "af": "af-ZA",
    "en": "en-US",
    "de": "de-DE",
    "nl": "nl-NL",
    "fr": "fr-FR",
    "es": "es-ES",
    "pt": "pt-BR",
    "it": "it-IT",
    "ja": "ja-JP",
    "zh": "zh-CN",
}


class GoogleCloudTranscriber:
    """Transcribes audio using Google Cloud Speech-to-Text API."""

    def __init__(self, credentials_path: str):
        self._credentials_path = credentials_path
        self._client = None

    def _ensure_client(self):
        """Lazy-load the Google Cloud Speech client."""
        if self._client is None:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.expanduser(
                self._credentials_path
            )
            from google.cloud import speech
            self._client = speech.SpeechClient()
        return self._client

    def transcribe(self, audio: np.ndarray, language: str = "af",
                   sample_rate: int = 16000) -> str:
        """Transcribe audio using Google Cloud Speech-to-Text.

        Args:
            audio: Audio data as float32 numpy array normalized to [-1, 1]
            language: Language code (e.g. "af", "en")
            sample_rate: Audio sample rate in Hz

        Returns:
            Transcribed text string
        """
        if len(audio) == 0:
            return ""

        client = self._ensure_client()
        from google.cloud import speech

        # Convert float32 [-1, 1] to int16 PCM bytes
        pcm = (audio * 32767).astype(np.int16).tobytes()

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=LANGUAGE_MAP.get(language, f"{language}-ZA"),
        )

        audio_content = speech.RecognitionAudio(content=pcm)

        response = client.recognize(config=config, audio=audio_content)

        parts = []
        for result in response.results:
            if result.alternatives:
                parts.append(result.alternatives[0].transcript)

        return " ".join(parts).strip()
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe_google.py -v`
Expected: ALL PASS.

Note: The tests mock the Google Cloud client, so `google-cloud-speech` doesn't need to be installed for tests to pass. However, verify the mocks match the real API shape.

**Step 5: Commit**

```
feat: add Google Cloud Speech-to-Text transcriber backend
```

---

### Task 3: Wire Per-Language Routing into Transcriber

**Files:**
- Modify: `daemon/transcribe.py:21-34` (Transcriber class)
- Test: `tests/unit/test_transcribe.py`

**Step 1: Write the failing tests**

Add to `tests/unit/test_transcribe.py`:

```python
class TestLanguageBackendRouting:
    """Verify per-language backend routing dispatches correctly."""

    @patch("mlx_whisper.transcribe")
    def test_default_language_uses_local_whisper(self, mock_transcribe):
        """English (no override) still uses local Whisper."""
        mock_transcribe.return_value = {"text": "hello world"}
        t = Transcriber(model_name="large-v3-turbo", backend="mlx",
                        language_backends={"af": {"backend": "google", "google_credentials": "/fake.json"}})
        t._model = "mlx"

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, language="en")

        mock_transcribe.assert_called_once()
        assert result == "hello world"

    def test_overridden_language_uses_google(self):
        """Afrikaans with google override routes to GoogleCloudTranscriber."""
        t = Transcriber(model_name="large-v3-turbo", backend="mlx",
                        language_backends={"af": {"backend": "google", "google_credentials": "/fake.json"}})
        t._model = "mlx"

        mock_google = MagicMock()
        mock_google.transcribe.return_value = "hallo wêreld"
        t._cloud_transcribers = {"af": mock_google}

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, language="af")

        mock_google.transcribe.assert_called_once()
        assert result == "hallo wêreld"

    @patch("mlx_whisper.transcribe")
    def test_empty_language_backends_uses_default(self, mock_transcribe):
        """Empty language_backends dict uses default backend for all languages."""
        mock_transcribe.return_value = {"text": "toets"}
        t = Transcriber(model_name="large-v3-turbo", backend="mlx",
                        language_backends={})
        t._model = "mlx"

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, language="af")

        mock_transcribe.assert_called_once()
        assert result == "toets"

    def test_google_transcriber_lazy_created(self):
        """GoogleCloudTranscriber is created on first use, not at init."""
        t = Transcriber(model_name="large-v3-turbo", backend="mlx",
                        language_backends={"af": {"backend": "google", "google_credentials": "/fake.json"}})
        assert t._cloud_transcribers == {}
```

**Step 2: Run test to verify it fails**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe.py::TestLanguageBackendRouting -v`
Expected: FAIL — `Transcriber.__init__()` does not accept `language_backends`.

**Step 3: Write minimal implementation**

Modify `daemon/transcribe.py`:

```python
class Transcriber:
    """Transcribes audio using Whisper (faster-whisper or MLX backend)."""

    # ... MLX_MODELS stays the same ...

    def __init__(self, model_name: str = "base.en", device: str = "cpu",
                 backend: str = "faster-whisper", language_backends: dict = None):
        self.model_name = model_name
        self.device = device
        self.backend = backend
        self._model = None
        self._model_dir = os.path.expanduser("~/.claude-voice/models/whisper")
        self.language_backends = language_backends or {}
        self._cloud_transcribers = {}

    # ... _ensure_model stays the same ...

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, language: str = "en",
                   initial_prompt: Optional[str] = None) -> str:
        """Transcribe audio to text."""
        if len(audio) == 0:
            return ""

        # Check for per-language backend override
        if language in self.language_backends:
            return self._transcribe_cloud(audio, language=language, sample_rate=sample_rate)

        self._ensure_model()

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        if self.backend == "mlx":
            return self._transcribe_mlx(audio, language=language, initial_prompt=initial_prompt)
        else:
            return self._transcribe_faster_whisper(audio, language=language, initial_prompt=initial_prompt)

    def _transcribe_cloud(self, audio: np.ndarray, language: str,
                          sample_rate: int = 16000) -> str:
        """Route to cloud transcription backend for this language."""
        if language not in self._cloud_transcribers:
            config = self.language_backends[language]
            backend = config.get("backend")
            if backend == "google":
                from daemon.transcribe_google import GoogleCloudTranscriber
                self._cloud_transcribers[language] = GoogleCloudTranscriber(
                    credentials_path=config["google_credentials"]
                )
            else:
                print(f"WARNING: Unknown cloud backend '{backend}' for language '{language}', "
                      f"falling back to local Whisper")
                # Remove from language_backends so we don't hit this warning again
                del self.language_backends[language]
                return self.transcribe(audio, sample_rate=sample_rate, language=language)

        return self._cloud_transcribers[language].transcribe(
            audio, language=language, sample_rate=sample_rate
        )

    # ... _transcribe_mlx and _transcribe_faster_whisper stay the same ...
```

**Step 4: Run test to verify it passes**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe.py -v`
Expected: ALL PASS (including existing tests).

**Step 5: Commit**

```
feat: add per-language backend routing to Transcriber
```

---

### Task 4: Wire Config Through Main Daemon

**Files:**
- Modify: `daemon/main.py:144-148` (Transcriber construction)
- Modify: `daemon/main.py:268-278` (reload_config transcriber section)

**Step 1: Write the failing test**

This is a wiring-only change (passing an existing config field to an existing constructor parameter). Verify by reading the code change. No dedicated unit test — the existing integration path (config → daemon → transcriber) is tested by the config and transcriber tests above.

However, write a quick smoke test in `tests/unit/test_transcribe.py`:

```python
class TestTranscriberBackwardCompat:
    """Existing Transcriber usage without language_backends still works."""

    @patch("mlx_whisper.transcribe")
    def test_no_language_backends_arg(self, mock_transcribe):
        """Transcriber() with no language_backends argument works."""
        mock_transcribe.return_value = {"text": "hello"}
        t = Transcriber(model_name="large-v3-turbo", backend="mlx")
        t._model = "mlx"

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, language="en")
        assert result == "hello"
```

**Step 2: Run test to verify it passes (backward compat already works)**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe.py::TestTranscriberBackwardCompat -v`
Expected: PASS (the default `language_backends=None` → `{}` already handles this).

**Step 3: Wire config through daemon**

In `daemon/main.py`, modify the Transcriber construction (~line 144):

```python
        self.transcriber = Transcriber(
            model_name=self.config.transcription.model,
            device=self.config.transcription.device,
            backend=self.config.transcription.backend,
            language_backends=self.config.transcription.language_backends,
        )
```

In `daemon/main.py`, modify the reload_config transcriber section (~line 268):

After the existing transcriber model/backend reset block, add language_backends update:

```python
        # Transcriber: reset model if model name or backend changed
        if (new.transcription.model != old.transcription.model
                or new.transcription.backend != old.transcription.backend):
            self.transcriber._model = None
            self.transcriber.model_name = new.transcription.model
            self.transcriber.backend = new.transcription.backend
            self.transcriber.device = new.transcription.device
            changed.append("transcriber(model reset)")
        elif new.transcription.device != old.transcription.device:
            self.transcriber.device = new.transcription.device
            changed.append("transcriber(device)")

        # Update language_backends (hot-reloadable)
        if new.transcription.language_backends != old.transcription.language_backends:
            self.transcriber.language_backends = new.transcription.language_backends
            self.transcriber._cloud_transcribers = {}  # Force re-creation
            changed.append("transcriber(language_backends)")
```

**Step 4: Run all tests**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS.

**Step 5: Commit**

```
feat: wire language_backends config through daemon to transcriber
```

---

### Task 5: Update Config Example and Install Script

**Files:**
- Modify: `config.yaml.example:10-16`
- Modify: `install.sh:224` (pip install line — add google-cloud-speech as optional)

**Step 1: Update config.yaml.example**

Add the `language_backends` section with comments explaining setup:

```yaml
transcription:
  model: "large-v3-turbo"       # tiny.en, base.en, small.en, medium.en, large-v3, large-v3-turbo
  language: "en"
  device: "cpu"                # cpu or cuda (for faster-whisper)
  backend: "mlx"               # "faster-whisper" or "mlx" (mlx is faster on Apple Silicon)
  extra_languages: ["af"]        # Additional languages to cycle through (e.g. ["af", "de"])
  word_replacements:              # Fix consistently misheard words (case-insensitive, whole-word)
    "clawd": "Claude"             # Key = what Whisper hears, Value = what you actually said
  # Per-language backend overrides — use a cloud API for specific languages
  # while keeping free local Whisper for English
  # language_backends:
  #   af:                         # Language code to override
  #     backend: "google"         # "google" = Google Cloud Speech-to-Text
  #     google_credentials: "~/.claude-voice/google-credentials.json"
  #     # Setup: 1) Create project at console.cloud.google.com
  #     #        2) Enable "Cloud Speech-to-Text API"
  #     #        3) Create service account key (JSON) and save to path above
  #     #        4) pip install google-cloud-speech in ~/.claude-voice/venv/
  #     # Pricing: $0.024/min ($1.44/hr), 60 min/month free tier
```

**Step 2: Update install.sh**

After the existing STT backend install section (~line 303), add a note about Google Cloud:

```bash
# Note: Google Cloud STT is optional (for non-English language backends)
# Install with: pip install google-cloud-speech
# See config.yaml.example for setup instructions
```

Do NOT auto-install `google-cloud-speech` — it's only needed when the user configures a Google backend. The `GoogleCloudTranscriber` lazy-imports it, so missing the package gives a clear import error at first use.

**Step 3: Run all tests (no regressions)**

Run: `~/.claude-voice/venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS.

**Step 4: Commit**

```
docs: add language_backends config example and Google Cloud STT setup instructions
```

---

### Task 6: Deploy and Manual Test

**Step 1: Install google-cloud-speech in the venv**

```bash
~/.claude-voice/venv/bin/pip install google-cloud-speech
```

**Step 2: Deploy**

```bash
./deploy.sh
```

**Step 3: Restart daemon**

```bash
~/.claude-voice/claude-voice-daemon restart
```

**Step 4: Configure**

Edit `~/.claude-voice/config.yaml` and add:

```yaml
transcription:
  language_backends:
    af:
      backend: "google"
      google_credentials: "~/.claude-voice/google-credentials.json"
```

Place the Google service account JSON at the configured path.

**Step 5: Manual test**

1. Cycle to Afrikaans language (press language hotkey)
2. Hold push-to-talk and speak Afrikaans
3. Verify transcription output is accurate Afrikaans (not Dutch)
4. Cycle back to English
5. Hold push-to-talk and speak English
6. Verify English still uses local Whisper (fast, no API call)

**Step 6: Commit any fixes from manual testing**

---

### Task 7: Final Test Suite Run and Cleanup

**Step 1: Run full test suite**

```bash
~/.claude-voice/venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS.

**Step 2: Run coverage check**

```bash
~/.claude-voice/venv/bin/python -m pytest tests/ --cov=daemon --cov-report=term-missing
```

Verify `daemon/transcribe_google.py` and the new routing code in `daemon/transcribe.py` have reasonable coverage.

**Step 3: Final commit if any cleanup needed**

---

## Summary of Changes

| File | Action | Description |
|------|--------|-------------|
| `daemon/config.py` | Modify | Add `language_backends` field to `TranscriptionConfig` |
| `daemon/transcribe.py` | Modify | Add `language_backends` param, routing logic, `_transcribe_cloud()` |
| `daemon/transcribe_google.py` | Create | `GoogleCloudTranscriber` class with Google Cloud STT API |
| `daemon/main.py` | Modify | Pass `language_backends` to Transcriber, handle in `reload_config` |
| `config.yaml.example` | Modify | Document `language_backends` with setup instructions |
| `install.sh` | Modify | Add note about optional google-cloud-speech dependency |
| `tests/unit/test_config.py` | Modify | Add `TestLanguageBackends` tests |
| `tests/unit/test_transcribe.py` | Modify | Add routing and backward compat tests |
| `tests/unit/test_transcribe_google.py` | Create | Full test suite for GoogleCloudTranscriber |