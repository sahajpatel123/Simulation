"""Unit tests for ``tools/validate_ci.py`` — the CI hygiene enforcer.

The validator guards supply-chain pinning, least-privilege permissions, and
workflow hygiene for every push. These tests exercise each check against
synthetic workflow/Dockerfile fixtures in a temporary repo root so a
regression in the enforcer (the thing that keeps CI green) is caught by CI
itself rather than discovered as a surprise red run.
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
_spec = importlib.util.spec_from_file_location("validate_ci", _TOOLS_DIR / "validate_ci.py")
validate_ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_ci)


def _repo(tmp_path: Path) -> Path:
    """Give the validator a synthetic repo root and return it."""
    return tmp_path


@pytest.fixture()
def vci(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Load the validator module with ROOT pointed at an empty temp repo."""
    monkeypatch.setattr(validate_ci, "ROOT", _repo(tmp_path))
    return validate_ci


def _write_workflow(root: Path, body: str, name: str = "ci.yml") -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / name).write_text(textwrap.dedent(body))


MINIMAL_WORKFLOW = textwrap.dedent(
    """\
    name: t
    on:
      workflow_dispatch:
    permissions:
      contents: read
    concurrency:
      group: t-${{ github.ref }}
      cancel-in-progress: true
    jobs:
      j:
        runs-on: ubuntu-latest
        timeout-minutes: 5
        steps:
          - uses: actions/checkout@1111111111111111111111111111111111111111 # v4.0.0
            with:
              persist-credentials: false
    """
)


class TestPinnedInstalls:
    def test_flags_floating_pip_install(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            """
            name: t
            on:
              workflow_dispatch:
            permissions:
              contents: read
            concurrency:
              group: t
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: pip install requests
            """,
        )
        errors = vci.validate_pinned_installs()
        assert len(errors) == 1
        assert "requests" in errors[0]

    def test_allows_exact_pins_and_requirements_includes(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            """
            name: t
            on:
              workflow_dispatch:
            permissions:
              contents: read
            concurrency:
              group: t
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: |
                      pip install --no-cache-dir -r requirements.txt
                      pip install --quiet "ruff==0.16.0" "pyyaml==6.0.3"
            """,
        )
        assert vci.validate_pinned_installs() == []


class TestDockerfileBaseImage:
    def test_flags_mutable_tag(self, vci, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.11-slim\nRUN true\n")
        errors = vci.validate_dockerfile_base_image()
        assert len(errors) == 1
        assert "python:3.11-slim" in errors[0]
        assert "sha256" in errors[0]

    def test_allows_digest_pin_and_scratch(self, vci, tmp_path):
        digest = "a" * 64
        (tmp_path / "Dockerfile").write_text(
            f"FROM python:3.11-slim@sha256:{digest}\n"
            "FROM scratch AS builder\n"
            f"FROM alpine:3.20@sha256:{digest} AS final\n"
        )
        assert vci.validate_dockerfile_base_image() == []

    def test_digest_with_platform_flag_passes(self, vci, tmp_path):
        digest = "b" * 64
        (tmp_path / "Dockerfile").write_text(
            f"FROM --platform=linux/amd64 python:3.11-slim@sha256:{digest}\n"
        )
        assert vci.validate_dockerfile_base_image() == []


class TestSupplyChain:
    def test_rejects_mutable_action_ref(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            """
            name: t
            on:
              workflow_dispatch:
            permissions:
              contents: read
            concurrency:
              group: t
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@v4
                    with:
                      persist-credentials: false
            """,
        )
        errors = vci.validate_supply_chain()
        assert len(errors) == 1
        assert "actions/checkout@v4" in errors[0]

    def test_checkout_requires_persist_credentials_false(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            """
            name: t
            on:
              workflow_dispatch:
            permissions:
              contents: read
            concurrency:
              group: t
            jobs:
              j:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - uses: actions/checkout@1111111111111111111111111111111111111111
            """,
        )
        errors = vci.validate_supply_chain()
        assert len(errors) == 1
        assert "persist-credentials" in errors[0]

    def test_sha_pinned_checkout_with_credentials_opt_out_passes(self, vci, tmp_path):
        _write_workflow(tmp_path, MINIMAL_WORKFLOW)
        assert vci.validate_supply_chain() == []


class TestWorkflowHygiene:
    def test_missing_concurrency_flagged(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            MINIMAL_WORKFLOW.replace("concurrency:\n  group: t-${{ github.ref }}\n  cancel-in-progress: true\n", ""),
        )
        errors = vci.validate_concurrency()
        assert len(errors) == 1

    def test_missing_timeout_flagged(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            MINIMAL_WORKFLOW.replace("    timeout-minutes: 5\n", ""),
        )
        errors = vci.validate_timeouts()
        assert len(errors) == 1

    def test_actions_write_flagged(self, vci, tmp_path):
        _write_workflow(
            tmp_path,
            MINIMAL_WORKFLOW.replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: read\n  actions: write",
            ),
        )
        errors = vci.validate_permissions()
        assert any("actions: write" in e for e in errors)

    def test_workflow_level_write_scope_flagged(self, vci, tmp_path):
        # The b39f77b1 pattern: writes belong on the job that needs them so
        # a future job can't inherit them by accident.
        _write_workflow(
            tmp_path,
            MINIMAL_WORKFLOW.replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: read\n  security-events: write",
            ),
        )
        errors = vci.validate_permissions()
        assert any("workflow-level write" in e and "security-events" in e for e in errors)

    def test_job_level_write_scope_passes(self, vci, tmp_path):
        body = MINIMAL_WORKFLOW.replace(
            "jobs:",
            "jobs:\n"
            "  uploader:\n"
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 5\n"
            "    permissions:\n"
            "      security-events: write\n"
            "    steps:\n"
            "      - run: true",
        )
        _write_workflow(tmp_path, body)
        assert vci.validate_permissions() == []

    def test_string_permissions_rejected_without_crash(self, vci, tmp_path):
        # ``permissions: read-all`` used to hit dict.get on a str.
        _write_workflow(
            tmp_path,
            MINIMAL_WORKFLOW.replace(
                "permissions:\n  contents: read", "permissions: read-all"
            ),
        )
        errors = vci.validate_permissions()
        assert len(errors) == 1
        assert "scope map" in errors[0]

    def test_job_level_string_permissions_rejected(self, vci, tmp_path):
        body = MINIMAL_WORKFLOW.replace(
            "jobs:",
            "jobs:\n"
            "  j2:\n"
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 5\n"
            "    permissions: write-all\n"
            "    steps:\n"
            "      - run: true",
        )
        _write_workflow(tmp_path, body)
        errors = vci.validate_permissions()
        assert any("job j2" in e and "scope map" in e for e in errors)

    def test_minimal_valid_workflow_passes_hygiene(self, vci, tmp_path):
        _write_workflow(tmp_path, MINIMAL_WORKFLOW)
        assert vci.validate_permissions() == []
        assert vci.validate_timeouts() == []
        assert vci.validate_concurrency() == []
        assert vci.validate_workflow_dispatch() == []


class TestLockSync:
    """requirements.txt bumps must reach the hash-locked files CI installs."""

    def _write(self, tmp_path: Path, requirements: str, lock: str, pytest_lock: str | None = None) -> None:
        (tmp_path / "requirements.txt").write_text(textwrap.dedent(requirements))
        (tmp_path / "requirements-lock.txt").write_text(textwrap.dedent(lock))
        if pytest_lock is not None:
            (tmp_path / "requirements-pytest-lock.txt").write_text(
                textwrap.dedent(pytest_lock)
            )

    def test_in_sync_passes(self, vci, tmp_path):
        self._write(
            tmp_path,
            """
            fastapi==0.100.0
            uvicorn[standard]==0.20.0
            """,
            """
            # header comment
            fastapi==0.100.0 \\
                --hash=sha256:abcd
            uvicorn[standard]==0.20.0 \\
                --hash=sha256:beef
            """,
            """
            fastapi==0.100.0 \\
                --hash=sha256:abcd
            uvicorn[standard]==0.20.0 \\
                --hash=sha256:beef
            pytest==9.1.1 \\
                --hash=sha256:c0de
            """,
        )
        assert vci.validate_lock_sync() == []

    def test_version_drift_flagged(self, vci, tmp_path):
        self._write(
            tmp_path,
            "fastapi==0.101.0\n",
            "fastapi==0.100.0 \\\n    --hash=sha256:abcd\n",
            "fastapi==0.100.0 \\\n    --hash=sha256:abcd\n",
        )
        errors = vci.validate_lock_sync()
        assert len(errors) == 2
        assert all("drifted" in e for e in errors)

    def test_missing_package_flagged(self, vci, tmp_path):
        self._write(
            tmp_path,
            "fastapi==0.100.0\nnewpkg==1.0.0\n",
            "fastapi==0.100.0 \\\n    --hash=sha256:abcd\n",
            "fastapi==0.100.0 \\\n    --hash=sha256:abcd\n",
        )
        errors = vci.validate_lock_sync()
        assert len(errors) == 2
        assert all("absent from the lock" in e and "newpkg" in e for e in errors)

    def test_missing_lock_file_flagged(self, vci, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\n")
        errors = vci.validate_lock_sync()
        assert len(errors) == 2
        assert all("missing or has no pins" in e for e in errors)

    def test_name_normalisation_and_comments_ignored(self, vci, tmp_path):
        self._write(
            tmp_path,
            "# a comment\n\nPython_Multipart==0.0.20  # trailing comment\n",
            "python-multipart==0.0.20 \\\n    --hash=sha256:abcd\n",
            "python-multipart==0.0.20 \\\n    --hash=sha256:abcd\n",
        )
        assert vci.validate_lock_sync() == []

    def test_no_requirements_txt_is_noop(self, vci, tmp_path):
        assert vci.validate_lock_sync() == []


class TestZizmorConfig:
    def test_disabling_unpinned_uses_flagged(self, vci, tmp_path):
        gh = tmp_path / ".github"
        gh.mkdir(parents=True)
        (gh / "zizmor.yml").write_text(
            "rules:\n  unpinned-uses:\n    disable: true\n"
        )
        errors = vci.validate_zizmor_config()
        assert len(errors) == 1
        assert "unpinned-uses" in errors[0]

    def test_default_config_passes(self, vci, tmp_path):
        gh = tmp_path / ".github"
        gh.mkdir(parents=True)
        (gh / "zizmor.yml").write_text("rules: {}\n")
        assert vci.validate_zizmor_config() == []


class TestPreCommitPins:
    @staticmethod
    def _config(tmp_path: Path, body: str) -> None:
        (tmp_path / ".pre-commit-config.yaml").write_text(textwrap.dedent(body))

    def test_mutable_tag_flagged(self, vci, tmp_path):
        self._config(
            tmp_path,
            """\
            repos:
              - repo: https://github.com/astral-sh/ruff-pre-commit
                rev: v0.16.0
                hooks:
                  - id: ruff
            """,
        )
        errors = vci.validate_pre_commit_pins()
        assert len(errors) == 1
        assert "ruff-pre-commit" in errors[0]
        assert "40-hex" in errors[0]

    def test_sha_pin_with_local_repo_passes(self, vci, tmp_path):
        self._config(
            tmp_path,
            """\
            repos:
              - repo: https://github.com/pre-commit/pre-commit-hooks
                rev: cef0300fd0fc4d2a87a85fa2093c6b283ea36f4b # v5.0.0
                hooks:
                  - id: trailing-whitespace
              - repo: local
                hooks:
                  - id: validate-ci-hygiene
                    entry: python3 tools/validate_ci.py
                    language: system
            """,
        )
        assert vci.validate_pre_commit_pins() == []

    def test_short_sha_still_rejected(self, vci, tmp_path):
        self._config(
            tmp_path,
            """\
            repos:
              - repo: https://github.com/PyCQA/bandit
                rev: 36fd6505 # 1.7.10 (abbreviated)
                hooks:
                  - id: bandit
            """,
        )
        assert len(vci.validate_pre_commit_pins()) == 1

    def test_missing_file_is_noop(self, vci, tmp_path):
        assert vci.validate_pre_commit_pins() == []

    def test_malformed_entry_reported_without_crash(self, vci, tmp_path):
        self._config(tmp_path, "repos:\n  - just-a-string\n")
        errors = vci.validate_pre_commit_pins()
        assert len(errors) == 1
        assert "malformed" in errors[0]
