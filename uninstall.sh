#!/bin/bash
#
# Claude Voice Interface Uninstaller
# Removes all components installed by install.sh
#

INSTALL_DIR="$HOME/.claude-voice"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

# Set up logging if install dir exists
if [ -d "$INSTALL_DIR/logs" ]; then
    LOG_FILE="$INSTALL_DIR/logs/uninstall-$(date +%Y%m%d-%H%M%S).log"
    exec > >(tee -a "$LOG_FILE") 2>&1
    TEE_PID=$!
    trap 'kill $TEE_PID 2>/dev/null; wait $TEE_PID 2>/dev/null' EXIT
    echo "Uninstall log: $LOG_FILE"
    echo ""
fi

echo "=================================="
echo "Claude Voice Interface Uninstaller"
echo "=================================="
echo "$(date)"
echo ""

# Check if installed
if [ ! -d "$INSTALL_DIR" ] && [ ! -f "$CLAUDE_HOOKS_DIR/speak-response.py" ]; then
    echo "Claude Voice does not appear to be installed."
    exit 0
fi

# Confirm uninstall
read -p "This will remove Claude Voice. Continue? [y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled."
    exit 0
fi

echo ""

# Stop daemon if running (check both PID file and running processes)
DAEMON_STOPPED=false

# Check PID file first (background mode)
if [ -f "$INSTALL_DIR/daemon.pid" ]; then
    PID=$(cat "$INSTALL_DIR/daemon.pid")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping running daemon (PID: $PID)..."
        kill "$PID" 2>/dev/null
        DAEMON_STOPPED=true
    fi
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

# Remove Claude Code hooks
echo "Removing Claude Code hook scripts..."
for hook in speak-response.py notify-permission.py permission-request.py handle-ask-user.py _common.py; do
    if [ -f "$CLAUDE_HOOKS_DIR/$hook" ]; then
        rm -f "$CLAUDE_HOOKS_DIR/$hook"
        echo "  Removed $hook"
    fi
done

# Remove hooks from settings.json (only claude-voice entries, preserve others)
if [ -f "$CLAUDE_SETTINGS" ] && grep -q 'claude/hooks/' "$CLAUDE_SETTINGS"; then
    echo "Removing Claude Voice hooks from Claude settings..."
    SETTINGS_PYTHON="${INSTALL_DIR}/venv/bin/python3"
    # Fall back to system python if venv is already gone
    if [ ! -x "$SETTINGS_PYTHON" ]; then
        SETTINGS_PYTHON="python3"
    fi
    "$SETTINGS_PYTHON" << 'EOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")

# Claude-voice hook command paths
CV_COMMANDS = {
    "~/.claude/hooks/speak-response.py",
    "~/.claude/hooks/notify-permission.py",
    "~/.claude/hooks/handle-ask-user.py",
    "~/.claude/hooks/permission-request.py",
}

def is_cv_hook(entry):
    """Check if a hook entry belongs to claude-voice."""
    for hook in entry.get("hooks", []):
        if hook.get("command") in CV_COMMANDS:
            return True
    return False

try:
    with open(settings_path) as f:
        settings = json.load(f)

    if "hooks" in settings:
        for category in list(settings["hooks"]):
            entries = settings["hooks"][category]
            if not isinstance(entries, list):
                continue
            # Keep only non-claude-voice entries
            kept = [e for e in entries if not is_cv_hook(e)]
            if kept:
                settings["hooks"][category] = kept
            else:
                del settings["hooks"][category]
        # Clean up empty hooks object
        if not settings["hooks"]:
            del settings["hooks"]

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print("Removed Claude Voice hooks from settings.json")
except Exception as e:
    print(f"Warning: Could not update settings.json: {e}")
EOF
fi

# Handle config.yaml
if [ -f "$INSTALL_DIR/config.yaml" ]; then
    echo ""
    read -p "Delete your config.yaml? (contains your customizations) [y/N]: " DEL_CONFIG
    if [[ "$DEL_CONFIG" =~ ^[Yy]$ ]]; then
        rm -f "$INSTALL_DIR/config.yaml"
        echo "Deleted config.yaml"
    else
        echo "Keeping config.yaml at $INSTALL_DIR/config.yaml"
        KEEP_CONFIG=true
    fi
fi

# Handle downloaded Kokoro TTS model (in Hugging Face cache)
KOKORO_CACHE="$HOME/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16"
if [ -d "$KOKORO_CACHE" ]; then
    KOKORO_SIZE=$(du -sh "$KOKORO_CACHE" 2>/dev/null | cut -f1)
    echo ""
    read -p "Delete downloaded Kokoro TTS model? ($KOKORO_SIZE) [y/N]: " DEL_KOKORO
    if [[ "$DEL_KOKORO" =~ ^[Yy]$ ]]; then
        rm -rf "$KOKORO_CACHE"
        echo "Deleted Kokoro model cache"
    else
        echo "Keeping Kokoro model at $KOKORO_CACHE"
    fi
fi

# Remove main installation directory
echo ""
if [ "$KEEP_CONFIG" = true ]; then
    echo "Removing installation (keeping config.yaml and dev/)..."
    # Remove everything except config.yaml and dev/ (shared with settings app)
    find "$INSTALL_DIR" -mindepth 1 \
        -not -name "config.yaml" \
        -not -name "dev" \
        -not -path "$INSTALL_DIR/dev/*" \
        -delete 2>/dev/null
    # Remove directory if empty (will fail if config.yaml or dev/ remain)
    rmdir "$INSTALL_DIR" 2>/dev/null || true
else
    echo "Removing installation directory..."
    rm -f "$INSTALL_DIR/.tts.sock"
    rm -f "$INSTALL_DIR/.control.sock"
    rm -rf "$INSTALL_DIR"
fi

# Remove temp files (session responses, debug logs, PID files)
if [ -d "/tmp/claude-voice" ]; then
    echo "Removing temp files..."
    rm -rf "/tmp/claude-voice"
fi

echo ""
echo "=================================="
echo "Uninstall complete!"
echo "=================================="
echo ""

# Handle shell aliases
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [ "$(uname)" = "Darwin" ]; then
    SHELL_RC="$HOME/.bash_profile"
else
    SHELL_RC="$HOME/.bashrc"
fi

if grep -q "claude-voice-daemon" "$SHELL_RC" 2>/dev/null; then
    read -p "Remove shell aliases from $SHELL_RC? [Y/n]: " DEL_ALIASES
    DEL_ALIASES=${DEL_ALIASES:-Y}

    if [[ "$DEL_ALIASES" =~ ^[Yy]$ ]]; then
        # Remove only the exact alias lines and their comment header
        sed -i '' '/^# Claude Voice aliases$/d' "$SHELL_RC"
        sed -i '' '/^alias cv[fs]\{0,1\}="~\/\.claude-voice\/claude-voice-daemon/d' "$SHELL_RC"
        echo "Removed aliases from $SHELL_RC"
        echo "Run 'source $SHELL_RC' or open a new terminal to apply."
    else
        echo "Aliases kept in $SHELL_RC - remove manually if desired."
    fi
fi
echo ""
