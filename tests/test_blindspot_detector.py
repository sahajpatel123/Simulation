"""
Tests for ``app.simulation.blindspot_detector`` — pure-Python pattern
scan (no DB needed — uses an in-memory fake).

Locks down:
  * the early-return short-circuits (db / user_id None)
  * history length threshold (< 2)
  * cluster_breakdown table lookup with nested 'conductor' fallback
  * high-conversion / low-weight → CLUSTER_IGNORED upsert path
  * history dedup: only fires when _seen_in_history is True
  * _detect_missing_dimensions: geography / segment heuristics
  * occurrence_count increment vs insert
  * exception rollback path
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeDB:
    """In-memory stand-in for a SQLAlchemy session. The
    BlindspotDetector's helpers are stubbed via monkeypatching in tests
    that need scan() / upsert() to actually call execute(); this fake
    just stores add/commit state."""

    def __init__(self, *, rows: list[Any] | None = None, blindspot_rows: list[Any] | None = None) -> None:
        self._rows = rows or []
        self._blindspot_rows = blindspot_rows or []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, stmt: Any) -> Any:  # pragma: no cover — overridden by helpers
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if hasattr(obj, "user_id") and obj not in self._blindspot_rows:
            self._blindspot_rows.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


# Monkeypatch helpers used inside BlindspotDetector so SQLAlchemy never
# actually runs during these tests.
import app.simulation.blindspot_detector as _bd_mod  # noqa: E402


def _install_fake_helpers(
    monkeypatch: Any,
    *,
    history: list[Any] | None = None,
    blindspot_rows: list[Any] | None = None,
    competitive_project_ids: set[int] | None = None,
    history_error: Exception | None = None,
) -> _FakeDB:
    """Stub get_user_simulation_history and get_blindspot against a fake DB."""
    state = {"history": history or [], "blindspot_rows": blindspot_rows or []}

    def fake_history(db: Any, user_id: int, limit: int = 25) -> list[Any]:
        if history_error is not None:
            raise history_error
        return list(state["history"])

    def fake_lookup(
        db: Any, user_id: int, blindspot_type: str, blindspot_value: str
    ) -> Any | None:
        for r in state["blindspot_rows"]:
            if (
                r.user_id == user_id
                and r.blindspot_type == blindspot_type
                and r.blindspot_value == blindspot_value
            ):
                return r
        return None

    def fake_competitive_lookup(db: Any, project_ids: set[int]) -> set[int]:
        return set(competitive_project_ids or [])

    monkeypatch.setattr(_bd_mod, "get_user_simulation_history", fake_history)
    monkeypatch.setattr(_bd_mod, "get_blindspot", fake_lookup)
    monkeypatch.setattr(
        _bd_mod,
        "get_project_ids_with_competitive_analysis",
        fake_competitive_lookup,
    )
    return _FakeDB(blindspot_rows=state["blindspot_rows"])


# ---------------------------------------------------------------------------
# _seen_in_history
# ---------------------------------------------------------------------------


def _sim(results_json: dict | None) -> _FakeRow:
    return _FakeRow(results_json=results_json)


def test_seen_in_history_returns_false_when_empty() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    bd = BlindspotDetector()
    assert bd._seen_in_history([], "metro_power_professional") is False


def test_seen_in_history_finds_high_conversion_in_flat_breakdown() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        # newest (skipped)
        _sim({"cluster_breakdown": {"metro": 0.5}}),
        # older — must find 0.26 here
        _sim({"cluster_breakdown": {"metro": 0.26}}),
    ]
    bd = BlindspotDetector()
    assert bd._seen_in_history(history, "metro") is True


def test_seen_in_history_returns_false_when_all_below_threshold() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim(None),
        _sim({"cluster_breakdown": {"metro": 0.20}}),
    ]
    bd = BlindspotDetector()
    assert bd._seen_in_history(history, "metro") is False


def test_seen_in_history_falls_back_to_nested_conductor_block() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim(None),
        _sim({"conductor": {"cluster_breakdown": {"metro": 0.30}}}),
    ]
    bd = BlindspotDetector()
    assert bd._seen_in_history(history, "metro") is True


def test_seen_in_history_handles_non_dict_results_json() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim(None),
        # results_json isn't a dict (corrupt row).
        _FakeRow(results_json="not a dict"),
    ]
    bd = BlindspotDetector()
    assert bd._seen_in_history(history, "metro") is False


def test_seen_in_history_skips_cluster_missing_from_breakdown() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim(None),
        _sim({"cluster_breakdown": {"other_cluster": 0.9}}),
    ]
    bd = BlindspotDetector()
    assert bd._seen_in_history(history, "metro") is False


def test_seen_in_history_treats_none_breakdown_as_zero() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim(None),
        _sim({"cluster_breakdown": {"metro": None}}),
    ]
    bd = BlindspotDetector()
    assert bd._seen_in_history(history, "metro") is False


# ---------------------------------------------------------------------------
# _detect_missing_dimensions
# ---------------------------------------------------------------------------


def test_detect_missing_dimensions_flags_no_geography_variation() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": {"geography": "METRO"}}),
        _sim({"env_params": {"geography": "METRO"}}),
    ]
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, None)
    assert "geography:TIER3_EXPLORATION" in out


def test_detect_missing_dimensions_no_flag_when_tier3_seen() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": {"geography": "METRO"}}),
        _sim({"env_params": {"geography": "TIER3"}}),
    ]
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, None)
    assert "geography:TIER3_EXPLORATION" not in out


def test_detect_missing_dimensions_flags_no_segment_variation() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": {"target_segment": "B2C"}}),
        _sim({"env_params": {"target_segment": "B2C"}}),
    ]
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, None)
    assert "segment:B2B_VS_B2C" in out


def test_detect_missing_dimensions_no_segment_flag_when_varied() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": {"target_segment": "B2C"}}),
        _sim({"env_params": {"target_segment": "B2B"}}),
    ]
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, None)
    assert "segment:B2B_VS_B2C" not in out


def test_detect_missing_dimensions_alternate_env_keys_supported() -> None:
    """``environment_params`` / ``target_geography`` / ``segment`` aliases."""
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"environment_params": {"target_geography": "METRO"}}),
        _sim({"environment_params": {"target_geography": "METRO"}}),
    ]
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, None)
    assert "geography:TIER3_EXPLORATION" in out


def test_detect_missing_dimensions_includes_current_simulation_geography() -> None:
    """The current sim's geography counts toward the seen-set."""
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": {"geography": "METRO"}}),
    ]
    current = _sim({"env_params": {"geography": "TIER3"}})
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, current)
    assert "geography:TIER3_EXPLORATION" not in out


def test_detect_missing_dimensions_skips_corrupt_env_params() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": "not-a-dict"}),
        _sim({"env_params": {"geography": "METRO"}}),
    ]
    bd = BlindspotDetector()
    out = bd._detect_missing_dimensions(history, None)
    # METRO-only → still flag TIER3 missing.
    assert "geography:TIER3_EXPLORATION" in out


# ---------------------------------------------------------------------------
# _detect_unchallenged_architects
# ---------------------------------------------------------------------------


def _finding(architect: str, text: str) -> dict:
    return {"architect_name": architect, "finding": text}


def _run_with_findings(*findings: dict, project_id: int | None = None) -> _FakeRow:
    return _FakeRow(
        project_id=project_id,
        results_json={"domain_findings": list(findings)},
    )


def test_detect_unchallenged_architects_flags_repeated_top_finding() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(
            _finding("PricingArchitect", "Price is too high"),
            project_id=1,
        ),
        _run_with_findings(
            _finding("PricingArchitect", "Price is too high"),
            project_id=2,
        ),
    ]
    bd = BlindspotDetector()
    assert bd._detect_unchallenged_architects(history) == ["PricingArchitect"]


def test_detect_unchallenged_architects_skips_changed_findings() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(_finding("PricingArchitect", "Price is too high")),
        _run_with_findings(_finding("PricingArchitect", "Price is too low")),
    ]
    bd = BlindspotDetector()
    assert bd._detect_unchallenged_architects(history) == []


def test_detect_unchallenged_architects_requires_two_runs() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(_finding("PricingArchitect", "Price is too high")),
    ]
    bd = BlindspotDetector()
    assert bd._detect_unchallenged_architects(history) == []


def test_detect_unchallenged_architects_uses_first_finding_per_run() -> None:
    """Only the top (first) finding per architect per run counts."""
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(
            _finding("PricingArchitect", "Top finding A"),
            _finding("PricingArchitect", "Lower finding A"),
        ),
        _run_with_findings(
            _finding("PricingArchitect", "Top finding A"),
            _finding("PricingArchitect", "Lower finding B"),
        ),
    ]
    bd = BlindspotDetector()
    assert bd._detect_unchallenged_architects(history) == ["PricingArchitect"]


def test_detect_unchallenged_architects_skips_corrupt_rows() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim("not-a-dict"),
        _sim({"domain_findings": [{"architect_name": "PricingArchitect"}]}),
        _run_with_findings(_finding("PricingArchitect", "Price is too high")),
    ]
    bd = BlindspotDetector()
    # Missing finding text and corrupt results_json never produce a match.
    assert bd._detect_unchallenged_architects(history) == []


def test_detect_unchallenged_architects_case_insensitive_and_sorted() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(
            _finding("PricingArchitect", "Price Is Too High"),
            _finding("TrustArchitect", "Unknown brand"),
        ),
        _run_with_findings(
            _finding("PricingArchitect", "price is too high"),
            _finding("TrustArchitect", "Different trust finding"),
        ),
    ]
    bd = BlindspotDetector()
    assert bd._detect_unchallenged_architects(history) == ["PricingArchitect"]


# ---------------------------------------------------------------------------
# _detect_ignored_competitive_context
# ---------------------------------------------------------------------------


def test_detect_ignored_competitive_context_flags_when_no_project_has_data(
    monkeypatch: Any,
) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch,
        history=[_FakeRow(project_id=1, results_json={}), _FakeRow(project_id=2, results_json={})],
        competitive_project_ids=set(),
    )
    bd = BlindspotDetector()
    assert bd._detect_ignored_competitive_context([_FakeRow(project_id=1), _FakeRow(project_id=2)], None, db) == [
        "competitive_analysis"
    ]


def test_detect_ignored_competitive_context_skips_when_any_project_has_data(
    monkeypatch: Any,
) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch,
        history=[_FakeRow(project_id=1, results_json={}), _FakeRow(project_id=2, results_json={})],
        competitive_project_ids={2},
    )
    bd = BlindspotDetector()
    out = bd._detect_ignored_competitive_context(
        [_FakeRow(project_id=1), _FakeRow(project_id=2)],
        None,
        db,
    )
    assert out == []


def test_detect_ignored_competitive_context_includes_current_simulation_project(
    monkeypatch: Any,
) -> None:
    """The current run's project counts, even when it has no prior runs yet."""
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch,
        history=[_FakeRow(project_id=1, results_json={})],
        competitive_project_ids=set(),
    )
    bd = BlindspotDetector()
    captured: list[set[int]] = []

    def capture(db: Any, project_ids: set[int]) -> set[int]:
        captured.append(set(project_ids))
        return set()

    monkeypatch.setattr(_bd_mod, "get_project_ids_with_competitive_analysis", capture)
    current = _FakeRow(project_id=7, results_json={})
    bd._detect_ignored_competitive_context([_FakeRow(project_id=1)], current, db)
    assert captured and 7 in captured[0]


def test_detect_ignored_competitive_context_returns_empty_without_project_ids(
    monkeypatch: Any,
) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(monkeypatch)
    bd = BlindspotDetector()
    assert bd._detect_ignored_competitive_context([_FakeRow(project_id=None)], None, db) == []


def test_detect_ignored_competitive_context_survives_db_failure(
    monkeypatch: Any,
) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(monkeypatch)

    def boom(db: Any, project_ids: set[int]) -> set[int]:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(_bd_mod, "get_project_ids_with_competitive_analysis", boom)
    bd = BlindspotDetector()
    out = bd._detect_ignored_competitive_context([_FakeRow(project_id=1)], None, db)
    assert out == []


# ---------------------------------------------------------------------------
# _upsert_blindspot
# ---------------------------------------------------------------------------


def test_upsert_inserts_new_when_no_existing(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(monkeypatch)
    bd = BlindspotDetector()
    bd._upsert_blindspot(
        db,
        user_id=1,
        blindspot_type="CLUSTER_IGNORED",
        blindspot_value="metro_power_professional",
    )
    assert len(db.added) == 1
    assert db.added[0].occurrence_count == 1
    assert db.commits == 1


def test_upsert_increments_occurrence_count_when_existing(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    existing = _FakeRow(
        user_id=1,
        blindspot_type="CLUSTER_IGNORED",
        blindspot_value="metro",
        occurrence_count=3,
    )
    db = _install_fake_helpers(monkeypatch, blindspot_rows=[existing])
    bd = BlindspotDetector()
    bd._upsert_blindspot(
        db,
        user_id=1,
        blindspot_type="CLUSTER_IGNORED",
        blindspot_value="metro",
    )
    assert existing.occurrence_count == 4
    assert db.added == []
    assert db.commits == 1


def test_upsert_rolls_back_on_commit_failure(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    class _BoomDB(_FakeDB):
        def commit(self) -> None:
            raise RuntimeError("simulated DB outage")

        def rollback(self) -> None:
            # Real DB rollback discards the staged add.
            self.added = []
            self.rollbacks += 1

    _install_fake_helpers(monkeypatch)
    db = _BoomDB(blindspot_rows=[])  # type: ignore[arg-type]
    bd = BlindspotDetector()
    bd._upsert_blindspot(
        db,
        user_id=1,
        blindspot_type="DIMENSION_MISSING",
        blindspot_value="geography:TIER3_EXPLORATION",
    )
    assert db.rollbacks == 1
    assert db.added == []  # real rollback discards the staged add


# ---------------------------------------------------------------------------
# scan() integration
# ---------------------------------------------------------------------------


class _FakeConductorResult:
    def __init__(self, cluster_results: dict, cluster_breakdown: dict) -> None:
        self.cluster_results = cluster_results
        self.cluster_breakdown = cluster_breakdown


def test_scan_returns_silently_when_db_is_none() -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    bd = BlindspotDetector()
    # Should not raise even with None db / user_id.
    bd.scan(
        user_id=None,
        simulation=None,
        cluster_weights={"metro": 0.5},
        conductor_result=_FakeConductorResult({}, {}),
        db=None,
    )


def test_scan_returns_when_history_below_threshold(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch, history=[_sim({"cluster_breakdown": {"metro": 0.5}})]
    )
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={"metro": 0.01},  # high conv, low weight
        conductor_result=_FakeConductorResult(
            {"metro": object()},
            {"metro": 0.30},
        ),
        db=db,
    )
    # Only one prior sim → no blindspots recorded.
    assert db.added == []


def test_scan_flags_cluster_ignored_when_history_supports(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"cluster_breakdown": {"metro": 0.5}}),  # newest — skipped
        _sim({"cluster_breakdown": {"metro": 0.30}}),  # older — supports
    ]
    db = _install_fake_helpers(monkeypatch, history=history)
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={"metro": 0.005},  # < 0.02
        conductor_result=_FakeConductorResult(
            {"metro": object()},
            {"metro": 0.30},  # > 0.25
        ),
        db=db,
    )
    added_values = [a.blindspot_value for a in db.added if a.blindspot_type == "CLUSTER_IGNORED"]
    assert "metro" in added_values


def test_scan_skips_cluster_missing_from_conductor_result(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch,
        history=[
            _sim({"cluster_breakdown": {"metro": 0.5}}),
            _sim({"cluster_breakdown": {"metro": 0.3}}),
        ],
    )
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={"metro": 0.005},
        conductor_result=_FakeConductorResult(
            {},  # metro NOT in cluster_results
            {"metro": 0.30},
        ),
        db=db,
    )
    # metro had high conv weight but no cluster_result → skip.
    assert all(getattr(a, "blindspot_value", "") != "metro" for a in db.added)


def test_scan_flags_missing_dimensions(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _sim({"env_params": {"geography": "METRO", "target_segment": "B2C"}}),
        _sim({"env_params": {"geography": "METRO", "target_segment": "B2C"}}),
    ]
    db = _install_fake_helpers(monkeypatch, history=history)
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={},
        conductor_result=_FakeConductorResult({}, {}),
        db=db,
    )
    types = {(a.blindspot_type, a.blindspot_value) for a in db.added}
    assert ("DIMENSION_MISSING", "geography:TIER3_EXPLORATION") in types
    assert ("DIMENSION_MISSING", "segment:B2B_VS_B2C") in types


def test_scan_flags_unchallenged_architect_and_ignored_competitors(
    monkeypatch: Any,
) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(
            _finding("PricingArchitect", "Price is too high"),
            project_id=1,
        ),
        _run_with_findings(
            _finding("PricingArchitect", "Price is too high"),
            project_id=2,
        ),
    ]
    db = _install_fake_helpers(
        monkeypatch,
        history=history,
        competitive_project_ids=set(),
    )
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={},
        conductor_result=_FakeConductorResult({}, {}),
        db=db,
    )
    types = {(a.blindspot_type, a.blindspot_value) for a in db.added}
    assert ("ARCHITECT_UNCHALLENGED", "PricingArchitect") in types
    assert ("COMPETITOR_IGNORED", "competitive_analysis") in types


def test_scan_skips_unchallenged_architect_when_finding_varies(
    monkeypatch: Any,
) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    history = [
        _run_with_findings(
            _finding("PricingArchitect", "Price is too high"),
            project_id=1,
        ),
        _run_with_findings(
            _finding("PricingArchitect", "Price is too low"),
            project_id=1,
        ),
    ]
    db = _install_fake_helpers(
        monkeypatch,
        history=history,
        competitive_project_ids={1},
    )
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={},
        conductor_result=_FakeConductorResult({}, {}),
        db=db,
    )
    architect_rows = [
        r for r in db.added if getattr(r, "blindspot_type", "") == "ARCHITECT_UNCHALLENGED"
    ]
    competitor_rows = [
        r for r in db.added if getattr(r, "blindspot_type", "") == "COMPETITOR_IGNORED"
    ]
    assert architect_rows == []
    assert competitor_rows == []


def test_scan_handles_db_history_lookup_failure_silently(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch,
        history=[_sim({}), _sim({})],
        history_error=RuntimeError("simulated outage"),
    )
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={"metro": 0.01},
        conductor_result=_FakeConductorResult({"metro": object()}, {"metro": 0.30}),
        db=db,
    )
    # Silent fallback — no exception, no records added.
    assert db.added == []


def test_scan_only_runs_when_user_id_is_not_none(monkeypatch: Any) -> None:
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(monkeypatch, history=[_sim({}), _sim({})])
    bd = BlindspotDetector()
    bd.scan(
        user_id=None,
        simulation=None,
        cluster_weights={"metro": 0.005},
        conductor_result=_FakeConductorResult(
            {"metro": object()}, {"metro": 0.30}
        ),
        db=db,
    )
    assert db.added == []


def test_scan_skips_high_conv_clusters_without_cluster_result(monkeypatch: Any) -> None:
    """If cluster_result is missing for a cluster, the scan must not crash and
    must not flag it as CLUSTER_IGNORED."""
    from app.simulation.blindspot_detector import BlindspotDetector

    db = _install_fake_helpers(
        monkeypatch,
        history=[_sim({"cluster_breakdown": {"metro": 0.3}}), _sim({})],
    )
    bd = BlindspotDetector()
    bd.scan(
        user_id=1,
        simulation=None,
        cluster_weights={"metro": 0.005, "missing": 0.005},
        conductor_result=_FakeConductorResult(
            {"metro": object()}, {"metro": 0.30}
        ),
        db=db,
    )
    # No CLUSTER_IGNORED rows added for "missing" (no cluster_result).
    cluster_rows = [r for r in db.added if getattr(r, "blindspot_type", "") == "CLUSTER_IGNORED"]
    assert cluster_rows == []
