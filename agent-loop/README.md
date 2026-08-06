# TheCee Autonomous Improvement Loop

An infinite, self-driving improvement loop for TheCee. Every **5 minutes** a
pass runs and does exactly **one** thing:

- **ADD** passes implement one new feature (insight, calibration, performance,
  observability, API ergonomics, docs, tests).
- **POLISH** passes improve the last feature or the weakest existing area.

Each pass is executed by the Codex CLI (`codex exec`), is required to pass the
test suite, and **must commit + push to `origin/main`** — no PRs, ever.

## How it runs

- `agent-loop/run_loop.py` — one bounded pass per invocation: locks against
  overlap, alternates ADD/POLISH via `state.json`, runs `codex exec` with the
  mission from `task.md`, retries once, writes telemetry to
  `.agent_loop_telemetry.json` and logs to `agent-loop/logs/`.
- `com.thecee.autonomous-loop.plist` — launchd job: `StartInterval` 300 s,
  `RunAtLoad` (first pass starts immediately).
- `run_env.sh` — launchd wrapper that restores `OPENCODE_API_KEY` from
  `~/.zshrc` (launchd doesn't source shell rc files).

## Commands

```bash
agent-loop/install.sh   # install + start (first pass immediately, then every 5 min)
agent-loop/status.sh    # launchd state + telemetry + logs
agent-loop/stop.sh      # stop now and disable on reboot
```

You can also pause without uninstalling by creating `agent-loop/stop`
(runner exits with STOPPED_BY_FLAG and skips future passes until the file is
removed; `install.sh` re-arms the launchd job).

## Safety guards

- Lock file prevents overlapping passes (launchd fires every 5 min; a pass may
  take longer — the next invocation just skips while the lock is held).
- The runner never edits `agent-loop/task.md`, state, or telemetry; the agent
  prompt forbids touching `.env*` and forbids destructive changes.
- Pushes are straight to `main`; force-push and PRs are forbidden by prompt.
- Failures are classified (DONE / BLOCKED / STOPPED-NO-PROGRESS / FAILED) and
  visible in telemetry + `logs/latest.log`.

## Cost & cadence

This loop calls a model roughly every 5 minutes (288 passes/day). Each pass is
bounded by `--timeout 2700` and retried at most once. Monitor
`agent-loop/status.sh`; stop anytime with `agent-loop/stop.sh`.
