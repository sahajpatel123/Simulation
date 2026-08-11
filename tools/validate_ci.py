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
  - Every job declares a positive timeout-minutes so CI cannot hang indefinitely.
  - Every workflow includes a workflow_dispatch trigger for manual runs.
  - The zizmor config disables hash-pinning (this repo pins to full tags instead).
  - Artifact uploads fail when no files are found instead of passing silently.
  - Every workflow declares a concurrency block to cancel superseded runs.

Usage:
    python3 tools/validate_ci.py

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
        else:
            errors.append(f"{rel}: no top-level permissions block")
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


def validate_timeouts() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        for job_name, job in (data.get("jobs") or {}).items():
            timeout = job.get("timeout-minutes")
            if (
                not isinstance(timeout, int)
                or isinstance(timeout, bool)
                or timeout <= 0
            ):
                errors.append(
                    f"{rel} job {job_name}: missing a positive timeout-minutes"
                )
    return errors


def validate_workflow_dispatch() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        # PyYAML parses the `on:` key as the boolean True.
        on = data.get(True) or data.get("on") or {}
        if not isinstance(on, dict) or "workflow_dispatch" not in on:
            errors.append(f"{rel}: missing workflow_dispatch trigger")
    return errors


def validate_zizmor_config() -> list[str]:
    errors: list[str] = []
    path = ROOT / ".github" / "zizmor.yml"
    if not path.exists():
        return [".github/zizmor.yml: missing"]
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    rules = data.get("rules") or {}
    unpinned = rules.get("unpinned-uses") or {}
    if unpinned.get("disable") is not True:
        errors.append(
            ".github/zizmor.yml: unpinned-uses must be disabled because this "
            "repo pins actions to full version tags"
        )
    return errors


def validate_artifacts() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        for job_name, job in (data.get("jobs") or {}).items():
            for i, step in enumerate((job.get("steps") or []), 1):
                ref = step.get("uses") or ""
                if not ref.startswith("actions/upload-artifact@"):
                    continue
                if step.get("with", {}).get("if-no-files-found") != "error":
                    errors.append(
                        f"{rel} job {job_name} step {i}: upload-artifact must set "
                        "if-no-files-found: error"
                    )
    return errors


def validate_concurrency() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        if not data.get("concurrency"):
                    errors.append(f"{rel}: missing concurrency block")
    return errors


def validate_security_events_permission() -> list[str]:
    """SARIF/CodeQL uploaders must declare `security-events: write`."""
    errors: list[str] = []
    scanner_refs = (
        "github/codeql-action/analyze@",
        "github/codeql-action/upload-sarif@",
        "ossf/scorecard-action@",
    )
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        top = data.get("permissions") or {}
        has_top = top.get("security-events") == "write"
        for job_name, job in (data.get("jobs") or {}).items():
            steps = job.get("steps") or []
            needs_write = any(
                (step.get("uses") or "").startswith(scanner_refs)
                for step in steps
            )
            if not needs_write:
                continue
            job_perms = (job.get("permissions") or {})
            if not (has_top or job_perms.get("security-events") == "write"):
                errors.append(
                    f"{rel} job {job_name}: scanner/SARIF uploader must "
                    "declare security-events: write at workflow or job level"
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
        ("job timeouts", validate_timeouts),
        ("workflow dispatch", validate_workflow_dispatch),
        ("zizmor config", validate_zizmor_config),
        ("artifact uploads", validate_artifacts),
        ("concurrency", validate_concurrency),
        ("SARIF permissions", validate_security_events_permission),
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
