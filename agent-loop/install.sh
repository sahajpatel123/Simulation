#!/bin/bash
# Install + start the autonomous loop as a launchd agent (runs every 5 min).
set -euo pipefail

PROJECT_DIR="/Users/sahajpatel/Code/thecee"
PLIST_SRC="$PROJECT_DIR/agent-loop/com.thecee.autonomous-loop.plist"
PLIST_NAME="com.thecee.autonomous-loop"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DEST="$LAUNCH_AGENTS_DIR/$PLIST_NAME.plist"
UID_NUM="$(id -u)"

mkdir -p "$LAUNCH_AGENTS_DIR"
cp "$PLIST_SRC" "$PLIST_DEST"

# Stop any previous instance, then load fresh (RunAtLoad kicks the first pass now).
launchctl bootout "gui/$UID_NUM/$PLIST_NAME" 2>/dev/null || true
# Wait for the old instance to fully exit before bootstrapping a fresh one,
# otherwise the lingering termination can kill the newly started job.
for _ in {1..20}; do
  launchctl print "gui/$UID_NUM/$PLIST_NAME" >/dev/null 2>&1 || break
  sleep 0.5
done
launchctl bootstrap "gui/$UID_NUM" "$PLIST_DEST"
launchctl enable "gui/$UID_NUM/$PLIST_NAME" 2>/dev/null || true

echo "installed and started: $PLIST_NAME (every 5 minutes, first pass now)"
