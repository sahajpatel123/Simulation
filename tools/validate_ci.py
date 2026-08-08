#!/usr/bin/env python3
"""Validate CI hygiene for GitHub Actions workflows.

Runs the same checks enforced by .github/workflows/workflow-validation.yml so you
can catch issues locally before pushing:

  - All YAML/TOML files under .github parse cleanly.
  - Security policy files exist (SECURITY.md, security report template, dependabot).
  - No .env* files are tracked by git.
  - Every GitHub Action ref is pinned to a full version tag or full commit SHA.
  - Every checkout sets persist-credentials: false.
  - Every workflow declares least-privilege permissions; no actions: write;
    id-token: write only in scorecard.yml.

Usage:
    python3 scripts/validate_ci.py

Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def emit_error(message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error::{message}")
    else:
        print(f"ERROR: {message}")


def validate_yaml() -> list[str]:
    errors: list[str] = []
    files = glob.glob(str(ROOT / ".github" / "**" / "*.yml"), recursive=True)
    files += glob.glob(str(ROOT / ".github" / "**" / "*.yaml"), recursive=True)
    for path in sorted(files):
        try:
            with open(path) as fh:
                yaml.safe_load(fh)
        except Exception as exc:
            errors.append(f"{Path(path).relative_to(ROOT)}: invalid YAML: {exc}")
    return errors


def validate_toml() -> list[str]:
    errors: list[str] = []
    for path in (ROOT / "pyproject.toml", ROOT / ".github" / "gitleaks.toml"):
        if not path.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing")
            continue
        try:
            with open(path, "rb") as fh:
                tomllib.load(fh)
        except Exception as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid TOML: {exc}")
    return errors


def validate_security_policy() -> list[str]:
    errors: list[str] = []
    required = [
        "SECURITY.md",
        ".github/ISSUE_TEMPLATE/security_report.md",
        ".github/dependabot.yml",
    ]
    for rel in required:
        if not (ROOT / rel).exists():
            errors.append(f"{rel}: missing")
    if (ROOT / ".github" / "dependabot.yml").exists():
        try:
            with open(ROOT / ".github" / "dependabot.yml") as fh:
                yaml.safe_load(fh)
        except Exception as exc:
            errors.append(f".github/dependabot.yml: invalid YAML: {exc}")
    return errors


def validate_env_files() -> list[str]:
    errors: list[str] = []
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = result.stdout.splitlines()
    for line in tracked:
        if re.search(r"(^|/)\.env(\.local|\.production)?$", line):
            errors.append(f"environment file is tracked by git: {line}")
    return errors


def validate_supply_chain() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        for job_name, job in (data.get("jobs") or {}).items():
            for i, step in enumerate((job.get("steps") or []), 1):
                ref = step.get("uses") or ""
                if not ref:
                    continue
                if ref.startswith("actions/checkout@"):
                    if "persist-credentials" not in step.get("with", {}):
                        errors.append(
                            f"{rel} job {job_name} step {i}: checkout must set "
                            "persist-credentials: false"
                        )
                    continue
                if ref.startswith("docker://"):
                    if ref.count(":") < 2:
                        errors.append(
                            f"{rel} job {job_name} step {i}: {ref} not pinned "
                            "to a specific tag"
                        )
                    continue
                _, _, version = ref.partition("@")
                if re.fullmatch(r"[0-9a-f]{40}", version or ""):
                    continue  # full commit SHA is acceptable
                if not version or version.count(".") < 2:
                    errors.append(
                        f"{rel} job {job_name} step {i}: {ref} is not pinned "
                        "to a full version tag"
                    )
    return errors


def validate_permissions() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        blocks: list[tuple[str, dict]] = []
        if data.get("permissions"):
            blocks.append(("workflow", data["permissions"]))
        for job_name, job in (data.get("jobs") or {}).items():
            if job.get("permissions"):
                blocks.append((f"job {job_name}", job["permissions"]))
        if not blocks:
            errors.append(f"{rel}: no permissions block")
        for block_name, block in blocks:
            if block.get("actions") == "write":
                errors.append(
                    f"{rel} {block_name}: actions: write is too broad; "
                    "use actions: read or omit"
                )
            if "scorecard.yml" not in rel.name and block.get("id-token") == "write":
                errors.append(
                    f"{rel} {block_name}: id-token: write is only allowed in "
                    "scorecard.yml"
                )
    return errors


def main() -> int:
    checks = [
        ("YAML", validate_yaml),
        ("TOML", validate_toml),
        ("security policy", validate_security_policy),
        ("env-file tracking", validate_env_files),
        ("supply-chain pinning", validate_supply_chain),
        ("least-privilege permissions", validate_permissions),
    ]
    errors: list[str] = []
    for label, func in checks:
        found = func()
        if found:
            errors.append(f"{label}:")
            errors.extend(f"  {e}" for e in found)
    if errors:
        for e in errors:
            emit_error(e)
        return 1
    print("✅ CI hygiene checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
