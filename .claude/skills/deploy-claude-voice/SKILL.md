---
name: deploy-claude-voice
description: Use when changes to claude-voice code need to be deployed from the project repo to the local installation at ~/.claude-voice
---

# Deploy Claude Voice

## Overview

Deploy changes from `/Users/johan/IdeaProjects/claude-voice` (project repo) to `~/.claude-voice/` and `~/.claude/hooks/` (local installation) where the daemon runs.

**Core principle:** Project repo is source of truth. Local installation must be updated manually after code changes.

## When to Use

- After modifying any file in `daemon/`
- After modifying any file in `hooks/`
- After creating new Python files
- User asks to "deploy", "install", or "update" changes

## Quick Reference

| Command | Purpose |
|---------|---------|
| `./deploy.sh` | Smart deploy - only copies changed files |
| `pkill -f claude-voice-daemon && claude-voice-daemon &` | Restart daemon |
| `ls -l ~/.claude/hooks/*.py` | Verify hooks are executable |

## Deployment Process

### 1. Run Deployment Script

```bash
cd /Users/johan/IdeaProjects/claude-voice
./deploy.sh
```

The script:
- Compares repo vs installation
- Copies only changed files
- Shows what was deployed
- Advises if restart needed

### 2. Make Hooks Executable (if new hooks deployed)

```bash
chmod +x ~/.claude/hooks/*.py
```

### 3. Restart Daemon (if daemon files changed)

```bash
pkill -f claude-voice-daemon
claude-voice-daemon &
```

### 4. Verify Deployment

Run a quick test:
```bash
# Check daemon is running
ps aux | grep claude-voice-daemon

# For hook changes, test in a Claude Code session
# Trigger the hook and verify behavior
```

## File Mappings

| Source (Repo) | Destination (Installation) |
|---------------|---------------------------|
| `daemon/*.py` | `~/.claude-voice/daemon/` |
| `hooks/*.py` | `~/.claude/hooks/` |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Forgot to deploy | Run `./deploy.sh` after every code change |
| Daemon using old code | Restart daemon with `pkill -f claude-voice-daemon && claude-voice-daemon &` |
| Hook not executable | `chmod +x ~/.claude/hooks/*.py` |
| Deployed but didn't test | Always verify with quick test after deployment |

## Manual Deployment (if script unavailable)

```bash
# Deploy daemon files
cp daemon/*.py ~/.claude-voice/daemon/

# Deploy hook files
cp hooks/*.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.py

# Restart daemon
pkill -f claude-voice-daemon
claude-voice-daemon &
```

## Red Flags - Missing Steps

- ❌ Deployed but didn't restart daemon
- ❌ Created new hook but didn't chmod +x
- ❌ Deployed but didn't verify it works
- ❌ Modified code but didn't deploy

**All of these mean: Complete the deployment process.**
