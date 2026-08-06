#!/bin/bash
# Stop the autonomous loop: flags the runner AND unloads the launchd agent.
set -euo pipefail

PROJECT_DIR="/Users/sahajpatel/Code/thecee"
PLIST_NAME="com.thecee.autonomous-loop"
UID_NUM="$(id -u)"

touch "$PROJECT_DIR/agent-loop/stop"
launchctl bootout "gui/$UID_NUM/$PLIST_NAME" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "stopped. To resume later, re-run agent-loop/install.sh (and remove agent-loop/stop)."
