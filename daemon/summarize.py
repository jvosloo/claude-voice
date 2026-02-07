"""LLM-based response summarization for narrate mode using Ollama."""

import re
import subprocess
import time

# Style-specific prompts for summarization
STYLE_PROMPTS = {
    "brief": """Summarize what was done in 1-2 short sentences. Focus on actions and outcomes.
Be direct: "I did X" not "The assistant did X". Omit technical details.
Output ONLY the summary. No preamble, no "Sure", no "Here's a summary".""",

    "conversational": """Give a natural, spoken recap of what happened. Use casual language like you're
explaining to a colleague. Start with context if helpful. 2-4 sentences max.
Be direct: "I did X" not "The assistant did X".
Output ONLY the summary. No preamble, no "Sure", no "Here's a summary".""",

    "bullets": """Summarize as 2-4 brief spoken bullet points. Start each with "First," "Second,"
"Then," "Finally," etc. Keep each point under 10 words.
Be direct: "Fixed the bug" not "The assistant fixed the bug".
Output ONLY the summary. No preamble, no "Sure", no "Here's a summary".""",
}

# Minimum text length to bother summarizing (chars)
MIN_TEXT_LENGTH = 20


def filter_for_summarization(text: str) -> str:
    """Remove code, paths, and technical noise before summarization."""
    if not text:
        return text

    # Remove code blocks (```...```)
    text = re.sub(r'```[\s\S]*?```', '', text)

    # Remove inline code (`...`)
    text = re.sub(r'`[^`]+`', '', text)

    # Remove file paths (common patterns)
    text = re.sub(r'(?:^|\s)[/~][\w./-]+(?:\s|$)', ' ', text)
    text = re.sub(r'\b\w+\.(py|js|ts|tsx|go|rs|java|cpp|c|h|md|yaml|json|toml)\b', '', text)

    # Remove stack traces (lines starting with "at " or "File ")
    text = re.sub(r'^\s*(at |File |Traceback).*$', '', text, flags=re.MULTILINE)

    # Remove error codes and hex addresses
    text = re.sub(r'\b0x[0-9a-fA-F]+\b', '', text)
    text = re.sub(r'\berror\s*[:-]?\s*\d+\b', '', text, flags=re.IGNORECASE)

    # Remove markdown formatting
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # Italic
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)  # Headers
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)  # List items

    # Collapse whitespace
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()


class ResponseSummarizer:
    """Summarizes Claude responses using a local LLM via Ollama."""

    def __init__(self, model_name: str = "qwen2.5:1.5b", debug: bool = False):
        self.model_name = model_name
        self.debug = debug
        self._ready = False

    def ensure_ready(self) -> bool:
        """Check Ollama is installed and model is available. Auto-pulls model if needed."""
        print("Checking Ollama for response summarization...")

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
                print("  → Narrate summarization disabled, using notify fallback")
                return False
            print("  ✓ Ollama installed")
        except FileNotFoundError:
            print("  ✗ Ollama not found. Install with:")
            print("      brew install ollama")
            print("      brew services start ollama")
            print("  → Narrate summarization disabled, using notify fallback")
            return False
        except subprocess.TimeoutExpired:
            print("  ✗ Ollama check timed out")
            print("  → Narrate summarization disabled, using notify fallback")
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
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"  ✗ Error checking models: {e}")
            print("  → Narrate summarization disabled, using notify fallback")
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
                print("  → Narrate summarization disabled, using notify fallback")
                return False
        except subprocess.TimeoutExpired:
            print("  ✗ Model download timed out")
            print("  → Narrate summarization disabled, using notify fallback")
            return False

    def summarize(self, text: str, style: str = "brief") -> str | None:
        """Summarize text using the LLM. Returns None on failure (caller should fallback).

        Args:
            text: The response text to summarize.
            style: One of "brief", "conversational", or "bullets".

        Returns:
            Summarized text, or None if summarization failed.
        """
        if not self._ready:
            return None

        # Filter technical content first
        filtered = filter_for_summarization(text)

        # Short text: speak directly without summarizing
        if len(filtered) < MIN_TEXT_LENGTH:
            return filtered if filtered else None

        # Get style-specific prompt (default to brief)
        style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["brief"])

        prompt = f'''{style_instruction}

Text to summarize:
"""
{filtered}
"""

Summary:'''

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
                return None

            summary = result.stdout.strip()

            if self.debug:
                print(f"Summarize ({style}): {elapsed:.2f}s")

            # Handle empty response
            if not summary:
                return None

            # Strip common LLM preamble prefixes
            for prefix in ("summary:", "output:", "here's", "sure,", "sure!", "sure.",
                           "here is", "here are"):
                if summary.lower().startswith(prefix):
                    summary = summary[len(prefix):].strip()

            # Strip surrounding quotes if LLM added them
            if (summary.startswith('"') and summary.endswith('"')) or \
               (summary.startswith("'") and summary.endswith("'")):
                summary = summary[1:-1]

            return summary if summary else None

        except subprocess.TimeoutExpired:
            return None  # LLM took too long
        except (subprocess.SubprocessError, OSError):
            return None  # Subprocess failed
