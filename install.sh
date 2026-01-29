#!/bin/bash
#
# Claude Voice Interface Installer
# Installs voice input (push-to-talk) and voice output (TTS) for Claude Code
# Safe to run multiple times - will update existing installation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.claude-voice"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# Set up logging - capture all output to log file while still showing on screen
mkdir -p "$INSTALL_DIR/logs"
LOG_FILE="$INSTALL_DIR/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "Install log: $LOG_FILE"
echo ""

# Detect if this is an update
IS_UPDATE=false
if [ -d "$INSTALL_DIR/daemon" ] && [ -f "$INSTALL_DIR/config.yaml" ]; then
    IS_UPDATE=true
fi

echo "=================================="
if [ "$IS_UPDATE" = true ]; then
    echo "Claude Voice Interface Updater"
else
    echo "Claude Voice Interface Installer"
fi
echo "=================================="
echo "$(date)"
echo ""

# Check for macOS (required for afplay)
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Warning: This tool is designed for macOS. TTS playback uses afplay."
    echo "On other platforms, you may need to modify hooks/speak-response.py"
    echo ""
fi

# Stop running daemon before updating (check both PID file and running processes)
if [ "$IS_UPDATE" = true ]; then
    DAEMON_STOPPED=false

    # Check PID file first (background mode)
    if [ -f "$INSTALL_DIR/daemon.pid" ]; then
        PID=$(cat "$INSTALL_DIR/daemon.pid")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping running daemon (PID: $PID)..."
            kill "$PID" 2>/dev/null || true
            DAEMON_STOPPED=true
        fi
        rm -f "$INSTALL_DIR/daemon.pid"
    fi

    # Also check for foreground daemons (no PID file)
    if pgrep -f "claude-voice/daemon/main.py" >/dev/null 2>&1; then
        if [ "$DAEMON_STOPPED" = false ]; then
            echo "Stopping running daemon..."
        fi
        pkill -f "claude-voice/daemon/main.py" 2>/dev/null || true
        DAEMON_STOPPED=true
    fi

    if [ "$DAEMON_STOPPED" = true ]; then
        sleep 1
    fi
fi

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"/{daemon,models/whisper,models/piper,logs}
mkdir -p "$CLAUDE_HOOKS_DIR"

# Copy daemon files (always update these)
if [ "$IS_UPDATE" = true ]; then
    echo "Updating daemon modules..."
else
    echo "Installing daemon modules..."
fi
cp "$SCRIPT_DIR"/daemon/*.py "$INSTALL_DIR/daemon/"
cp "$SCRIPT_DIR/claude-voice-daemon" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/claude-voice-daemon"

# Handle config file
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    echo "Creating default config..."
    cp "$SCRIPT_DIR/config.yaml.example" "$INSTALL_DIR/config.yaml"
else
    echo "Keeping existing config.yaml"
    # Always update the example file so users can see new options
    cp "$SCRIPT_DIR/config.yaml.example" "$INSTALL_DIR/config.yaml.example"
    # Check if example has new options
    if ! diff -q "$INSTALL_DIR/config.yaml" "$INSTALL_DIR/config.yaml.example" >/dev/null 2>&1; then
        echo "  Note: config.yaml.example updated - check for new options"
    fi
fi

# Create or reuse virtual environment
if [ ! -d "$INSTALL_DIR/venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
else
    echo "Using existing virtual environment..."
fi

source "$INSTALL_DIR/venv/bin/activate"

# Install/upgrade Python dependencies
if [ "$IS_UPDATE" = true ]; then
    echo "Updating Python dependencies..."
else
    echo "Installing Python dependencies..."
fi
pip install --upgrade pip -q
pip install --upgrade pynput sounddevice pyyaml -q
echo "  Core dependencies installed"

# Determine STT backend - check existing config on updates
CURRENT_BACKEND=""
if [ "$IS_UPDATE" = true ] && [ -f "$INSTALL_DIR/config.yaml" ]; then
    # Extract value between quotes: backend: "mlx" -> mlx
    CURRENT_BACKEND=$(grep -E '^\s*backend:' "$INSTALL_DIR/config.yaml" | sed 's/.*backend:[[:space:]]*"\([^"]*\)".*/\1/')
fi

if [ -n "$CURRENT_BACKEND" ]; then
    echo ""
    echo "Updating speech-to-text backend ($CURRENT_BACKEND)... (this may take a moment)"
    if [ "$CURRENT_BACKEND" = "mlx" ]; then
        pip install --upgrade mlx-whisper -q
    else
        pip install --upgrade faster-whisper -q
    fi
    echo "  Speech-to-text backend updated"
else
    # Fresh install - ask about backend
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
        echo "Installing mlx-whisper... (this may take a moment)"
        pip install mlx-whisper -q
        echo "  MLX Whisper installed"
        # Update config to use mlx backend
        if grep -q 'backend: "faster-whisper"' "$INSTALL_DIR/config.yaml"; then
            sed -i '' 's/backend: "faster-whisper"/backend: "mlx"/' "$INSTALL_DIR/config.yaml"
        fi
    else
        echo "Installing faster-whisper... (this may take a moment)"
        pip install faster-whisper -q
        echo "  Faster Whisper installed"
    fi
fi

# Download Piper TTS binary (uses native binary instead of Python library for macOS compatibility)
echo ""
PIPER_DIR="$INSTALL_DIR/piper"
mkdir -p "$PIPER_DIR"

if [ ! -f "$PIPER_DIR/piper" ]; then
    echo "Downloading Piper TTS binary..."
    if [[ "$(uname)" == "Darwin" ]]; then
        if [[ "$(uname -m)" == "arm64" ]]; then
            PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_aarch64.tar.gz"
        else
            PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_x64.tar.gz"
        fi
    else
        PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"
    fi
    curl -L "$PIPER_URL" 2>/dev/null | tar -xz -C "$PIPER_DIR" --strip-components=1
    chmod +x "$PIPER_DIR/piper"
    echo "Piper TTS binary installed"
else
    echo "Piper TTS binary already installed"
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

# macOS permissions check
if [[ "$(uname)" == "Darwin" ]]; then

    # Check Microphone permission using macOS AVFoundation
    echo ""
    echo "=================================="
    echo "macOS Microphone Permission"
    echo "=================================="
    echo ""
    echo "Checking microphone permissions..."

    MIC_CHECK=$(osascript -e 'use framework "AVFoundation"' -e 'set authStatus to current application'"'"'s AVCaptureDevice'"'"'s authorizationStatusForMediaType:"soun"' -e 'return authStatus as integer' 2>/dev/null)

    # authorizationStatus: 0=notDetermined, 1=restricted, 2=denied, 3=authorized
    case "$MIC_CHECK" in
        3) MIC_CHECK="granted" ;;
        0) MIC_CHECK="not_determined" ;;
        *) MIC_CHECK="denied" ;;
    esac

    if [[ "$MIC_CHECK" == "granted" ]]; then
        echo "✓ Microphone permission is already granted!"
    else
        echo ""
        if [[ "$MIC_CHECK" == "not_determined" ]]; then
            echo "Microphone permission not yet requested."
        else
            echo "⚠️  Microphone permission is NOT enabled."
        fi
        echo ""
        echo "Opening System Settings > Privacy & Security > Microphone..."
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
        echo ""
        echo "Enable microphone access for your terminal app."
        echo "(Your terminal is likely: Terminal, iTerm, Warp, or the IDE you're running this from)"
        echo ""
        read -p "Press Enter after enabling microphone access... "
    fi

    # Check Accessibility permission
    echo ""
    echo "=================================="
    echo "macOS Accessibility Permission"
    echo "=================================="
    echo ""
    echo "The daemon needs Accessibility permissions to detect keyboard input."
    echo ""

    # Use tccutil to check, or try to detect via pynput's warning output
    echo "Checking Accessibility permissions..."

    # Run pynput and capture stderr for the "not trusted" warning
    ACCESSIBILITY_CHECK=$("$INSTALL_DIR/venv/bin/python3" << 'EOF' 2>&1
import sys
import time
from pynput import keyboard

# Create and start listener
listener = keyboard.Listener(on_press=lambda k: None)
listener.start()
time.sleep(0.5)  # Give it time to show warning
listener.stop()
print("done")
EOF
)

    if [[ "$ACCESSIBILITY_CHECK" == *"not trusted"* ]] || [[ "$ACCESSIBILITY_CHECK" == *"not be possible"* ]]; then
        echo ""
        echo "⚠️  Accessibility permission is NOT enabled."
        echo ""
        echo "Opening System Settings > Privacy & Security > Accessibility..."
        echo ""
        open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"

        echo "Please enable your terminal app in the list, then press Enter to continue."
        echo "(Your terminal is likely: Terminal, iTerm, Warp, or the IDE you're running this from)"
        echo ""
        read -p "Press Enter after enabling Accessibility for your terminal... "

        echo ""
        echo "Note: You may need to restart your terminal for the permission to take effect."
    else
        echo "✓ Accessibility permission is already granted!"
    fi
    echo ""
fi

# Add shell aliases (only on fresh install)
if [ "$IS_UPDATE" != true ]; then
    echo ""

    # Detect shell config file
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_RC="$HOME/.zshrc"
        SHELL_NAME="zsh"
    else
        SHELL_RC="$HOME/.bashrc"
        SHELL_NAME="bash"
    fi

    # Check if aliases already exist
    if grep -q "claude-voice-daemon" "$SHELL_RC" 2>/dev/null; then
        echo "Shell aliases already configured in $SHELL_RC"
    else
        echo "Would you like to add shell aliases (cv, cvf, cvs) to $SHELL_RC?"
        read -p "Add aliases? [Y/n]: " ADD_ALIASES
        ADD_ALIASES=${ADD_ALIASES:-Y}

        if [[ "$ADD_ALIASES" =~ ^[Yy]$ ]]; then
            echo "" >> "$SHELL_RC"
            echo "# Claude Voice aliases" >> "$SHELL_RC"
            echo 'alias cv="~/.claude-voice/claude-voice-daemon"' >> "$SHELL_RC"
            echo 'alias cvf="~/.claude-voice/claude-voice-daemon foreground"' >> "$SHELL_RC"
            echo 'alias cvs="~/.claude-voice/claude-voice-daemon --silent foreground"' >> "$SHELL_RC"
            echo "Aliases added to $SHELL_RC"
            echo ""
            echo "To use them now, run:  source $SHELL_RC"
        else
            echo ""
            echo "To add aliases manually, add these to $SHELL_RC:"
            echo '  alias cv="~/.claude-voice/claude-voice-daemon"'
            echo '  alias cvf="~/.claude-voice/claude-voice-daemon foreground"'
            echo '  alias cvs="~/.claude-voice/claude-voice-daemon --silent foreground"'
        fi
    fi
fi

echo ""
echo "=================================="
if [ "$IS_UPDATE" = true ]; then
    echo "Update complete!"
else
    echo "Installation complete!"
fi
echo "=================================="

# Remind about shell aliases
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="~/.zshrc"
else
    SHELL_RC="~/.bashrc"
fi
echo ""
echo "To use shortcuts (cv, cvf, cvs): source $SHELL_RC"
echo ""

# Offer to test
echo ""
read -p "Would you like to try it out now? (starts voice daemon) [Y/n]: " TEST_NOW
TEST_NOW=${TEST_NOW:-Y}

if [[ "$TEST_NOW" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Starting Claude Voice..."
    echo ""
    echo "  Hold Right Alt and speak, then release to transcribe."
    echo "  Press Ctrl+C to stop."
    echo ""
    echo "---"
    # Restore direct terminal output before running daemon
    # This avoids tee buffering issues with Python output
    exec 1>/dev/tty 2>&1
    "$INSTALL_DIR/claude-voice-daemon" foreground
else
    echo ""
    echo "Quick start:"
    echo "  1. Start the daemon:  ~/.claude-voice/claude-voice-daemon foreground"
    echo "  2. Start Claude Code:  claude"
    echo "  3. Hold Right Alt and speak, release to transcribe"
    echo ""
    if [ "$IS_UPDATE" = true ]; then
        echo "To uninstall: ./uninstall.sh"
        echo ""
    fi
fi
