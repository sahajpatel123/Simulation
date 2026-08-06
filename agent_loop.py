#!/usr/bin/env python3
"""Autonomous improvement-loop state manager for TheCee.

Tracks each cycle's live timestamps (start / completion), computes the next
auto-triggered run, and keeps the telemetry file in sync.

Protocol
--------
1. The loop wakes and checks ``next_run``. If ``now < next_run`` it waits
   until the scheduled time before starting work.
2. ``begin`` records the cycle start.
3. Work completes exactly ONE unit (feature add or polish, alternating).
4. Tests pass, the change is committed, and the branch is pushed to main.
5. ``complete`` records completion, computes
   ``next_run = completed_at + interval``, and flips the mode for the next
   cycle so add/polish strictly alternate.

Usage
-----
    python3 agent_loop.py status
    python3 agent_loop.py begin 1 add --summary "..."
    python3 agent_loop.py complete 1 --summary "..." --commit abc1234 --tests "358 passed"

State lives in ``.agent_loop_state.json``; ``.agent_loop_telemetry.json`` is
kept as a lightweight mirror for the previous convention.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".agent_loop_state.json"
TELEMETRY_FILE = ROOT / ".agent_loop_telemetry.json"
IST = ZoneInfo("Asia/Kolkata")

DEFAULT_INTERVAL_MINUTES = int(os.environ.get("THECEE_LOOP_INTERVAL_MINUTES", "5"))
VALID_MODES = {"setup", "add", "polish"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S %Z")


def _default_state() -> dict:
    return {
        "loop": {
            "active": True,
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "cadence": "next cycle starts interval_minutes after the previous cycle completed",
            "alternation": "add -> polish -> add -> polish (strictly alternating)",
            "branch": "main",
            "push_policy": "commit and push to main every cycle; no new PRs",
            "created_at": _iso(_now_utc()),
        },
        "cycles": [],
        "last_completed_cycle": 0,
        "next_cycle": 1,
        "next_mode": "add",
        "next_run": None,
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            defaults = _default_state()
            defaults.update(data)
            return defaults
        except (json.JSONDecodeError, OSError):
            pass
    return _default_state()


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    last = state["cycles"][-1] if state["cycles"] else {}
    telemetry = {
        "status": "ACTIVE" if state["loop"]["active"] else "STOPPED",
        "cycle": state.get("last_completed_cycle"),
        "mode": last.get("mode"),
        "start_time": last.get("started_at"),
        "end_time": last.get("completed_at"),
        "next_scheduled_run": state.get("next_run"),
        "interval_minutes": state["loop"]["interval_minutes"],
        "executed_task": last.get("summary", ""),
        "commit": last.get("commit"),
        "tests": last.get("tests"),
    }
    TELEMETRY_FILE.write_text(
        json.dumps(telemetry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def cmd_status() -> int:
    state = load_state()
    now = _now_utc()
    print(f"Loop active:      {state['loop']['active']}")
    print(f"Interval:         {state['loop']['interval_minutes']} min after completion")
    print(f"Next cycle:       #{state['next_cycle']} ({state['next_mode']})")
    print(f"Now (IST):        {_ist(now)}")
    if state.get("next_run"):
        next_run = datetime.fromisoformat(state["next_run"])
        remaining = next_run - now
        wait_min = max(0.0, remaining.total_seconds() / 60.0)
        print(f"Next scheduled:   {_ist(next_run)}  (in {wait_min:.1f} min)")
    else:
        print("Next scheduled:   immediately (no prior cycle)")
    if state["cycles"]:
        last = state["cycles"][-1]
        print(f"Last cycle:       #{last['cycle']} ({last['mode']}) completed {_ist(datetime.fromisoformat(last['completed_at']))}")
        print(f"  summary:        {last.get('summary', '')}")
        if last.get("commit"):
            print(f"  commit:         {last['commit']}")
    print(f"Cycles completed: {len(state['cycles'])}")
    return 0


def cmd_begin(cycle: int, mode: str, summary: str) -> int:
    state = load_state()
    if not state["loop"]["active"]:
        print("Loop is stopped; refusing to begin a cycle.", file=__import__("sys").stderr)
        return 1
    if mode not in VALID_MODES:
        print(f"Invalid mode {mode!r}; expected one of {sorted(VALID_MODES)}", file=__import__("sys").stderr)
        return 1
    now = _now_utc()
    state["cycles"].append(
        {
            "cycle": cycle,
            "mode": mode,
            "summary": summary or "",
            "started_at": _iso(now),
            "completed_at": None,
            "next_run": None,
            "commit": None,
            "tests": None,
        }
    )
    state["next_cycle"] = cycle
    state["next_mode"] = mode
    save_state(state)
    print(f"Cycle #{cycle} ({mode}) started at {_ist(now)}")
    return 0


def cmd_complete(cycle: int, summary: str, commit: str, tests: str) -> int:
    state = load_state()
    if not state["cycles"] or state["cycles"][-1]["cycle"] != cycle:
        print(f"No started cycle #{cycle} found; call begin first.", file=__import__("sys").stderr)
        return 1
    now = _now_utc()
    entry = state["cycles"][-1]
    entry["completed_at"] = _iso(now)
    entry["summary"] = summary or entry.get("summary", "")
    entry["commit"] = commit or None
    entry["tests"] = tests or None
    interval = timedelta(minutes=state["loop"]["interval_minutes"])
    next_run = now + interval
    entry["next_run"] = _iso(next_run)
    state["last_completed_cycle"] = cycle
    state["next_cycle"] = cycle + 1
    state["next_mode"] = "add" if entry["mode"] in {"polish", "setup"} else "polish"
    state["next_run"] = entry["next_run"]
    save_state(state)
    print(f"Cycle #{cycle} ({entry['mode']}) completed at {_ist(now)}")
    print(f"Next cycle (#{state['next_cycle']}, {state['next_mode']}) scheduled for {_ist(next_run)}")
    return 0


def cmd_stop() -> int:
    state = load_state()
    state["loop"]["active"] = False
    save_state(state)
    print("Loop marked STOPPED. Set loop.active=true (or tell the agent to resume) to restart.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TheCee autonomous loop state manager")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show current loop state and schedule")

    p_begin = sub.add_parser("begin", help="record the start of a cycle")
    p_begin.add_argument("cycle", type=int)
    p_begin.add_argument("mode", choices=sorted(VALID_MODES))
    p_begin.add_argument("--summary", default="")

    p_complete = sub.add_parser("complete", help="record cycle completion and schedule next run")
    p_complete.add_argument("cycle", type=int)
    p_complete.add_argument("--summary", default="")
    p_complete.add_argument("--commit", default="")
    p_complete.add_argument("--tests", default="")

    sub.add_parser("stop", help="mark the loop as stopped")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        return cmd_status()
    if args.command == "begin":
        return cmd_begin(args.cycle, args.mode, args.summary)
    if args.command == "complete":
        return cmd_complete(args.cycle, args.summary, args.commit, args.tests)
    if args.command == "stop":
        return cmd_stop()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
