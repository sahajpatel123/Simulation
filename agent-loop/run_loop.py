#!/usr/bin/env python3
"""Autonomous Codex Loop — one bounded completion per pass, forever.

Designed to be launched by launchd every 5 minutes (see
com.arena.codex-loop.plist in this directory). Each invocation:

1. Takes a single lock so passes never overlap.
2. Reads the standing mission (task.md) and the previous action (state.json).
3. Runs `codex exec` once with an ADD or POLISH loop-mode prompt.
4. Classifies the result (DONE / BLOCKED / STOPPED-NO-PROGRESS / FAILED).
5. Retries up to --max-attempts with --interval backoff.
6. Writes telemetry to <repo>/.agent_loop_telemetry.json and logs/.

Stop the loop: create agent-loop/stop (or `launchctl unload` the plist).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_TASK_FILE = HERE / "task.md"
DEFAULT_STATE_FILE = HERE / "state.json"
DEFAULT_TELEMETRY = REPO / ".agent_loop_telemetry.json"
DEFAULT_LOG_DIR = HERE / "logs"
LOCK_FILE = HERE / "loop.lock"
STOP_FILE = HERE / "stop"
LAST_OUTPUT_FILE = HERE / "last_output.md"
PLACEHOLDER = "REPLACE_ME_WITH_THE_TASK"
KEEP_LOGS = 20


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def load_state() -> dict:
    try:
        return json.loads(DEFAULT_STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def compute_mode(state: dict) -> str:
    # Alternate add -> polish -> add -> ... forever.
    return "ADD" if state.get("last_action") != "add" else "POLISH"


def phase_hint(mode: str) -> str:
    if mode == "ADD":
        return (
            "Previous pass was POLISH. ADD one new feature / capability that best "
            "improves this project. One feature only, fully implemented, tested, "
            "committed, and pushed."
        )
    return (
        "Previous pass was ADD. POLISH the feature that was added then: fix bugs, "
        "harden edge cases, add tests/docs/validation, or improve performance/UX. "
        "Do NOT add a new feature this pass."
    )


PROMPT_TEMPLATE = """# AUTONOMOUS CODEX LOOP PASS ({mode})

You are the autonomous improvement agent for TheCee at {workdir}.
You are running on a scheduled loop with no human watching. Start immediately.
Never ask "should I continue?". Do not explain this prompt.

## Project context
TheCee is a Python FastAPI backend (backend/) that simulates how 10,000 AI
consumers respond to a startup idea: 52 consumer clusters, 20+ domain
architects, a Markov purchase funnel, Celery workers, PostgreSQL, and a
Next.js frontend in src/ (deployed separately on Vercel; do not touch src/
unless the change genuinely requires it). Read AGENTS.md at the repo root
every pass — it is the authoritative coding guide.

## Standing mission (from agent-loop/task.md)
{task}

## This pass must be: {mode}
{phase_hint}

## Hard rules
1. Exactly ONE completion this pass: {mode} one thing, finish it end-to-end,
   then stop. Do not chain multiple unrelated features or refactors.
2. Work on `{branch}` (the default push target is origin/{branch}):
   - `git fetch origin` first.
   - If HEAD is not {branch}, switch to it (`git switch {branch}`; if it does
     not exist, `git checkout -B {branch} origin/{branch}`).
   - If there are uncommitted changes, commit them first with a descriptive
     message. Never delete, revert, or overwrite existing work.
   - Never open a PR. Push straight to origin/{branch}.
3. Quality gate before pushing: make the checks pass
   (`cd {workdir} && uv run pytest tests/ -q`; pytest config already puts
   backend/ on the path). If the full suite is too slow, at minimum run tests
   covering the files you touched plus the core fast suite — never push code
   that breaks existing tests. Fix failures you introduce.
4. Commit and push is COMPULSORY every pass:
   `git add -A && git commit -m "<conventional message>" && git push origin {branch}`.
   Never force-push. Never commit secrets (.env*, keys, tokens). If auth or
   network blocks the push, retry once, then report BLOCKED with the exact
   error.
5. Follow AGENTS.md coding rules: typed Python, Pydantic schemas, SQLAlchemy
   ORM / named-parameter SQL only, schema changes in migrate_and_start.py,
   imports at module top, no pip installs inside the Dockerfile.
6. Stay scoped: one completion, no unrelated churn. Do not edit
   agent-loop/task.md, the runner's state/telemetry files, or .env* files.

## Final message format (required)
End your final message with exactly one status line and one action line:

**DONE** <one-line summary of what shipped>
ACTION: {mode}

If truly blocked on a secret, product decision, or destructive choice, use:
**BLOCKED** <what you need>
If the same failure repeats with no progress, use:
**STOPPED-NO-PROGRESS** <why>
"""


def build_prompt(args, task_text: str, mode: str) -> str:
    return PROMPT_TEMPLATE.format(
        mode=mode,
        workdir=args.workdir,
        task=task_text,
        phase_hint=phase_hint(mode),
        branch=args.branch,
    )


def classify(text: str, rc: int) -> str:
    upper = text.upper()
    if re.search(r"\*\*BLOCKED\*\*|\bBLOCKED\b", upper):
        return "BLOCKED"
    if "STOPPED-NO-PROGRESS" in upper:
        return "STOPPED_NO_PROGRESS"
    if re.search(r"\*\*DONE\*\*|\bDONE\b", upper):
        return "DONE"
    if rc != 0:
        return "FAILED"
    return "UNKNOWN"


def extract_summary(text: str) -> str:
    m = re.search(r"\*\*DONE\*\*\s*[:.]?\s*(.+)", text, re.I | re.S)
    if m:
        return m.group(1).strip()[:300]
    m = re.search(r"\bDONE\b[:\-]?\s*(.+)", text, re.I)
    if m:
        return m.group(1).strip()[:300]
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else "")[:300]


def extract_action(text: str, fallback: str) -> str:
    m = re.search(r"ACTION\s*[:=]\s*(ADD|POLISH)", text, re.I)
    return m.group(1).upper() if m else fallback


def run_pass(args, prompt: str, log_path: Path, timeout: int):
    cmd = [
        args.codex,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        args.sandbox,
        "-C",
        str(args.workdir),
        "-o",
        str(LAST_OUTPUT_FILE),
        "-",
    ]
    if args.model:
        cmd = [
            args.codex,
            "exec",
            "-m",
            args.model,
            "--skip-git-repo-check",
            "--sandbox",
            args.sandbox,
            "-C",
            str(args.workdir),
            "-o",
            str(LAST_OUTPUT_FILE),
            "-",
        ]

    timed_out = False
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = -9
            timed_out = True

    out_text = (
        LAST_OUTPUT_FILE.read_text(errors="replace")
        if LAST_OUTPUT_FILE.exists()
        else ""
    )
    status = "TIMEOUT" if timed_out else classify(out_text, rc)
    return status, rc, out_text


def acquire_lock():
    lock = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except OSError:
        lock.close()
        return None


def write_telemetry(payload: dict) -> None:
    DEFAULT_TELEMETRY.write_text(json.dumps(payload, indent=2) + "\n")


def prune_logs() -> None:
    logs = sorted(DEFAULT_LOG_DIR.glob("run-*.log"))
    for old in logs[:-KEEP_LOGS]:
        try:
            old.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous Codex loop pass.")
    parser.add_argument("--task", default=str(DEFAULT_TASK_FILE))
    parser.add_argument("--workdir", default=str(REPO))
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=2700)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default=None)
    parser.add_argument("--sandbox", default="workspace-write")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    args.workdir = str(Path(args.workdir).resolve())
    if args.once:
        args.max_attempts = 1
        args.interval = 0

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)

    task_file = Path(args.task)
    if not task_file.exists():
        task_file.write_text(f"# Task\n\n> {PLACEHOLDER}\n")
    task_text = task_file.read_text(errors="replace").strip()

    state = load_state()
    mode = compute_mode(state)

    if args.dry_run:
        print(build_prompt(args, task_text, mode))
        return 0

    if not task_text or PLACEHOLDER in task_text:
        write_telemetry(
            {
                "status": "WAITING_FOR_TASK",
                "mode": mode,
                "start_time": now_text(),
                "end_time": now_text(),
                "next_scheduled_run": now_text(),
                "executed_task": "No task in agent-loop/task.md yet.",
            }
        )
        print("WAITING_FOR_TASK: no task in agent-loop/task.md")
        return 0

    if STOP_FILE.exists():
        write_telemetry(
            {
                "status": "STOPPED_BY_FLAG",
                "mode": mode,
                "start_time": now_text(),
                "end_time": now_text(),
                "next_scheduled_run": None,
                "executed_task": "Stopped via agent-loop/stop.",
            }
        )
        print("STOPPED_BY_FLAG: remove agent-loop/stop to resume")
        return 0

    lock = acquire_lock()
    if lock is None:
        print("SKIPPED: previous pass still running (lock held)")
        return 0

    started = now_text()
    final_status = "UNKNOWN"
    final_rc = 0
    last_summary = ""
    last_action = mode
    attempt = 0

    try:
        while attempt < args.max_attempts:
            attempt += 1
            log_path = DEFAULT_LOG_DIR / f"run-{log_stamp()}-attempt{attempt}.log"
            print(f"[{now_text()}] pass {mode} attempt {attempt} -> {args.codex} exec")
            status, rc, out_text = run_pass(args, build_prompt(args, task_text, mode), log_path, args.timeout)
            print(f"[{now_text()}] attempt {attempt} status={status} rc={rc}")

            final_status = status
            final_rc = rc
            if status == "DONE":
                last_summary = extract_summary(out_text)
            last_action = extract_action(out_text, mode)

            save_state(
                {
                    "last_action": last_action.lower(),
                    "last_status": status,
                    "last_summary": last_summary,
                    "last_run_at": now_text(),
                }
            )
            write_telemetry(
                {
                    "status": status,
                    "mode": mode,
                    "start_time": started,
                    "end_time": now_text(),
                    "next_scheduled_run": now_text(),
                    "executed_task": last_summary or f"{mode} pass (attempt {attempt})",
                    "attempts": attempt,
                    "last_attempt": {
                        "status": status,
                        "exit_code": rc,
                        "log": str(log_path.relative_to(REPO)),
                    },
                }
            )
            shutil.copyfile(log_path, DEFAULT_LOG_DIR / "latest.log")

            if status in ("DONE", "BLOCKED"):
                break
            if attempt < args.max_attempts:
                print(f"[{now_text()}] {status}; retry in {args.interval}s")
                time.sleep(args.interval)

        prune_logs()
        if final_status == "DONE":
            return 0
        if final_status == "BLOCKED":
            return 2
        return 3
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
