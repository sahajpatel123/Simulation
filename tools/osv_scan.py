#!/usr/bin/env python3
"""Query OSV for known vulnerabilities in every pinned dependency.

Reads every Python pin source in the repo — ``requirements.txt``, all
generated ``requirements-*-lock.txt`` hash-lock files, and the
``tools/lock-specs/*.txt`` specs — plus every resolved package (root and
nested) from ``package-lock.json``, then asks ``api.osv.dev`` about each exact
version. This mirrors how OpenSSF Scorecard's ``Vulnerabilities`` check
works: it runs osv-scanner recursively over the whole checkout with the
python requirements plugin enabled, so the hash-lock files' frozen
*transitive* versions are scanned too, not just direct pins. A clean run
here means scorecard sees a clean dependency set too — without waiting
for the weekly analysis.

Stdlib-only by design: the tool must stay installable-free so CI can
run it straight after ``actions/setup-python`` with no hash-locked
toolchain, and so it cannot itself become a supply-chain question.

Exit status: 0 = no known vulnerabilities, 1 = findings,
2 = malformed environment (missing manifests, network failure).

Usage:
    python tools/osv_scan.py [--json] [--root REPO_ROOT]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

OSV_QUERYBATCH = "https://api.osv.dev/v1/querybatch"
_BATCH_SIZE = 100
_RETRY_ATTEMPTS = 4

_REQ_PIN = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s\\]+)"
)


def parse_requirements_txt(path: Path) -> list[tuple[str, str]]:
    """Direct ``name==version`` pins; comments and continuations ignored."""
    if not path.exists():
        return []
    pins: list[tuple[str, str]] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _REQ_PIN.match(stripped)
        if match:
            pins.append((match.group(1), match.group(3)))
    return pins


def parse_package_lock_json(path: Path) -> list[tuple[str, str]]:
    """Every resolved package from an npm lockfile v2/v3 ``packages`` map.

    Entries are ``node_modules/<name>`` keys; ``<name>`` may contain one
    slash for scopes (``@scope/pkg``). Nested copies
    (``node_modules/x/node_modules/y``) are included on purpose: npm
    installs them for their subtree when ranges force duplication, and
    scorecard's recursive osv-scanner scans them — skipping them would
    open a parity gap where this tool reports CLEAN while scorecard
    flags a vulnerable nested pin. Identical ``name@version`` pairs from
    multiple paths are deduplicated so batches stay minimal.
    """
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    prefix = "node_modules/"
    unique: dict[tuple[str, str], None] = {}
    for key, meta in sorted((data.get("packages") or {}).items()):
        if not key.startswith(prefix):
            continue
        name = key[len(prefix) :].split("/node_modules/")[-1]
        version = meta.get("version")
        if version:
            unique[(name, version)] = None
    return sorted(unique)


def _post_with_retry(payload: dict, attempts: int = _RETRY_ATTEMPTS) -> dict:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            req = Request(  # noqa: S310 - fixed https host
                OSV_QUERYBATCH,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https host
                result: dict = json.load(resp)
            return result
        except (URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"OSV API unreachable after {attempts} attempts") from last_exc


def query_osv(
    packages: list[tuple[str, str]], ecosystem: str
) -> dict[str, list[str]]:
    """Map ``name@version`` -> advisory IDs for every package with findings."""
    queries = [
        {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
        for name, version in packages
    ]
    findings: dict[str, list[str]] = {}
    for start in range(0, len(queries), _BATCH_SIZE):
        chunk = queries[start : start + _BATCH_SIZE]
        results = _post_with_retry({"queries": chunk}).get("results", [])
        for query, result in zip(chunk, results):
            ids = [v["id"] for v in (result.get("vulns") or [])]
            if ids:
                key = f"{query['package']['name']}@{query['version']}"
                findings[key] = ids
    return findings


def python_pin_sources(root: Path) -> list[Path]:
    """Every in-repo file scorecard's recursive osv-scanner would parse.

    The hash-lock files matter most: they freeze every transitive
    dependency at generation time, so an advisory published after the
    last regeneration only shows up here — never in ``requirements.txt``.
    """
    paths = sorted(root.glob("requirements*.txt"))
    specs = root / "tools" / "lock-specs"
    if specs.is_dir():
        paths.extend(sorted(specs.glob("*.txt")))
    return paths


def scan(root: Path) -> dict[str, list[str]]:
    """Scan both ecosystems under ``root`` and return all findings."""
    findings: dict[str, list[str]] = {}
    py_pins: dict[tuple[str, str], None] = {}
    for path in python_pin_sources(root):
        for pin in parse_requirements_txt(path):
            py_pins[pin] = None
    if py_pins:
        findings.update(query_osv(list(py_pins), "PyPI"))
    npm_pins = parse_package_lock_json(root / "package-lock.json")
    if npm_pins:
        findings.update(query_osv(npm_pins, "npm"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repo root containing requirements.txt / package-lock.json",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)

    try:
        findings = scan(args.root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(findings, indent=2, sort_keys=True))
    elif findings:
        print(f"{len(findings)} pinned dependencies have known advisories:")
        for pkg, ids in sorted(findings.items()):
            print(f"  {pkg}: {', '.join(ids)}")
    else:
        print("CLEAN: no known OSV vulnerabilities for any pinned version")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
