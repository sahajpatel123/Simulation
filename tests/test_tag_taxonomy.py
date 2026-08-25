"""Tests for the per-user tag-taxonomy helper."""
from __future__ import annotations


def test_public_allowlist_matches_callers():
    from app.simulation import tag_taxonomy
    assert set(tag_taxonomy.__all__) == {
        "SIGNAL_OK", "SIGNAL_WATCH", "build_tag_taxonomy",
    }


def test_empty_returns_zero_state():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([])
    assert out["tag_count"] == 0
    assert out["tags"] == []


def test_passes_through_per_tag():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        ("pricing", 3),
        ("tier-3", 2),
    ])
    assert out["tag_count"] == 2


def test_sorted_by_project_count_desc():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        ("a", 1),
        ("b", 5),
        ("c", 3),
    ])
    assert [t["tag"] for t in out["tags"]] == ["b", "c", "a"]


def test_tiebreak_alphabetical_when_equal_counts():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        ("zebra", 2),
        ("alpha", 2),
        ("mango", 2),
    ])
    assert [t["tag"] for t in out["tags"]] == [
        "alpha", "mango", "zebra",
    ]


def test_dedupes_duplicate_tag_entries():
    """If the same tag appears twice (e.g. caller bug),
    we keep the first entry and ignore the rest."""
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        ("pricing", 3),
        ("pricing", 5),
    ])
    assert out["tag_count"] == 1
    assert out["tags"][0]["project_count"] == 3


def test_skips_non_tuple_entries():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        "not-a-tuple",
        None,
        ("ok", 1),
    ])
    assert out["tag_count"] == 1


def test_skips_empty_string_tag():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        ("", 5),
        ("real", 1),
    ])
    assert out["tag_count"] == 1
    assert out["tags"][0]["tag"] == "real"


def test_narrative_mentions_most_used_tag():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([
        ("pricing", 5),
        ("tier-3", 1),
    ])
    assert "pricing" in out["narrative"]
    assert "5 project" in out["narrative"]


def test_narrative_for_no_tags():
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    out = build_tag_taxonomy([])
    assert "No tags" in out["narrative"]


def test_schema_default_shape():
    from app.schemas.user import TagTaxonomyOut
    out = TagTaxonomyOut()
    assert out.tag_count == 0
    assert out.tags == []


def test_schema_round_trip():
    from app.schemas.user import TagTaxonomyOut
    from app.simulation.tag_taxonomy import build_tag_taxonomy
    payload = build_tag_taxonomy([("x", 1)])
    out = TagTaxonomyOut(**payload)
    assert out.tag_count == 1
    assert out.tags[0]["tag"] == "x"
