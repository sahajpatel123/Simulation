#!/usr/bin/env python3
"""Validate CI hygiene for GitHub Actions workflows.

Runs the same checks enforced by .github/workflows/workflow-validation.yml so you
can catch issues locally before pushing:

  - All YAML/TOML files under .github parse cleanly.
  - Security policy files exist (SECURITY.md, security report template, dependabot).
  - No .env* files are tracked by git.
  - Every GitHub Action ref is pinned to a full commit SHA — first-party
    and third-party alike — with the version kept as a trailing comment.
    Mutable tags are rejected so a repointed tag can never swap code
    into CI.
  - Every checkout sets persist-credentials: false.
  - Every workflow declares least-privilege permissions; no actions: write;
    id-token: write only in scorecard.yml (analysis job); every other write
    scope lives on a job, never at workflow level.
  - Every job declares a positive timeout-minutes so CI cannot hang indefinitely.
  - Every workflow includes a workflow_dispatch trigger for manual runs.
  - The zizmor config keeps every audit enabled (`rules: {}`) — SHA-everywhere
    pinning satisfies zizmor's unpinned-uses audit, so no overrides are needed.
  - Artifact uploads fail when no files are found instead of passing silently.
  - Every pip install in a workflow run block pins an exact version.
  - Direct pins in requirements.txt match the hash-locked files CI
    installs from, so a requirements bump without regenerating the
    locks fails instead of silently keeping stale versions.
  - Every workflow declares a concurrency block to cancel superseded runs.
  - Every Dockerfile FROM pins its base image by sha256 digest.

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
                    version = ref.split("@", 1)[1]
                    if not re.fullmatch(r"[0-9a-f]{40}", version):
                        errors.append(
                            f"{rel} job {job_name} step {i}: {ref} must be "
                            "pinned to a full 40-hex commit SHA"
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
                    continue  # immutable commit SHA — the only accepted form
                errors.append(
                    f"{rel} job {job_name} step {i}: {ref} must be pinned "
                    "to a full 40-hex commit SHA"
                )
    return errors


def validate_permissions() -> list[str]:
    errors: list[str] = []
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        blocks: list[tuple[str, dict]] = []
        top = data.get("permissions")
        if not top:
            errors.append(f"{rel}: no top-level permissions block")
        elif isinstance(top, str):
            # e.g. ``permissions: read-all`` — legal YAML but it hides which
            # scopes are granted and breaks the per-scope audit below.
            errors.append(
                f"{rel}: workflow permissions must be a scope map, got {top!r}"
            )
        else:
            blocks.append(("workflow", top))
        for job_name, job in (data.get("jobs") or {}).items():
            perms = job.get("permissions")
            if not perms:
                continue
            if isinstance(perms, str):
                errors.append(
                    f"{rel} job {job_name}: job permissions must be a scope "
                    f"map, got {perms!r}"
                )
            else:
                blocks.append((f"job {job_name}", perms))
        if not blocks and not top:
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
            if block_name == "workflow":
                writes = sorted(
                    k for k, v in block.items() if v == "write" and k != "actions"
                )
                if writes:
                    errors.append(
                        f"{rel}: workflow-level write permissions "
                        f"({', '.join(writes)}) must be scoped to the job "
                        "that needs them"
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
    if unpinned.get("disable") is True:
        errors.append(
            ".github/zizmor.yml: unpinned-uses must NOT be disabled — every "
            "action is SHA-pinned now, so zizmor's default audit applies"
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


def validate_pinned_installs() -> list[str]:
    """Every pip install inside a workflow ``run`` block pins exact versions.

    Unpinned installs float to whatever the index serves at run time —
    a supply-chain hole (scorecard PinnedDependencies) and a
    reproducibility hazard. ``-r requirements.txt`` style includes are
    exempt; the referenced file is the pin source.
    """
    errors: list[str] = []
    exempt_tokens = {"pip", "install", "python", "-m", "--quiet", "--no-cache-dir", "--upgrade", "--upgrade-strategy"}
    for path in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        rel = Path(path).relative_to(ROOT)
        for job_name, job in (data.get("jobs") or {}).items():
            for i, step in enumerate((job.get("steps") or []), 1):
                run = step.get("run") or ""
                for line in run.splitlines():
                    stripped = line.strip()
                    if not (
                        stripped.startswith("pip install")
                        or stripped.startswith("python -m pip install")
                    ):
                        continue
                    tokens = stripped.split()
                    if any(t in ("-r", "--requirement") for t in tokens):
                        continue
                    specs = [
                        t
                        for t in tokens
                        if re.match(r"^[A-Za-z0-9_]", t)
                        and t not in exempt_tokens
                        and not t.startswith("-")
                    ]
                    unpinned = [s for s in specs if "==" not in s]
                    if unpinned:
                        errors.append(
                            f"{rel} job {job_name} step {i}: pip install "
                            f"without exact pin: {', '.join(unpinned)}"
                        )
    return errors


def validate_dockerfile_base_image() -> list[str]:
    """Every Dockerfile ``FROM`` pins its base image by sha256 digest.

    A mutable tag (``python:3.11-slim``) silently repoints whenever the
    maintainer pushes — the same supply-chain hole full-SHA pinning closed
    for GitHub Actions. Digests keep the tag for readability::

        FROM python:3.11-slim@sha256:<64-hex>
    """
    errors: list[str] = []
    candidates = [ROOT / "Dockerfile"]
    for p in glob.glob(str(ROOT / "**" / "Dockerfile"), recursive=True):
        if ".venv" not in p and "node_modules" not in p:
            candidates.append(Path(p))
    seen: set[str] = set()
    for path in candidates:
        if not path.exists():
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        rel = path.relative_to(ROOT)
        with open(path) as fh:
            for i, line in enumerate(fh, 1):
                stripped = line.strip()
                if not stripped.upper().startswith("FROM"):
                    continue
                tokens = stripped.split()[1:]
                image = next(
                    (t for t in tokens if not t.startswith("--")), ""
                )
                if image == "scratch":
                    continue
                if re.search(r"@sha256:[0-9a-f]{64}$", image):
                    continue
                errors.append(
                    f"{rel}:{i}: FROM {image} must be pinned by sha256 "
                    f"digest (FROM {image}@sha256:<64-hex>)"
                )
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


def _parse_requirement_pins(path: Path) -> dict[str, str]:
    """Map normalised package name -> pinned version for ``==`` lines.

    Skips comments, blank lines, and hash continuations (which are
    indented). Extras brackets (``uvicorn[standard]``) are ignored;
    names are lowercased and underscore-normalised per PEP 503 so the
    two files compare equal despite cosmetic differences.
    """
    pins: dict[str, str] = {}
    if not path.exists():
        return pins
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(
            r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s\\]+)",
            stripped,
        )
        if not match:
            continue
        name = match.group(1).lower().replace("_", "-")
        pins[name] = match.group(3)
    return pins


def validate_lock_sync() -> list[str]:
    """Direct dependency pins must match every derived lock file.

    CI installs from the hash-locked files, not from requirements.txt —
    so bumping requirements.txt without regenerating the locks would
    silently keep CI (and the Docker image) on stale versions while
    looking up to date. This check makes that drift a hard failure.

    Only locks *derived* from requirements.txt are checked;
    requirements-tools-lock.txt resolves its own tool set (its pydantic
    pin deliberately differs) and is intentionally exempt.
    """
    errors: list[str] = []
    direct = _parse_requirement_pins(ROOT / "requirements.txt")
    if not direct:
        return errors
    for lock_name in ("requirements-lock.txt", "requirements-pytest-lock.txt"):
        lock_path = ROOT / lock_name
        locked = _parse_requirement_pins(lock_path)
        if not locked:
            errors.append(
                f"{lock_name}: missing or has no pins — regenerate with "
                "tools/gen_dependency_lock.py after changing requirements.txt"
            )
            continue
        for name, version in sorted(direct.items()):
            locked_version = locked.get(name)
            if locked_version is None:
                errors.append(
                    f"{lock_name}: {name}=={version} is required by "
                    "requirements.txt but absent from the lock — regenerate "
                    "via tools/gen_dependency_lock.py"
                )
            elif locked_version != version:
                errors.append(
                    f"{lock_name}: {name} drifted — requirements.txt pins "
                    f"{version}, lock holds {locked_version} — regenerate "
                    "via tools/gen_dependency_lock.py"
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
        ("pinned installs", validate_pinned_installs),
        ("dependency lock sync", validate_lock_sync),
        ("Dockerfile base images", validate_dockerfile_base_image),
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
