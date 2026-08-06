#!/bin/zsh
# launchd does not source ~/.zshrc, so pull out just the API key the codex
# CLI needs (OPENCODE_API_KEY), then hand off to the loop runner.
if [[ -f "$HOME/.zshrc" ]]; then
  line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?OPENCODE_API_KEY=' "$HOME/.zshrc" | tail -1)"
  if [[ -n "$line" ]]; then
    val="${line#*=}"
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    export OPENCODE_API_KEY="$val"
  fi
fi
export PATH="/Users/sahajpatel/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] loop pass starting (env loaded)"
exec /opt/homebrew/bin/python3 -u /Users/sahajpatel/Code/thecee/agent-loop/run_loop.py "$@"
