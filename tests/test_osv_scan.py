"""Unit tests for ``tools/osv_scan.py`` — the OSV dependency scanner.

The scanner is stdlib-only so CI can run it with zero installs; these
tests keep its parsing and batching honest without touching the real
OSV API. The nested/scoped package-lock cases encode the exact tree
shapes npm emits (a wrong filter here silently drops @scope/* deps from
coverage, which is worse than not scanning at all).
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
_spec = importlib.util.spec_from_file_location("osv_scan", _TOOLS_DIR / "osv_scan.py")
osv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(osv)


class TestRequirementsParsing:
    def test_direct_pins_extras_and_comments(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text(
            "# header comment\n"
            "fastapi==0.100.0\n"
            "uvicorn[standard]==0.20.0  \n"
            "\n"
            "python_multipart==0.0.20\n"
        )
        assert osv.parse_requirements_txt(req) == [
            ("fastapi", "0.100.0"),
            ("uvicorn", "0.20.0"),
            ("python_multipart", "0.0.20"),
        ]

    def test_hash_continuation_lines_skipped(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text(
            "apkg==1.0 \\\n    --hash=sha256:abcd\n# done\n"
        )
        assert osv.parse_requirements_txt(req) == [("apkg", "1.0")]

    def test_missing_file_is_empty(self, tmp_path):
        assert osv.parse_requirements_txt(tmp_path / "nope.txt") == []


class TestPackageLockParsing:
    def _lock(self, tmp_path: Path, packages: dict) -> Path:
        lock = tmp_path / "package-lock.json"
        lock.write_text(json.dumps({"packages": packages}))
        return lock

    def test_root_entries_including_scopes_kept(self, tmp_path):
        lock = self._lock(
            tmp_path,
            {
                "": {"name": "thecee", "version": ""},
                "node_modules/react": {"version": "19.2.8"},
                "node_modules/@tanstack/react-query": {"version": "5.101.4"},
            },
        )
        assert osv.parse_package_lock_json(lock) == [
            ("@tanstack/react-query", "5.101.4"),
            ("react", "19.2.8"),
        ]

    def test_nested_copies_excluded(self, tmp_path):
        lock = self._lock(
            tmp_path,
            {
                "node_modules/nanoid": {"version": "3.3.18"},
                "node_modules/postcss/node_modules/nanoid": {"version": "3.3.16"},
            },
        )
        assert osv.parse_package_lock_json(lock) == [("nanoid", "3.3.18")]

    def test_versionless_entries_skipped(self, tmp_path):
        lock = self._lock(tmp_path, {"node_modules/link-dep": {"link": True}})
        assert osv.parse_package_lock_json(lock) == []

    def test_missing_file_is_empty(self, tmp_path):
        assert osv.parse_package_lock_json(tmp_path / "nope.json") == []


class TestOsvQuerying:
    def _batch_response(self, results: list) -> dict:
        """Build a urlopen stand-in returning one canned querybatch reply."""
        payload = json.dumps({"results": results}).encode()

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        calls: list[dict] = []

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode())
            calls.append(body)
            return _Resp(payload)

        return fake_urlopen, calls

    def test_findings_mapped_to_name_at_version(self, monkeypatch, tmp_path):
        fake, calls = self._batch_response(
            [{"vulns": [{"id": "GHSA-1"}]}, {"vulns": []}]
        )
        monkeypatch.setattr(osv, "urlopen", fake)
        monkeypatch.setattr(osv.time, "sleep", lambda s: None)

        findings = osv.query_osv([("aaa", "1.0"), ("bbb", "2.0")], "PyPI")
        assert findings == {"aaa@1.0": ["GHSA-1"]}
        assert calls[0]["queries"][0]["package"]["ecosystem"] == "PyPI"

    def test_batches_of_one_hundred(self, monkeypatch):
        captured: list[int] = []

        def counting_urlopen(request, timeout):
            body = json.loads(request.data.decode())
            captured.append(len(body["queries"]))
            empty = json.dumps({"results": [{} for _ in body["queries"]]}).encode()

            class _Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Resp(empty)

        monkeypatch.setattr(osv, "urlopen", counting_urlopen)
        monkeypatch.setattr(osv.time, "sleep", lambda s: None)

        pkgs = [(f"pkg{i}", "1.0") for i in range(250)]
        findings = osv.query_osv(pkgs, "npm")
        assert captured == [100, 100, 50]
        assert findings == {}

    def test_network_failure_raises_after_retries(self, monkeypatch):
        attempts = {"n": 0}

        def dead_urlopen(request, timeout):
            attempts["n"] += 1
            raise OSError("down")

        monkeypatch.setattr(osv, "urlopen", dead_urlopen)
        monkeypatch.setattr(osv.time, "sleep", lambda s: None)

        with pytest.raises(RuntimeError, match="unreachable after"):
            osv.query_osv([("x", "1")], "PyPI")
        assert attempts["n"] == osv._RETRY_ATTEMPTS


class TestScanEndToEnd:
    def test_python_pin_sources_includes_locks_and_specs(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("a==1\n")
        (tmp_path / "requirements-lock.txt").write_text("a==1\ntransitive==0.9\n")
        specs = tmp_path / "tools" / "lock-specs"
        specs.mkdir(parents=True)
        (specs / "runtime.txt").write_text("-r ../../requirements.txt\n")
        (specs / "tools.txt").write_text("ruff==0.16.0\n")

        sources = osv.python_pin_sources(tmp_path)
        names = [p.relative_to(tmp_path).as_posix() for p in sources]
        assert names == [
            "requirements-lock.txt",
            "requirements.txt",
            "tools/lock-specs/runtime.txt",
            "tools/lock-specs/tools.txt",
        ]

    def test_scan_dedupes_shared_pins_across_sources(self, monkeypatch, tmp_path):
        # Same direct pin listed in the manifest and its hash-lock: OSV must
        # see it once, not once per source file.
        (tmp_path / "requirements.txt").write_text("dup==1.0\nonly-manifest==2.0\n")
        (tmp_path / "requirements-lock.txt").write_text(
            "dup==1.0 \\\n    --hash=sha256:aa\nonly-lock==3.0\n"
        )
        seen: list[str] = []

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode())
            for q in body["queries"]:
                seen.append(q["package"]["name"])
            out = json.dumps({"results": [{} for _ in body["queries"]]}).encode()

            class _Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Resp(out)

        monkeypatch.setattr(osv, "urlopen", fake_urlopen)
        monkeypatch.setattr(osv.time, "sleep", lambda s: None)

        assert osv.scan(tmp_path) == {}
        assert sorted(seen) == ["dup", "only-lock", "only-manifest"]

    def test_scan_aggregates_both_ecosystems(self, monkeypatch, tmp_path):
        (tmp_path / "requirements.txt").write_text("requests==2.32.0\n")
        (tmp_path / "package-lock.json").write_text(
            json.dumps({"packages": {"node_modules/hono": {"version": "4.12.31"}}})
        )

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode())
            eco = body["queries"][0]["package"]["ecosystem"]
            ids = (
                [{"id": "PYSEC-X"}] if eco == "PyPI" else [{"id": "GHSA-Y"}]
            )
            out = json.dumps({"results": [{"vulns": ids}]}).encode()

            class _Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Resp(out)

        monkeypatch.setattr(osv, "urlopen", fake_urlopen)
        monkeypatch.setattr(osv.time, "sleep", lambda s: None)

        findings = osv.scan(tmp_path)
        assert findings == {
            "requests@2.32.0": ["PYSEC-X"],
            "hono@4.12.31": ["GHSA-Y"],
        }

    def test_main_exit_codes(self, monkeypatch, tmp_path, capsys):
        # Clean repo -> 0; vulnerable repo -> 1.
        (tmp_path / "requirements.txt").write_text("clean==1.0.0\n")

        def clean_urlopen(request, timeout):
            out = json.dumps({"results": [{}]}).encode()

            class _Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Resp(out)

        monkeypatch.setattr(osv, "urlopen", clean_urlopen)
        monkeypatch.setattr(osv.time, "sleep", lambda s: None)

        assert osv.main(["--root", str(tmp_path)]) == 0
        assert "CLEAN" in capsys.readouterr().out

        (tmp_path / "requirements.txt").write_text("bad==9.9.9\n")

        def vuln_urlopen(request, timeout):
            out = json.dumps(
                {"results": [{"vulns": [{"id": "GHSA-Z"}]}]}
            ).encode()

            class _Resp(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return _Resp(out)

        monkeypatch.setattr(osv, "urlopen", vuln_urlopen)
        assert osv.main(["--root", str(tmp_path)]) == 1
        assert "bad@9.9.9" in capsys.readouterr().out
