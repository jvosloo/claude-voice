# Parakeet Transcription Backend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add NVIDIA Parakeet ASR as a new transcription backend via `parakeet-mlx`, giving dramatically faster and more accurate local transcription on Apple Silicon.

**Architecture:** Extends the existing `Transcriber` class with a `_transcribe_parakeet()` method, routed when `backend: "parakeet"` is configured. Per-language cloud overrides still take priority. The `parakeet-mlx` library is lazy-imported inside the method.

**Tech Stack:** `parakeet-mlx` (Python, MLX framework, Apple Silicon)

---

### Task 1: Install parakeet-mlx dependency

**Files:**
- Modify: `requirements.txt` (if it exists) or install directly

**Step 1: Install parakeet-mlx into the venv**

```bash
~/.claude-voice/venv/bin/pip install parakeet-mlx
```

**Step 2: Verify installation**

```bash
~/.claude-voice/venv/bin/python -c "from parakeet_mlx import from_pretrained; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: install parakeet-mlx dependency"
```

---

### Task 2: Write failing tests for Parakeet transcription

**Files:**
- Modify: `tests/unit/test_transcribe.py`

**Step 1: Write failing tests**

Add a new test class `TestParakeetBackend` to `tests/unit/test_transcribe.py`:

```python
class TestParakeetBackend:
    """Verify Parakeet transcription backend routing and behavior."""

    def _make_transcriber(self):
        t = Transcriber(model_name="mlx-community/parakeet-tdt-0.6b-v3", backend="parakeet")
        return t

    @patch("parakeet_mlx.from_pretrained")
    def test_parakeet_transcribes_audio(self, mock_from_pretrained):
        """Parakeet backend transcribes audio and returns text."""
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "  hello world  "
        mock_model.transcribe.return_value = mock_result
        mock_from_pretrained.return_value = mock_model

        t = self._make_transcriber()
        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio)

        mock_from_pretrained.assert_called_once_with("mlx-community/parakeet-tdt-0.6b-v3")
        mock_model.transcribe.assert_called_once()
        assert result == "hello world"

    @patch("parakeet_mlx.from_pretrained")
    def test_parakeet_model_loaded_once(self, mock_from_pretrained):
        """Model is lazy-loaded on first call and reused."""
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "hello"
        mock_model.transcribe.return_value = mock_result
        mock_from_pretrained.return_value = mock_model

        t = self._make_transcriber()
        audio = np.zeros(16000, dtype=np.float32)
        t.transcribe(audio)
        t.transcribe(audio)

        # from_pretrained called only once (model reused)
        mock_from_pretrained.assert_called_once()
        assert mock_model.transcribe.call_count == 2

    @patch("parakeet_mlx.from_pretrained")
    def test_parakeet_ignores_initial_prompt(self, mock_from_pretrained):
        """Parakeet does not pass initial_prompt (unsupported)."""
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "hello Claude"
        mock_model.transcribe.return_value = mock_result
        mock_from_pretrained.return_value = mock_model

        t = self._make_transcriber()
        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, initial_prompt="Claude, pytest")

        # transcribe called without initial_prompt kwarg
        call_kwargs = mock_model.transcribe.call_args[1] if mock_model.transcribe.call_args[1] else {}
        assert "initial_prompt" not in call_kwargs
        assert result == "hello Claude"

    def test_parakeet_cloud_override_still_works(self):
        """Per-language cloud override takes priority over parakeet backend."""
        t = Transcriber(
            model_name="mlx-community/parakeet-tdt-0.6b-v3",
            backend="parakeet",
            language_backends={"af": {"backend": "openai"}},
            openai_api_key="sk-test",
        )

        mock_openai = MagicMock()
        mock_openai.transcribe.return_value = "hallo wêreld"
        t._cloud_transcribers = {"af": mock_openai}

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, language="af")

        mock_openai.transcribe.assert_called_once()
        assert result == "hallo wêreld"

    @patch("parakeet_mlx.from_pretrained")
    def test_parakeet_empty_audio_returns_empty(self, mock_from_pretrained):
        """Empty audio returns empty string without loading model."""
        t = self._make_transcriber()
        result = t.transcribe(np.array([], dtype=np.float32))

        mock_from_pretrained.assert_not_called()
        assert result == ""
```

**Step 2: Run tests to verify they fail**

```bash
~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe.py::TestParakeetBackend -v
```

Expected: FAIL — `_transcribe_parakeet` method doesn't exist yet.

**Step 3: Commit**

```bash
git add tests/unit/test_transcribe.py
git commit -m "test: add failing tests for Parakeet transcription backend"
```

---

### Task 3: Implement `_transcribe_parakeet()` and routing

**Files:**
- Modify: `daemon/transcribe.py`

**Step 1: Add _transcribe_parakeet method and update routing**

In `daemon/transcribe.py`, add the new method to the `Transcriber` class and update `_ensure_model()` and `transcribe()` to route to it:

In `_ensure_model()`, add a branch for `"parakeet"`:
```python
elif self.backend == "parakeet":
    with Spinner(f"Loading Parakeet model: {self.model_name}"):
        from parakeet_mlx import from_pretrained
        self._model = from_pretrained(self.model_name)
```

In `transcribe()`, add routing before the existing backend check:
```python
if self.backend == "parakeet":
    return self._transcribe_parakeet(audio)
```

Add the new method:
```python
def _transcribe_parakeet(self, audio: np.ndarray) -> str:
    """Transcribe using Parakeet MLX."""
    self._ensure_model()
    result = self._model.transcribe(audio)
    return result.text.strip()
```

**Step 2: Run tests to verify they pass**

```bash
~/.claude-voice/venv/bin/python -m pytest tests/unit/test_transcribe.py::TestParakeetBackend -v
```

Expected: All 5 tests PASS.

**Step 3: Run full test suite to check for regressions**

```bash
~/.claude-voice/venv/bin/python -m pytest tests/ -v
```

Expected: All existing tests still pass.

**Step 4: Commit**

```bash
git add daemon/transcribe.py
git commit -m "feat: add Parakeet MLX transcription backend"
```

---

### Task 4: Update config and example

**Files:**
- Modify: `config.yaml.example`

**Step 1: Update config.yaml.example**

Update the `transcription` section comments to document the new backend option:
- Change the `backend` comment from `"faster-whisper" or "mlx"` to `"faster-whisper", "mlx", or "parakeet"`
- Add a comment block showing parakeet-specific config example

**Step 2: Commit**

```bash
git add config.yaml.example
git commit -m "docs: add parakeet backend option to config example"
```

---

### Task 5: Deploy and manual test

**Step 1: Deploy**

```bash
./deploy.sh
```

**Step 2: Update user's config.yaml to use parakeet**

The user should update `~/.claude-voice/config.yaml`:
```yaml
transcription:
  backend: "parakeet"
  model: "mlx-community/parakeet-tdt-0.6b-v3"
```

**Step 3: Restart daemon and test**

```bash
~/.claude-voice/claude-voice-daemon restart
```

Test by pressing the hotkey and speaking. The first transcription will download the model (~1.2GB). Subsequent transcriptions should be fast.

**Step 4: Commit any fixes if needed**
