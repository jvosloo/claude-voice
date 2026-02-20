"""Tests for daemon/transcribe.py — initial_prompt passthrough."""

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from daemon.transcribe import Transcriber


class TestInitialPromptMLX:
    """Verify initial_prompt is forwarded to mlx_whisper.transcribe()."""

    def _make_transcriber(self):
        t = Transcriber(model_name="large-v3-turbo", backend="mlx")
        t._model = "mlx"  # skip lazy-load
        return t

    @patch("mlx_whisper.transcribe")
    def test_initial_prompt_passed_to_mlx(self, mock_transcribe):
        mock_transcribe.return_value = {"text": "hello Claude"}
        t = self._make_transcriber()

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, initial_prompt="Claude, pytest, TypeScript")

        mock_transcribe.assert_called_once()
        call_kwargs = mock_transcribe.call_args[1]
        assert call_kwargs["initial_prompt"] == "Claude, pytest, TypeScript"
        assert result == "hello Claude"

    @patch("mlx_whisper.transcribe")
    def test_no_initial_prompt_when_none(self, mock_transcribe):
        mock_transcribe.return_value = {"text": "hello"}
        t = self._make_transcriber()

        audio = np.zeros(16000, dtype=np.float32)
        t.transcribe(audio)

        call_kwargs = mock_transcribe.call_args[1]
        assert "initial_prompt" not in call_kwargs


class TestConditionOnPreviousText:
    """Verify condition_on_previous_text=False is always passed to prevent hallucination loops."""

    @patch("mlx_whisper.transcribe")
    def test_mlx_disables_condition_on_previous_text(self, mock_transcribe):
        mock_transcribe.return_value = {"text": "hello"}
        t = Transcriber(model_name="large-v3-turbo", backend="mlx")
        t._model = "mlx"

        audio = np.zeros(16000, dtype=np.float32)
        t.transcribe(audio)

        call_kwargs = mock_transcribe.call_args[1]
        assert call_kwargs["condition_on_previous_text"] is False

    def test_faster_whisper_disables_condition_on_previous_text(self):
        t = Transcriber(model_name="base.en", backend="faster-whisper")
        mock_model = MagicMock()
        segment = MagicMock()
        segment.text = "hello"
        mock_model.transcribe.return_value = ([segment], MagicMock())
        t._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        t.transcribe(audio)

        call_kwargs = t._model.transcribe.call_args[1]
        assert call_kwargs["condition_on_previous_text"] is False


class TestInitialPromptFasterWhisper:
    """Verify initial_prompt is forwarded to faster-whisper model.transcribe()."""

    def _make_transcriber(self):
        t = Transcriber(model_name="base.en", backend="faster-whisper")
        # Mock the faster-whisper model
        mock_model = MagicMock()
        segment = MagicMock()
        segment.text = "hello Claude"
        mock_model.transcribe.return_value = ([segment], MagicMock())
        t._model = mock_model
        return t

    def test_initial_prompt_passed_to_faster_whisper(self):
        t = self._make_transcriber()

        audio = np.zeros(16000, dtype=np.float32)
        result = t.transcribe(audio, initial_prompt="Claude, pytest")

        call_kwargs = t._model.transcribe.call_args[1]
        assert call_kwargs["initial_prompt"] == "Claude, pytest"
        assert result == "hello Claude"

    def test_no_initial_prompt_when_none(self):
        t = self._make_transcriber()

        audio = np.zeros(16000, dtype=np.float32)
        t.transcribe(audio)

        call_kwargs = t._model.transcribe.call_args[1]
        assert "initial_prompt" not in call_kwargs
