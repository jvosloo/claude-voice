#!/usr/bin/env bash
# Claude Code tmux wrapper
#
# Source this file in your .zshrc or .bashrc:
#   source /path/to/claude-voice/claude-wrapper.sh
#
# This replaces the `claude` command with a function that transparently
# wraps interactive sessions in tmux. Non-interactive usage (claude -p, etc.)
# passes through unchanged.

claude() {
    # Already inside tmux — run claude normally
    if [ -n "$TMUX" ]; then
        command claude "$@"
        return
    fi

    # Check if tmux is installed
    if ! command -v tmux &>/dev/null; then
        echo "claude-wrapper: tmux not found, running claude directly. Install with: brew install tmux" >&2
        command claude "$@"
        return
    fi

    # Non-interactive mode — run directly, no tmux needed
    # Catches flags and subcommands that don't need an interactive session
    if [ $# -gt 0 ]; then
        case "$1" in
            -p|--print|--help|-h|-v|--version|doctor|mcp|plugin|setup-token|update|install)
                command claude "$@"
                return
                ;;
        esac
    fi

    # Interactive mode outside tmux — wrap in a tmux session
    local session_name
    session_name="$(basename "$PWD")"

    # Sanitize session name: tmux doesn't allow dots or colons
    session_name="${session_name//./-}"
    session_name="${session_name//:/-}"

    # Handle duplicate names
    if tmux has-session -t "=$session_name" 2>/dev/null; then
        session_name="${session_name}-$$"
    fi

    # Create detached session in current directory
    tmux new-session -d -s "$session_name" -c "$PWD"

    # Build the claude command with arguments
    local cmd="command claude"
    if [ $# -gt 0 ]; then
        # Quote each argument for safe passing
        for arg in "$@"; do
            cmd="$cmd $(printf '%q' "$arg")"
        done
    fi

    # Launch claude inside the tmux session
    tmux send-keys -t "$session_name" "$cmd" Enter

    # Attach to the session
    tmux attach -t "$session_name"
}
