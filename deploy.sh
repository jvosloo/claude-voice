#!/bin/bash
set -e

# Claude Voice Deployment Script
# Copies daemon and hooks from the repo to the running installation

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.claude-voice"
HOOKS_DIR="$HOME/.claude/hooks"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "Claude Voice Deployment"
echo "======================"
echo "Repo:    $REPO_DIR"
echo "Daemon:  $INSTALL_DIR/daemon"
echo "Hooks:   $HOOKS_DIR"
echo ""

# Check if installation exists
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}Error: Installation not found at $INSTALL_DIR${NC}"
    echo "Run install.sh first."
    exit 1
fi

# Function to copy with comparison
copy_if_changed() {
    local src="$1"
    local dest="$2"

    if [ ! -f "$dest" ]; then
        cp "$src" "$dest"
        echo -e "  ${GREEN}+${NC} $(basename "$dest") (new)"
        return 0
    fi

    if ! cmp -s "$src" "$dest"; then
        cp "$src" "$dest"
        echo -e "  ${YELLOW}*${NC} $(basename "$dest") (updated)"
        return 0
    fi

    return 1
}

# Deploy daemon files
echo "Deploying daemon files..."
daemon_changed=0
for file in "$REPO_DIR/daemon"/*.py; do
    if [ -f "$file" ]; then
        if copy_if_changed "$file" "$INSTALL_DIR/daemon/$(basename "$file")"; then
            daemon_changed=$((daemon_changed + 1))
        fi
    fi
done

if [ $daemon_changed -eq 0 ]; then
    echo "  No daemon changes"
fi

# Deploy hooks files
echo ""
echo "Deploying hooks files..."
hooks_changed=0
for file in "$REPO_DIR/hooks"/*.py; do
    if [ -f "$file" ]; then
        if copy_if_changed "$file" "$HOOKS_DIR/$(basename "$file")"; then
            hooks_changed=$((hooks_changed + 1))
        fi
    fi
done

if [ $hooks_changed -eq 0 ]; then
    echo "  No hooks changes"
fi

# Check if daemon is running
echo ""
if pgrep -f "claude-voice-daemon" > /dev/null; then
    echo -e "${YELLOW}Daemon is running${NC}"

    if [ $daemon_changed -gt 0 ]; then
        echo ""
        echo "Daemon files changed - restart required:"
        echo "  pkill -f claude-voice-daemon && claude-voice-daemon"
        echo ""
        echo "Or reload config only (if only config logic changed):"
        echo "  claude-voice-daemon reload"
    else
        echo "No daemon restart needed (only hooks changed or no changes)"
    fi
else
    echo -e "${RED}Daemon is not running${NC}"
    echo "Start it with: claude-voice-daemon"
fi

echo ""
echo -e "${GREEN}Deployment complete${NC}"
echo "Files deployed: daemon=$daemon_changed, hooks=$hooks_changed"
