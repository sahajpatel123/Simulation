#!/bin/bash
# Show loop state: launchd status, telemetry, and recent logs.
PROJECT_DIR="/Users/sahajpatel/Code/thecee"
PLIST_NAME="com.thecee.autonomous-loop"
UID_NUM="$(id -u)"

echo "--- launchd ---"
launchctl print "gui/$UID_NUM/$PLIST_NAME" 2>/dev/null | sed -n '1,25p' || echo "not loaded"
echo
echo "--- telemetry ---"
cat "$PROJECT_DIR/.agent_loop_telemetry.json" 2>/dev/null || echo "no telemetry yet"
echo
echo "--- last logs ---"
tail -n 25 "$PROJECT_DIR/agent-loop/logs/launchd.out.log" 2>/dev/null || true
tail -n 15 "$PROJECT_DIR/agent-loop/logs/launchd.err.log" 2>/dev/null || true
echo
echo "--- latest pass log ---"
tail -n 40 "$PROJECT_DIR/agent-loop/logs/latest.log" 2>/dev/null || echo "no pass logs yet"
