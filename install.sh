#!/bin/bash
#
# Claude Voice Interface Installer
# Installs voice input (push-to-talk) and voice output (TTS) for Claude Code
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.claude-voice"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

echo "=================================="
echo "Claude Voice Interface Installer"
echo "=================================="
echo ""

# Check for macOS (required for afplay)
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Warning: This tool is designed for macOS. TTS playback uses afplay."
    echo "On other platforms, you may need to modify hooks/speak-response.py"
    echo ""
fi

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"/{daemon,models/whisper,models/piper,logs}
mkdir -p "$CLAUDE_HOOKS_DIR"

# Copy daemon files
echo "Installing daemon modules..."
cp "$SCRIPT_DIR"/daemon/*.py "$INSTALL_DIR/daemon/"
cp "$SCRIPT_DIR/claude-voice-daemon" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/claude-voice-daemon"

# Copy config if it doesn't exist
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    echo "Creating default config..."
    cp "$SCRIPT_DIR/config.yaml.example" "$INSTALL_DIR/config.yaml"
else
    echo "Config already exists, keeping existing config.yaml"
fi

# Create virtual environment
if [ ! -d "$INSTALL_DIR/venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
fi

source "$INSTALL_DIR/venv/bin/activate"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip -q
pip install pynput sounddevice numpy pyyaml piper-tts -q

# Ask about speech-to-text backend
echo ""
echo "Speech-to-text backend options:"
echo "  1) faster-whisper (CPU, cross-platform)"
echo "  2) mlx-whisper (Apple Silicon, faster)"
echo ""

# Check if running on Apple Silicon
if [[ "$(uname -m)" == "arm64" ]]; then
    read -p "Install mlx-whisper for Apple Silicon? [Y/n]: " USE_MLX
    USE_MLX=${USE_MLX:-Y}
else
    USE_MLX="n"
fi

if [[ "$USE_MLX" =~ ^[Yy]$ ]]; then
    echo "Installing mlx-whisper..."
    pip install mlx-whisper -q
    # Update config to use mlx backend
    if grep -q 'backend: "faster-whisper"' "$INSTALL_DIR/config.yaml"; then
        sed -i '' 's/backend: "faster-whisper"/backend: "mlx"/' "$INSTALL_DIR/config.yaml"
    fi
else
    echo "Installing faster-whisper..."
    pip install faster-whisper -q
fi

# Download default voice model
echo ""
VOICE_MODEL="en_GB-alan-medium"
VOICE_DIR="$INSTALL_DIR/models/piper"

if [ ! -f "$VOICE_DIR/$VOICE_MODEL.onnx" ]; then
    echo "Downloading Piper voice model ($VOICE_MODEL)..."
    curl -L -o "$VOICE_DIR/$VOICE_MODEL.onnx" \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/$VOICE_MODEL.onnx" 2>/dev/null
    curl -L -o "$VOICE_DIR/$VOICE_MODEL.onnx.json" \
      "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/$VOICE_MODEL.onnx.json" 2>/dev/null
else
    echo "Voice model already downloaded"
fi

# Install Claude Code hook
echo "Installing Claude Code hook..."
cp "$SCRIPT_DIR/hooks/speak-response.py" "$CLAUDE_HOOKS_DIR/"
chmod +x "$CLAUDE_HOOKS_DIR/speak-response.py"

# Update Claude settings for hook
echo "Configuring Claude Code settings..."
if [ -f "$CLAUDE_SETTINGS" ]; then
    # Check if Stop hook already exists
    if grep -q '"Stop"' "$CLAUDE_SETTINGS"; then
        echo "Stop hook already configured in settings.json"
    else
        # Add the Stop hook to existing settings
        python3 << 'EOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
with open(settings_path, 'r') as f:
    settings = json.load(f)

if 'hooks' not in settings:
    settings['hooks'] = {}

settings['hooks']['Stop'] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": "~/.claude/hooks/speak-response.py"
    }]
}]

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)

print("Added Stop hook to settings.json")
EOF
    fi
else
    # Create new settings file
    cat > "$CLAUDE_SETTINGS" << 'EOF'
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/speak-response.py"
          }
        ]
      }
    ]
  }
}
EOF
    echo "Created settings.json with Stop hook"
fi

# Add shell aliases
echo ""
echo "To add convenient aliases, add these to your ~/.bashrc or ~/.zshrc:"
echo ""
echo '  alias cv="~/.claude-voice/claude-voice-daemon"'
echo '  alias cvf="~/.claude-voice/claude-voice-daemon foreground"'
echo '  alias cvs="~/.claude-voice/claude-voice-daemon --silent foreground"'
echo ""

# macOS accessibility note
echo "=================================="
echo "Installation complete!"
echo "=================================="
echo ""
echo "IMPORTANT: macOS Accessibility Permission Required"
echo "The daemon needs accessibility permissions to detect keyboard input."
echo ""
echo "Grant access in: System Settings > Privacy & Security > Accessibility"
echo "Add your terminal app (Terminal, iTerm2, etc.)"
echo ""
echo "Quick start:"
echo "  1. Start the daemon:  ~/.claude-voice/claude-voice-daemon foreground"
echo "  2. Start Claude Code:  claude"
echo "  3. Hold Right Alt and speak, release to transcribe"
echo ""
