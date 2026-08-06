# TheCee Autonomous Improvement Loop

This repo runs an autonomous improvement loop driven by an active Codex goal.
The loop never stops on its own; it runs until the owner says "stop".

## Cadence

- The loop interval is **5 minutes** (configurable via the `THECEE_LOOP_INTERVAL_MINUTES`
  environment variable or the `loop.interval_minutes` field in
  `.agent_loop_state.json`).
- The clock is relative to **completion**, not start: when a cycle finishes at
  `T`, the next cycle is scheduled for `T + interval` and starts automatically —
  no human command is required.
- All timestamps are stored as UTC ISO-8601 in `.agent_loop_state.json` and
  displayed in Asia/Kolkata for readability.

## Cycle contract

Each cycle completes **exactly one unit of work**:

1. `add` — one new feature (backend or, when clearly warranted, frontend).
2. `polish` — one refinement of the previous cycle's feature (or another
   existing piece of the project).
3. `add` — and so on, strictly alternating.

Every cycle must:

- Be verified (targeted tests, plus lint where applicable).
- Be committed with a descriptive message.
- Be **pushed directly to `main`** — no new PRs, no feature branches.
- Record its start time, completion time, commit, and summary via
  `python3 agent_loop.py begin|complete`.

## State & telemetry

- `agent_loop.py` — state manager (stdlib only; `python3 agent_loop.py status`).
- `.agent_loop_state.json` — authoritative per-cycle history and schedule
  (gitignored; local machine state).
- `.agent_loop_telemetry.json` — lightweight mirror of the latest cycle
  (gitignored; backwards compatible with the earlier loop).

## Stopping / resuming

- Stop: tell the agent "stop the loop", or run `python3 agent_loop.py stop`.
- Resume: set `loop.active` back to `true` in `.agent_loop_state.json`, or tell
  the agent to resume.

## Rules of engagement

- Work only for the betterment of the project.
- No destructive changes, no secret leakage, no dependency churn without a
  strong reason.
- If a cycle cannot finish, it must leave the repo in a working state
  (revert partial work, or land it only when tests pass).
