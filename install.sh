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

_spin_run() {
    # Usage: _spin_run "message" command args...
    local msg="$1"; shift
    local frames="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    local log; log=$(mktemp)

    # Run command in background, capture output
    "$@" >"$log" 2>&1 &
    local cmd_pid=$!

    # Animate spinner while command runs
    local i=0
    while kill -0 "$cmd_pid" 2>/dev/null; do
        printf "\r\033[K%s %s" "${frames:$((i % ${#frames})):1}" "$msg"
        sleep 0.08
        i=$((i + 1))
    done

    # Get exit code
    wait "$cmd_pid"
    local rc=$?

    if [ $rc -eq 0 ]; then
        printf "\r\033[K%s done.\n" "$msg"
    else
        printf "\r\033[K%s FAILED\n" "$msg"
        cat "$log"
    fi
    rm -f "$log"
    return $rc
}

# Set up logging - capture all output to log file while still showing on screen
mkdir -p "$INSTALL_DIR/logs"
LOG_FILE="$INSTALL_DIR/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
TEE_PID=$!
trap 'kill $TEE_PID 2>/dev/null; wait $TEE_PID 2>/dev/null' EXIT

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

# Check for ffmpeg (required by mlx-audio's av dependency)
if ! command -v ffmpeg &>/dev/null; then
    echo "FFmpeg is required for Kokoro TTS (mlx-audio)."
    if command -v brew &>/dev/null; then
        read -p "Install ffmpeg via Homebrew? [Y/n]: " INSTALL_FFMPEG
        INSTALL_FFMPEG=${INSTALL_FFMPEG:-Y}
        if [[ "$INSTALL_FFMPEG" =~ ^[Yy]$ ]]; then
            echo "Installing ffmpeg..."
            brew install ffmpeg
        else
            echo "Error: ffmpeg is required. Install it manually and re-run."
            exit 1
        fi
    else
        echo "Error: ffmpeg not found and Homebrew not available."
        echo "Install ffmpeg manually (e.g. brew install ffmpeg) and re-run."
        exit 1
    fi
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
        # Wait up to 5 seconds for daemon to exit
        for i in 1 2 3 4 5; do
            if ! pgrep -f "claude-voice/daemon/main.py" >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
    fi
fi

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"/{daemon,logs}
mkdir -p "$CLAUDE_HOOKS_DIR"

# Copy daemon files (always update these)
if [ "$IS_UPDATE" = true ]; then
    echo "Updating daemon modules..."
else
    echo "Installing daemon modules..."
fi
cp "$SCRIPT_DIR"/daemon/*.py "$INSTALL_DIR/daemon/"
cp -r "$SCRIPT_DIR/daemon/notify_phrases" "$INSTALL_DIR/daemon/"
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
fi

# Find suitable Python (3.12+ required for mlx-audio dependencies)
PYTHON_BIN=""

# Check pyenv versions first (most reliable on macOS)
for pyver in 3.13 3.12; do
    for p in "$HOME/.pyenv/versions/$pyver"*/bin/python3; do
        if [ -x "$p" ]; then
            PYTHON_BIN="$p"
            break 2
        fi
    done
done

# Fall back to system pythons (skip pyenv shims which may not resolve)
if [ -z "$PYTHON_BIN" ]; then
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        if [ -x "$candidate" ]; then
            PY_MINOR=$("$candidate" -c "import sys; print(sys.version_info[1])" 2>/dev/null || echo "0")
            if [ "$PY_MINOR" -ge 12 ] 2>/dev/null; then
                PYTHON_BIN="$candidate"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "Error: Python 3.12+ is required but not found."
    echo "Install it with: pyenv install 3.13"
    exit 1
fi

echo "Using Python: $($PYTHON_BIN --version 2>&1)"

# Create or reuse virtual environment
if [ ! -d "$INSTALL_DIR/venv" ]; then
    echo "Creating Python virtual environment..."
    "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
else
    # Check existing venv Python version is 3.12+
    VENV_MINOR=$("$INSTALL_DIR/venv/bin/python3" -c "import sys; print(sys.version_info[1])" 2>/dev/null || echo "0")
    if [ "$VENV_MINOR" -lt 12 ] 2>/dev/null; then
        echo "Recreating virtual environment with Python 3.12+..."
        rm -rf "$INSTALL_DIR/venv"
        "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
    else
        echo "Using existing virtual environment..."
    fi
fi

source "$INSTALL_DIR/venv/bin/activate"

# Install/upgrade Python dependencies
if [ "$IS_UPDATE" = true ]; then
    _spin_run "Updating Python dependencies" pip install --upgrade pip -q
else
    _spin_run "Installing Python dependencies" pip install --upgrade pip -q
fi
_spin_run "Installing core dependencies" pip install --upgrade --only-binary av pynput sounddevice pyyaml mlx-audio "misaki<0.8" num2words phonemizer spacy espeakng-loader pyobjc-framework-Cocoa pyobjc-framework-Quartz -q
if ! python3 -c "import en_core_web_sm" 2>/dev/null; then
    _spin_run "Downloading spacy English model" python3 -m spacy download en_core_web_sm -q
fi

# Migrate Piper TTS config to Kokoro (must run after venv + deps are installed)
if grep -q 'piper\|en_GB-\|en_US-' "$INSTALL_DIR/config.yaml" 2>/dev/null; then
    echo "  Migrating speech config from Piper to Kokoro..."
    "$INSTALL_DIR/venv/bin/python3" << 'MIGRATE'
import os, re

config_path = os.path.expanduser("~/.claude-voice/config.yaml")
with open(config_path) as f:
    text = f.read()

changed = False

# Migrate Piper voice to Kokoro default
if re.search(r'voice:\s*["\']?en_(GB|US)-', text):
    text = re.sub(r'(voice:\s*)["\']?en_\w+-[\w-]+["\']?', r'\1"af_heart"', text)
    changed = True

# Add lang_code if missing (insert after voice line)
if "lang_code" not in text:
    text = re.sub(r'(voice:.*\n)', r'\1  lang_code: "a"\n', text)
    changed = True

# Reset speed from Piper default
if re.search(r'speed:\s*1\.3\b', text):
    text = re.sub(r'(speed:\s*)1\.3', r'\g<1>1.0', text)
    changed = True

if changed:
    with open(config_path, "w") as f:
        f.write(text)
    print("  Config migrated: voice -> af_heart, lang_code -> a")
else:
    print("  Config already up to date")
MIGRATE
fi

# Determine STT backend - check existing config on updates
CURRENT_BACKEND=""
if [ "$IS_UPDATE" = true ] && [ -f "$INSTALL_DIR/config.yaml" ]; then
    # Extract backend value: handles backend: "mlx", backend: mlx, and inline comments
    CURRENT_BACKEND=$(grep -E '^\s*backend:' "$INSTALL_DIR/config.yaml" | sed 's/.*backend:[[:space:]]*//' | sed 's/[[:space:]]*#.*//' | tr -d '"' | xargs)
fi

if [ -n "$CURRENT_BACKEND" ]; then
    echo ""
    if [ "$CURRENT_BACKEND" = "mlx" ]; then
        _spin_run "Updating speech-to-text backend (mlx)" pip install --upgrade --only-binary av mlx-whisper -q
    else
        _spin_run "Updating speech-to-text backend (faster-whisper)" pip install --upgrade --only-binary av faster-whisper -q
    fi
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
        _spin_run "Installing mlx-whisper" pip install mlx-whisper -q
        # Update config to use mlx backend
        if grep -q 'backend: "faster-whisper"' "$INSTALL_DIR/config.yaml"; then
            sed -i '' 's/backend: "faster-whisper"/backend: "mlx"/' "$INSTALL_DIR/config.yaml"
        fi
    else
        _spin_run "Installing faster-whisper" pip install faster-whisper -q
    fi
fi

# Install Claude Code hooks
echo "Installing Claude Code hooks..."
cp "$SCRIPT_DIR/hooks/speak-response.py" "$CLAUDE_HOOKS_DIR/"
cp "$SCRIPT_DIR/hooks/notify-permission.py" "$CLAUDE_HOOKS_DIR/"
cp "$SCRIPT_DIR/hooks/permission-request.py" "$CLAUDE_HOOKS_DIR/"
cp "$SCRIPT_DIR/hooks/handle-ask-user.py" "$CLAUDE_HOOKS_DIR/"
cp "$SCRIPT_DIR/hooks/_common.py" "$CLAUDE_HOOKS_DIR/"
chmod +x "$CLAUDE_HOOKS_DIR/speak-response.py"
chmod +x "$CLAUDE_HOOKS_DIR/notify-permission.py"
chmod +x "$CLAUDE_HOOKS_DIR/permission-request.py"
chmod +x "$CLAUDE_HOOKS_DIR/handle-ask-user.py"

# Update Claude settings for hooks
echo "Configuring Claude Code settings..."
"$INSTALL_DIR/venv/bin/python3" << 'EOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")

# Claude Voice hook definitions
CV_HOOKS = {
    "Stop": {"matcher": "", "command": "~/.claude/hooks/speak-response.py"},
    "Notification": {"matcher": "permission_prompt", "command": "~/.claude/hooks/notify-permission.py"},
    "PreToolUse": {"matcher": "AskUserQuestion", "command": "~/.claude/hooks/handle-ask-user.py"},
    "PermissionRequest": {"matcher": "", "command": "~/.claude/hooks/permission-request.py"},
}

# All claude-voice hook script filenames (for filtering)
CV_COMMANDS = {h["command"] for h in CV_HOOKS.values()}

def is_cv_hook(entry):
    """Check if a hook entry belongs to claude-voice."""
    for hook in entry.get("hooks", []):
        if hook.get("command") in CV_COMMANDS:
            return True
    return False

try:
    with open(settings_path) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

if "hooks" not in settings:
    settings["hooks"] = {}

changed = False
for category, defn in CV_HOOKS.items():
    existing = settings["hooks"].get(category, [])

    # Filter out old claude-voice entries, keep everything else
    other_hooks = [e for e in existing if not is_cv_hook(e)]

    # Append our hook
    cv_entry = {
        "matcher": defn["matcher"],
        "hooks": [{"type": "command", "command": defn["command"]}],
    }
    new_list = other_hooks + [cv_entry]

    if new_list != existing:
        changed = True
    settings["hooks"][category] = new_list

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

if changed:
    print("Updated Claude Voice hooks in settings.json (preserved other hooks)")
else:
    print("Hooks already configured in settings.json")
EOF

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

# Notify mode info
echo ""
echo "=================================="
echo "Notify Mode"
echo "=================================="
echo ""
echo "Notify mode plays short status phrases instead of reading responses aloud."
echo "Error detection uses Claude Code hooks (no LLM required)."
echo "Switch at runtime with voice command: 'switch to notify mode'"
echo ""

# AFK mode info
echo "=================================="
echo "AFK Mode"
echo "=================================="
echo ""
echo "AFK mode lets you handle Claude Code permissions and questions remotely"
echo "via Telegram, and send new prompts to idle sessions while away from your desk."
echo ""
echo "To set up AFK mode, add your Telegram bot token and chat ID to:"
echo "  ~/.claude-voice/config.yaml"
echo ""
echo "  afk:"
echo "    telegram:"
echo "      bot_token: \"your-bot-token\""
echo "      chat_id: \"your-chat-id\""
echo ""

# Add shell aliases (only on fresh install)
if [ "$IS_UPDATE" != true ]; then
    echo ""

    # Detect shell config file
    if [[ "$SHELL" == *"zsh"* ]]; then
        SHELL_RC="$HOME/.zshrc"
        SHELL_NAME="zsh"
    elif [ "$(uname)" = "Darwin" ]; then
        SHELL_RC="$HOME/.bash_profile"
        SHELL_NAME="bash"
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
elif [ "$(uname)" = "Darwin" ]; then
    SHELL_RC="~/.bash_profile"
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
