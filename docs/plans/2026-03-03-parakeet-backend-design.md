# Parakeet Transcription Backend

## Summary

Add NVIDIA's Parakeet ASR model as a new local transcription backend via `parakeet-mlx`, running natively on Apple Silicon. Parakeet tops the Hugging Face Open ASR Leaderboard (6.05% WER) and is dramatically faster than Whisper — transcribing ~68 minutes of audio in ~62 seconds on an M3.

## Motivation

Inspired by [Speaky (speakink)](https://github.com/bedriyan/speakink), which uses Parakeet as its default transcription engine. Parakeet's FastConformer architecture processes audio in a single forward pass rather than autoregressively, yielding both better accuracy and speed.

## Design

### Configuration

```yaml
transcription:
  backend: "parakeet"                              # new option
  model: "mlx-community/parakeet-tdt-0.6b-v3"     # HuggingFace repo name
  language: "en"
  extra_languages: ["af"]
  language_backends:
    af:
      backend: "openai"                            # Afrikaans routes to cloud
```

### Backend routing

The existing `Transcriber.transcribe()` method routes to `_transcribe_parakeet()` when `self.backend == "parakeet"`. Per-language cloud overrides still take priority (checked first).

### Key differences from Whisper

| Aspect | Whisper | Parakeet |
|--------|---------|----------|
| Architecture | Autoregressive transformer | FastConformer + TDT (single forward pass) |
| `initial_prompt` | Supported | Not supported (no mechanism) |
| `word_replacements` | Works (post-processing) | Works (post-processing) |
| Language | Passed explicitly | Auto-detected (v3) or English-only (v2) |
| VAD | faster-whisper has built-in filter | Not needed |
| Model size | ~1.5-3GB depending on variant | ~2GB |
| License | MIT (whisper), varies (backends) | CC-BY-4.0 |

### What stays the same

- Language cycling hotkey
- Per-language cloud routing (Afrikaans -> OpenAI)
- Word replacements post-processing
- Silence detection in main.py (pre-transcription)
- Audio format: 16kHz mono float32

### What changes

1. New pip dependency: `parakeet-mlx`
2. New backend value `"parakeet"` accepted in `TranscriptionConfig.backend`
3. New method `Transcriber._transcribe_parakeet()`
4. Model name uses HuggingFace repo names directly (not short aliases)
5. `initial_prompt` parameter ignored silently (word_replacements still apply)

### Available models

| Model | Languages | Notes |
|-------|-----------|-------|
| `mlx-community/parakeet-tdt-0.6b-v2` | English only | Best for English-only use |
| `mlx-community/parakeet-tdt-0.6b-v3` | 25 European languages | No Afrikaans |

### Language support gap

Parakeet v3 supports 25 European languages but not Afrikaans. The existing `language_backends` routing handles this — Afrikaans routes to OpenAI cloud, everything else uses Parakeet locally.

## Dependencies

- `parakeet-mlx` (pip install)
- Requires Apple Silicon (MLX framework)
