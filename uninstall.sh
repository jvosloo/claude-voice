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
    sleep 1
fi

# Remove Claude Code hooks
if [ -f "$CLAUDE_HOOKS_DIR/speak-response.py" ]; then
    echo "Removing Claude Code hooks..."
    rm -f "$CLAUDE_HOOKS_DIR/speak-response.py"
fi
rm -f "$CLAUDE_HOOKS_DIR/notify-permission.py"
rm -f "$CLAUDE_HOOKS_DIR/permission-request.py"
rm -f "$CLAUDE_HOOKS_DIR/handle-ask-user.py"
rm -f "$CLAUDE_HOOKS_DIR/_common.py"

# Remove hooks from settings.json
if [ -f "$CLAUDE_SETTINGS" ] && grep -q '"Stop"\|"Notification"\|"PreToolUse"\|"PermissionRequest"' "$CLAUDE_SETTINGS"; then
    echo "Removing Claude Voice hooks from Claude settings..."
    python3 << 'EOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
try:
    with open(settings_path, 'r') as f:
        settings = json.load(f)

    if 'hooks' in settings:
        for hook_name in ['Stop', 'Notification', 'PreToolUse', 'PermissionRequest']:
            settings['hooks'].pop(hook_name, None)
        # Clean up empty hooks object
        if not settings['hooks']:
            del settings['hooks']

    with open(settings_path, 'w') as f:
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
    echo "Removing installation (keeping preserved files)..."
    # Remove everything except what user chose to keep
    rm -rf "$INSTALL_DIR/daemon"
    rm -rf "$INSTALL_DIR/venv"
    rm -rf "$INSTALL_DIR/logs"
    rm -f "$INSTALL_DIR/daemon.pid"
    rm -f "$INSTALL_DIR/.silent"
    rm -f "$INSTALL_DIR/.mode"
    rm -rf "$INSTALL_DIR/notify_cache"
    rm -f "$INSTALL_DIR/.tts.sock"
    rm -f "$INSTALL_DIR/.control.sock"
    rm -f "$INSTALL_DIR/claude-voice-daemon"
    rm -f "$INSTALL_DIR/claude-wrapper.sh"
    rm -f "$INSTALL_DIR/config.yaml.example"
    rm -f "$INSTALL_DIR/permission_rules.json"
    rm -f "$INSTALL_DIR/.DS_Store"
    rm -rf "$INSTALL_DIR/tests"
    # Note: dev/ is shared with the settings app — don't delete it
    # Remove any stray files that shouldn't be there
    rm -f "$INSTALL_DIR/README.md"
    rm -f "$INSTALL_DIR/requirements.txt"
    rm -f "$INSTALL_DIR/install.sh"
    rm -rf "$INSTALL_DIR/models"

    # Remove directory if empty
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
        # Remove the aliases and the comment line
        sed -i '' '/# Claude Voice aliases/d' "$SHELL_RC"
        sed -i '' '/claude-voice-daemon/d' "$SHELL_RC"
        echo "Removed aliases from $SHELL_RC"
        echo "Run 'source $SHELL_RC' or open a new terminal to apply."
    else
        echo "Aliases kept in $SHELL_RC - remove manually if desired."
    fi
fi
echo ""
