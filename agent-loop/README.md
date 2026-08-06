# TheCee Autonomous Improvement Loop

> **Status: DISABLED.** The repo's active autonomous loop is the goal-driven
> harness documented in `AGENT_LOOP.md` (run by the Codex session itself).
> This launchd-based harness is kept as an alternative/fallback. Re-enable
> with `agent-loop/install.sh` (and remove `agent-loop/stop`) only if the
> goal-driven loop is stopped first — never run both at once.

An infinite, self-driving improvement loop for TheCee. Every **5 minutes** a
pass runs and does exactly **one** thing:

- **ADD** passes implement one new feature (insight, calibration, performance,
  observability, API ergonomics, docs, tests).
- **POLISH** passes improve the last feature or the weakest existing area.

Each pass is executed by the Codex CLI (`codex exec`) inside a sandbox; the
launchd runner then re-runs the test suite, commits, and pushes to
`origin/main` — no PRs, ever. (Git writes live in the runner, outside the
model's sandbox, so a bad model turn can never push broken code.)

## How it runs

- `agent-loop/run_loop.py` — one bounded pass per invocation: locks against
  overlap, skips when the worktree is dirty (never touches your uncommitted
  work), syncs `origin/main`, alternates ADD/POLISH via `state.json`, runs
  `codex exec` with the mission from `task.md`, re-runs the test suite,
  commits + pushes, retries once, and writes telemetry to
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
- Dirty worktree = pass skipped; the loop never touches your uncommitted work.
- The wrapper runs the full test suite itself and reverts a pass that breaks
  tests, so broken code never reaches `main`.
- The runner never edits `agent-loop/task.md`, state, or telemetry; the agent
  prompt forbids touching `.env*` and forbids destructive changes.
- Pushes are straight to `main`; force-push and PRs are forbidden by prompt.
- Failures are classified (DONE / BLOCKED / STOPPED-NO-PROGRESS / FAILED) and
  visible in telemetry + `logs/latest.log`.

## Cost & cadence

This loop calls a model roughly every 5 minutes (288 passes/day). Each pass is
bounded by `--timeout 2700` and retried at most once. Monitor
`agent-loop/status.sh`; stop anytime with `agent-loop/stop.sh`.
