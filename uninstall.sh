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

# Remove Claude Code hook
if [ -f "$CLAUDE_HOOKS_DIR/speak-response.py" ]; then
    echo "Removing Claude Code hook..."
    rm -f "$CLAUDE_HOOKS_DIR/speak-response.py"
fi

# Remove Stop hook from settings.json
if [ -f "$CLAUDE_SETTINGS" ] && grep -q '"Stop"' "$CLAUDE_SETTINGS"; then
    echo "Removing Stop hook from Claude settings..."
    python3 << 'EOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
try:
    with open(settings_path, 'r') as f:
        settings = json.load(f)

    if 'hooks' in settings and 'Stop' in settings['hooks']:
        del settings['hooks']['Stop']
        # Clean up empty hooks object
        if not settings['hooks']:
            del settings['hooks']

    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    print("Removed Stop hook from settings.json")
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

# Handle downloaded models
MODELS_SIZE=$(du -sh "$INSTALL_DIR/models" 2>/dev/null | cut -f1)
if [ -d "$INSTALL_DIR/models" ] && [ -n "$(ls -A "$INSTALL_DIR/models/piper" 2>/dev/null)" ]; then
    echo ""
    read -p "Delete downloaded voice models? ($MODELS_SIZE) [y/N]: " DEL_MODELS
    if [[ "$DEL_MODELS" =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR/models"
        echo "Deleted models"
    else
        echo "Keeping models at $INSTALL_DIR/models/"
        KEEP_MODELS=true
    fi
fi

# Remove main installation directory
echo ""
if [ "$KEEP_CONFIG" = true ] || [ "$KEEP_MODELS" = true ]; then
    echo "Removing installation (keeping preserved files)..."
    # Remove everything except what user chose to keep
    rm -rf "$INSTALL_DIR/daemon"
    rm -rf "$INSTALL_DIR/venv"
    rm -rf "$INSTALL_DIR/logs"
    rm -rf "$INSTALL_DIR/piper"
    rm -f "$INSTALL_DIR/daemon.pid"
    rm -f "$INSTALL_DIR/.silent"
    rm -f "$INSTALL_DIR/claude-voice-daemon"
    rm -f "$INSTALL_DIR/config.yaml.example"
    rm -f "$INSTALL_DIR/.DS_Store"
    # Remove any stray files that shouldn't be there
    rm -f "$INSTALL_DIR/README.md"
    rm -f "$INSTALL_DIR/requirements.txt"
    rm -f "$INSTALL_DIR/install.sh"
    [ "$KEEP_MODELS" != true ] && rm -rf "$INSTALL_DIR/models"
    [ "$KEEP_CONFIG" != true ] && rm -f "$INSTALL_DIR/config.yaml"

    # Remove directory if empty
    rmdir "$INSTALL_DIR" 2>/dev/null || true
else
    echo "Removing installation directory..."
    rm -rf "$INSTALL_DIR"
fi

echo ""
echo "=================================="
echo "Uninstall complete!"
echo "=================================="
echo ""

# Handle shell aliases
if [[ "$SHELL" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
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
