"""Unit tests for ``tools/gen_dependency_lock.py``.

The generator turns pip ``--dry-run --report`` JSON into hash-locked
requirements files that every CI install depends on. Its output format
has one sharp edge worth pinning down forever: pip only treats a line
as a continuation when it ends in a backslash, so indentation alone is
NOT enough and comments cannot follow the backslash. That shape was a
real bug during development; these tests keep it from regressing.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import URLError

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
_spec = importlib.util.spec_from_file_location(
    "gen_dependency_lock", _TOOLS_DIR / "gen_dependency_lock.py"
)
gdl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gdl)


def _report(*packages: tuple[str, str]) -> str:
    """Build a pip --report JSON payload from (name, version) pairs."""
    return json.dumps(
        {
            "install": [
                {"metadata": {"name": name, "version": version}}
                for name, version in packages
            ]
        }
    )


class TestLockFileFormat:
    def test_hash_continuations_use_trailing_backslash(self, tmp_path, monkeypatch):
        report = tmp_path / "r.json"
        out = tmp_path / "out.lock"
        report.write_text(_report(("apkg", "1.0")))
        # Three files: first two continuations end in " \", last is bare.
        monkeypatch.setattr(
            gdl,
            "fetch_all_hashes",
            lambda name, version: [
                ("a-1.0.whl", "h1"),
                ("a-1.0.tar.gz", "h2"),
                ("a-1.0-cp311.whl", "h3"),
            ],
        )

        monkeypatch.setattr(
            "sys.argv", ["gen_dependency_lock.py", str(report), str(out), "title"]
        )
        assert gdl.main() == 0

        lines = out.read_text().splitlines()
        pin_lines = [line for line in lines if line.startswith("apkg==")]
        assert pin_lines == ["apkg==1.0 \\"]
        hash_lines = [line for line in lines if "--hash=sha256:" in line]
        assert len(hash_lines) == 3
        assert all(line.startswith("    --hash=sha256:") for line in hash_lines)
        assert hash_lines[0].endswith(" \\")
        assert hash_lines[1].endswith(" \\")
        # The final hash of the whole block must NOT carry a backslash:
        # text after a continuation backslash makes the line invalid.
        assert not hash_lines[-1].endswith("\\")

    def test_pins_sorted_case_insensitively(self, tmp_path, monkeypatch):
        report = tmp_path / "r.json"
        out = tmp_path / "out.lock"
        report.write_text(_report(("Zlib", "2.0"), ("apkg", "1.0"), ("Bpkg", "1.5")))
        monkeypatch.setattr(
            gdl, "fetch_all_hashes", lambda name, version: [("x.whl", f"h-{version}")]
        )
        monkeypatch.setattr("sys.argv", ["g", str(report), str(out), "t"])

        assert gdl.main() == 0
        pins = [
            line.split(" ")[0] for line in out.read_text().splitlines() if "==" in line
        ]
        assert pins == ["apkg==1.0", "Bpkg==1.5", "Zlib==2.0"]

    def test_single_file_package_has_no_continuation(self, tmp_path, monkeypatch):
        report = tmp_path / "r.json"
        out = tmp_path / "out.lock"
        report.write_text(_report(("solo", "3.1")))
        monkeypatch.setattr(
            gdl, "fetch_all_hashes", lambda name, version: [("solo.whl", "only")]
        )
        monkeypatch.setattr("sys.argv", ["g", str(report), str(out), "t"])

        gdl.main()
        lines = out.read_text().splitlines()
        block = [line for line in lines if "==" in line or "--hash" in line]
        assert block == ["solo==3.1 \\", "    --hash=sha256:only"]


class TestFailureModes:
    def test_missing_files_reported_and_exit_nonzero(self, tmp_path, monkeypatch, capsys):
        report = tmp_path / "r.json"
        out = tmp_path / "out.lock"
        report.write_text(_report(("ghost", "9.9"), ("real", "1.0")))

        def fake_fetch(name: str, version: str) -> list[tuple[str, str]]:
            return [] if name == "ghost" else [("real.whl", "h")]

        monkeypatch.setattr(gdl, "fetch_all_hashes", fake_fetch)
        monkeypatch.setattr("sys.argv", ["g", str(report), str(out), "t"])

        exit_code = gdl.main()
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "ghost==9.9" in captured.out
        # The healthy package is still written; only the empty one failed.
        assert "real==1.0" in out.read_text()

    def test_bad_argv_prints_usage_and_exits_two(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["g", "only-one-arg"])
        assert gdl.main() == 2


class TestFetchResilience:
    def test_transient_failures_are_retried(self, monkeypatch):
        payload = json.dumps(
            {
                "urls": [
                    {"filename": "p-1.0.whl", "digests": {"sha256": "abc"}},
                    {"filename": "p-1.0.tar.gz", "digests": {}},  # no digest -> skipped
                ]
            }
        ).encode()
        attempts = {"n": 0}

        class _FakeResponse(io.BytesIO):
            def __enter__(self):  # pragma: no cover - trivial context manager
                return self

            def __exit__(self, *args) -> bool:
                return False

        def flaky_urlopen(url, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise URLError("handshake blip")
            return _FakeResponse(payload)

        monkeypatch.setattr(gdl, "urlopen", flaky_urlopen)
        monkeypatch.setattr(gdl.time, "sleep", lambda seconds: None)

        files = gdl.fetch_all_hashes("p", "1.0")
        assert attempts["n"] == 3
        assert files == [("p-1.0.whl", "abc")]

    def test_persistent_failure_raises_after_budget(self, monkeypatch):
        attempts = {"n": 0}

        def dead_urlopen(url, timeout):
            attempts["n"] += 1
            raise URLError("down")

        monkeypatch.setattr(gdl, "urlopen", dead_urlopen)
        monkeypatch.setattr(gdl.time, "sleep", lambda seconds: None)

        with pytest.raises(RuntimeError, match="unavailable after"):
            gdl.fetch_all_hashes("p", "1.0")
        assert attempts["n"] == 4

    def test_url_targets_pypi_json_api(self):
        # Guard against the host drifting away from the documented API.
        assert gdl.PYPI_JSON.format(name="requests", version="2.32.0") == (
            "https://pypi.org/pypi/requests/2.32.0/json"
        )
