#!/usr/bin/env python3
"""Autonomous Codex Loop — one bounded completion per pass, forever.

Designed to be launched by launchd every 5 minutes (see
com.thecee.autonomous-loop.plist in this directory). Each invocation:

1. Takes a single lock so passes never overlap.
2. Skips if the worktree has uncommitted changes (never touches user WIP).
3. Fetches and rebases onto origin/{branch}.
4. Reads the standing mission (task.md) and the previous action (state.json).
5. Runs `codex exec` once with an ADD or POLISH loop-mode prompt.
6. Classifies the result (DONE / BLOCKED / STOPPED-NO-PROGRESS / FAILED).
7. On DONE: re-runs the test suite, then commits and pushes to origin/{branch}.
8. Retries up to --max-attempts with --interval backoff.
9. Writes telemetry to <repo>/.agent_loop_telemetry.json and logs/.

Stop the loop: create agent-loop/stop (or `launchctl unload` the plist).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
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
BASELINE_FILE = HERE / "baseline_failures.txt"
TEST_IMPORT_CHECK = "import pytest, fastapi, sqlalchemy, openai"
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
            "improves this project. One feature only, fully implemented and tested; "
            "report DONE and the wrapper will commit and push."
        )
    return (
        "Previous pass was ADD. POLISH the feature that was added then: fix bugs, "
        "harden edge cases, add tests/docs/validation, or improve performance/UX. "
        "Do NOT add a new feature this pass. Report DONE when complete; the wrapper "
        "commits and pushes."
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
2. Do NOT run any git commands (fetch, add, commit, push, switch, rebase) —
   the loop wrapper handles all git and pushes to origin/{branch}. Read-only
   git (`git status`, `git diff`, `git log`) is fine.
3. Quality gate: run `python3 -m pytest tests/ -q` from {workdir} (pytest
   config already puts backend/ on the path; the wrapper resolves a working
   test interpreter and re-runs the suite before committing). If the full
   suite is too slow, at minimum run tests covering the files you touched —
   never leave existing tests broken. Fix failures you introduce.
4. Finish with exactly one completion and report **DONE** with a one-line
   summary; the wrapper commits and pushes straight to origin/{branch}
   (never a PR, never force-push, never commit secrets like .env*).
5. Follow AGENTS.md coding rules: typed Python, Pydantic schemas, SQLAlchemy
   ORM / named-parameter SQL only, schema changes in migrate_and_start.py,
   imports at module top, no pip installs inside the Dockerfile.
6. Stay scoped: one completion, no unrelated churn. Do not edit
   agent-loop/task.md, the runner's state/telemetry files, or .env* files.
7. Work directly in this session — do NOT spawn sub-agents, delegate, or
   fork sessions. One model, one change, finished end-to-end by you.

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
    # The prompt requires the final status line to use the explicit
    # **DONE** / **BLOCKED** markers. Match those exact markers and
    # prefer DONE: feature prose legitimately contains words like
    # "blocked" (e.g. a readiness tier named BLOCKED) and must not
    # flip a completed pass into BLOCKED.
    if re.search(r"\*\*DONE\*\*", upper):
        return "DONE"
    if re.search(r"\*\*BLOCKED\*\*", upper):
        return "BLOCKED"
    if "STOPPED-NO-PROGRESS" in upper:
        return "STOPPED_NO_PROGRESS"
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


def git_cmd(args, *cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *cmd],
        cwd=args.workdir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def resolve_test_python(workdir: str) -> str | None:
    """Pick a Python interpreter that can import the app's test deps.

    The repo's ``.venv`` is uv-managed and can be empty, so fall back to
    system interpreters that actually have pytest + the app stack.
    """
    candidates = [
        os.environ.get("THECEE_TEST_PYTHON"),
        str(Path(workdir) / ".venv/bin/python"),
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        shutil.which("python3"),
    ]
    seen: set[str] = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if not Path(cand).exists():
            continue
        try:
            r = subprocess.run(
                [cand, "-c", TEST_IMPORT_CHECK],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return cand
    return None


def load_baseline() -> set[str]:
    if not BASELINE_FILE.exists():
        return set()
    return {ln.strip() for ln in BASELINE_FILE.read_text().splitlines() if ln.strip()}


def save_baseline(failed: set[str]) -> None:
    BASELINE_FILE.write_text("".join(f"{f}\n" for f in sorted(failed)))


def run_tests(args, log_path: Path, timeout: int = 900) -> tuple[int, set[str]]:
    py = args.test_python
    if not py:
        print(f"[{now_text()}] no usable test interpreter found")
        return -99, set()
    cmd = [py, "-m", "pytest", "tests/", "-q"]
    print(f"[{now_text()}] running tests: {' '.join(cmd)}")
    try:
        r = subprocess.run(
            cmd, cwd=args.workdir, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        print(f"[{now_text()}] tests timed out after {timeout}s")
        return -9, set()
    with open(log_path, "a") as f:
        f.write("\n--- wrapper test run ---\n")
        f.write(r.stdout or "")
        f.write(r.stderr or "")
    failed: set[str] = set()
    for line in (r.stdout or "").splitlines() + (r.stderr or "").splitlines():
        m = re.match(r"^(?:FAILED|ERROR)\s+(tests/\S+)", line)
        if m:
            failed.add(m.group(1))
    tail = "\n".join((r.stdout or "").strip().splitlines()[-8:])
    print(f"[{now_text()}] pytest rc={r.returncode}\n{tail}")
    return r.returncode, failed


def ship_pass(args, mode: str, summary: str, log_path: Path) -> tuple[str, int]:
    """Re-run tests, then commit and push the pass. Returns (status, rc)."""
    if not args.test_python:
        # Re-resolve in case the environment recovered since startup; a
        # pass must NEVER ship without a real test gate.
        args.test_python = resolve_test_python(args.workdir)
    if not args.test_python:
        print(
            f"[{now_text()}] no usable test interpreter; refusing to ship "
            "without a test gate"
        )
        git_cmd(args, "reset", "--hard", "HEAD")
        git_cmd(args, "clean", "-fdq")
        return "ENV_ERROR", -99

    test_rc, failed = run_tests(args, log_path)
    baseline = load_baseline()
    if not baseline:
        save_baseline(failed)
        baseline = failed
        print(
            f"[{now_text()}] established baseline with {len(baseline)} "
            "pre-existing failures"
        )
    new_failures = failed - baseline
    if new_failures:
        print(
            f"[{now_text()}] tests failed (rc={test_rc}); "
            f"{len(new_failures)} new failure(s) vs baseline; reverting this pass"
        )
        for f in sorted(new_failures)[:10]:
            print(f"  new failure: {f}")
        git_cmd(args, "reset", "--hard", "HEAD")
        git_cmd(args, "clean", "-fdq")
        return "TEST_FAILED", test_rc
    print(
        f"[{now_text()}] gate OK: {len(failed)} failing, "
        f"all within {len(baseline)}-entry baseline"
    )

    subject = (summary or f"autonomous[{mode}] improvement pass").strip()
    if len(subject) > 100:
        subject = subject[:97] + "..."
    body = f"Mode: {mode}\n\n{summary or 'Autonomous improvement pass.'}\n\nPass log: {log_path.name}"

    git_cmd(args, "add", "-A")
    c = git_cmd(args, "commit", "-m", subject, "-m", body)
    if c.returncode != 0:
        print(f"[{now_text()}] commit failed: {(c.stderr or '').strip()}")
        return "COMMIT_FAILED", c.returncode

    p = git_cmd(args, "push", "origin", args.branch, timeout=180)
    if p.returncode != 0:
        print(f"[{now_text()}] push failed: {(p.stderr or '').strip()}")
        return "PUSH_FAILED", p.returncode

    print(f"[{now_text()}] shipped [{mode}]: {subject}")
    return "DONE", 0


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
    parser.add_argument(
        "--refresh-baseline",
        action="store_true",
        help="run the suite and rewrite agent-loop/baseline_failures.txt, then exit",
    )
    args = parser.parse_args()

    args.workdir = str(Path(args.workdir).resolve())
    if args.once:
        args.max_attempts = 1
        args.interval = 0
    args.test_python = resolve_test_python(args.workdir)
    print(f"[{now_text()}] test interpreter: {args.test_python or 'NONE'}")

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

    if args.refresh_baseline:
        log_path = DEFAULT_LOG_DIR / f"baseline-{log_stamp()}.log"
        _, failed = run_tests(args, log_path)
        save_baseline(failed)
        print(f"[{now_text()}] baseline saved: {len(failed)} failing tests")
        return 0

    started = now_text()
    final_status = "UNKNOWN"
    final_rc = 0
    last_summary = ""
    attempt = 0

    try:
        # Never touch a dirty worktree — the user's uncommitted work wins.
        st = git_cmd(args, "status", "--porcelain")
        if st.returncode != 0 or st.stdout.strip():
            write_telemetry(
                {
                    "status": "SKIPPED_DIRTY",
                    "mode": mode,
                    "start_time": started,
                    "end_time": now_text(),
                    "next_scheduled_run": now_text(),
                    "executed_task": "Worktree had uncommitted changes; pass skipped.",
                }
            )
            print(
                f"[{now_text()}] SKIPPED_DIRTY: uncommitted changes present; "
                "leaving them untouched"
            )
            return 0

        print(f"[{now_text()}] worktree clean; syncing origin/{args.branch}")
        git_cmd(args, "fetch", "origin", args.branch, timeout=180)
        git_cmd(args, "pull", "--rebase", "origin", args.branch, timeout=180)

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

            if final_status == "DONE":
                final_status, final_rc = ship_pass(args, mode, last_summary, log_path)

            if final_status == "DONE":
                # Advance ADD/POLISH alternation only on shipped passes so a
                # failed pass doesn't consume the next mode.
                save_state(
                    {
                        "last_action": last_action.lower(),
                        "last_status": final_status,
                        "last_summary": last_summary,
                        "last_run_at": now_text(),
                    }
                )
            write_telemetry(
                {
                    "status": final_status,
                    "mode": mode,
                    "start_time": started,
                    "end_time": now_text(),
                    "next_scheduled_run": now_text(),
                    "executed_task": last_summary or f"{mode} pass (attempt {attempt})",
                    "attempts": attempt,
                    "last_attempt": {
                        "status": final_status,
                        "exit_code": final_rc,
                        "log": str(log_path.relative_to(REPO)),
                    },
                }
            )
            shutil.copyfile(log_path, DEFAULT_LOG_DIR / "latest.log")

            if final_status in ("DONE", "BLOCKED"):
                break
            if attempt < args.max_attempts:
                print(f"[{now_text()}] {final_status}; retry in {args.interval}s")
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
