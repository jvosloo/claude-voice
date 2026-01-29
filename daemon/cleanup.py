"""LLM-based transcription cleanup using Ollama."""

import subprocess
import time


class TranscriptionCleaner:
    """Cleans up Whisper transcriptions using a local LLM via Ollama."""

    def __init__(self, model_name: str = "qwen2.5:1.5b", debug: bool = False):
        self.model_name = model_name
        self.debug = debug
        self._ready = False

    def ensure_ready(self) -> bool:
        """Check Ollama is installed and model is available. Auto-pulls model if needed."""
        print("Checking Ollama for transcription cleanup...")

        # Check if Ollama is installed
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                print("  ✗ Ollama not found. Install with:")
                print("      brew install ollama")
                print("      brew services start ollama")
                print("  → Transcription cleanup disabled, using raw Whisper output")
                return False
            print("  ✓ Ollama installed")
        except FileNotFoundError:
            print("  ✗ Ollama not found. Install with:")
            print("      brew install ollama")
            print("      brew services start ollama")
            print("  → Transcription cleanup disabled, using raw Whisper output")
            return False
        except subprocess.TimeoutExpired:
            print("  ✗ Ollama check timed out")
            print("  → Transcription cleanup disabled, using raw Whisper output")
            return False

        # Check if model is available
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if self.model_name in result.stdout:
                print(f"  ✓ Model {self.model_name} ready")
                self._ready = True
                return True
        except (subprocess.TimeoutExpired, Exception) as e:
            print(f"  ✗ Error checking models: {e}")
            print("  → Transcription cleanup disabled, using raw Whisper output")
            return False

        # Model not found, try to pull it
        print(f"  ↓ Pulling model {self.model_name} (this may take a few minutes)...")
        try:
            result = subprocess.run(
                ["ollama", "pull", self.model_name],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes for large models
            )
            if result.returncode == 0:
                print(f"  ✓ Model {self.model_name} ready")
                self._ready = True
                return True
            else:
                print(f"  ✗ Failed to pull model: {result.stderr}")
                print("  → Transcription cleanup disabled, using raw Whisper output")
                return False
        except subprocess.TimeoutExpired:
            print("  ✗ Model download timed out")
            print("  → Transcription cleanup disabled, using raw Whisper output")
            return False

    def cleanup(self, text: str) -> str:
        """Clean up transcription using the LLM. Returns original on failure."""
        if not self._ready or not text:
            return text

        prompt = f'''Clean up this speech-to-text transcription:
- Fix misheard words
- Add punctuation and sentence breaks
- Fix capitalization
- Fix minor grammar errors (missing words like "I'm" → "I am")
- Do NOT rephrase or change the meaning

Return only the cleaned text, no commentary.

{text}'''

        try:
            start_time = time.time()
            result = subprocess.run(
                ["ollama", "run", self.model_name, prompt],
                capture_output=True,
                text=True,
                timeout=10,
            )
            elapsed = time.time() - start_time

            if result.returncode != 0:
                return text

            cleaned = result.stdout.strip()

            if self.debug:
                print(f"Cleanup: {elapsed:.2f}s")

            # Handle empty response
            if not cleaned:
                return text

            # Strip "Output:" prefix if model included it
            if cleaned.lower().startswith("output:"):
                cleaned = cleaned[7:].strip()

            # Strip surrounding quotes if LLM added them
            if (cleaned.startswith('"') and cleaned.endswith('"')) or \
               (cleaned.startswith("'") and cleaned.endswith("'")):
                cleaned = cleaned[1:-1]

            return cleaned

        except subprocess.TimeoutExpired:
            return text
        except Exception:
            return text
