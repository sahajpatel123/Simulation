#!/usr/bin/env bash
# Regenerate all three hash-locked requirements files from their specs.
#
# Why local and not CI: resolution inherently needs bare `pip install
# --dry-run --report` (you cannot hash-resolve before resolving), and any
# such line in a workflow re-opens scorecard's PinnedDependencies findings
# — the exact alerts the hash-locking closed. Regeneration therefore runs
# on a developer machine, where the probe doesn't look, and pushes its
# output as part of the same commit as the requirements.txt bump.
#
# Deterministic by construction: every direct pin is == (see lock-specs/),
# so the same python/pip pair reproduces byte-identical versions. Use
# python 3.11 + pip 25.2 (the CI interpreter pair) for best fidelity.
#
# Usage:
#   tools/regen_locks.sh            # regenerate all three locks
#   tools/regen_locks.sh runtime    # just one: runtime | pytest | tools

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PYTHON="${PYTHON:-python3}"
PIP="${PIP:-pip3}"

regen() {
	local name="$1"
	case "$name" in
	runtime | pytest | tools) ;;
	*)
		echo "Unknown lock '$name' — expected runtime, pytest, or tools" >&2
		exit 2
		;;
	esac
	local spec="tools/lock-specs/${name}.txt"
	# Map spec name -> shipped lock filename.
	local out
	case "$name" in
	runtime) out="requirements-lock.txt" ;;
	pytest) out="requirements-pytest-lock.txt" ;;
	tools) out="requirements-tools-lock.txt" ;;
	esac

	echo "== resolving $spec"
	"$PIP" install --quiet --dry-run --ignore-installed --only-binary :all: \
		--report "$TMP/$name.json" -r "$spec"

	echo "== fetching hashes -> $out"
	"$PYTHON" tools/gen_dependency_lock.py "$TMP/$name.json" "$out" "$name"

	echo "== verifying $out installs clean with --require-hashes"
	"$PIP" install --quiet --dry-run --require-hashes -r "$out"
}

targets=("$@")
if [ ${#targets[@]} -eq 0 ]; then
	targets=(runtime pytest tools)
fi

for target in "${targets[@]}"; do
	regen "$target"
done

echo "All locks regenerated and verified."
