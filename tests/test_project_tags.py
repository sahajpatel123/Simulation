"""
Tests for the project-tags feature.

Covers four layers:

1. **Pure helpers** (``app.simulation.project_tags``) — the
   normalise/validate contract that every write path funnels through.
   Pins the case-folding, whitespace collapse, char-set, length, and
   cap behaviour so a future "simplification" of the helper can't
   silently change the contract.
2. **Schemas** — the put/delete response shapes.
3. **Duplicate payload** — tags are carried across when a project
   is duplicated (or stripped if the source has garbage).
4. **Route registration** — the new endpoints appear in the
   router with the expected shape.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalise_tags_empty_inputs_return_empty_list() -> None:
    from app.simulation.project_tags import normalise_tags

    assert normalise_tags([]) == []
    assert normalise_tags(None) == []


def test_normalise_tags_lowercases_and_strips() -> None:
    from app.simulation.project_tags import normalise_tags

    assert normalise_tags(["  SAAS  ", "V2"]) == ["saas", "v2"]


def test_normalise_tags_collapses_internal_whitespace_to_dash() -> None:
    from app.simulation.project_tags import normalise_tags

    # Three internal spaces -> one dash, surrounding spaces stripped.
    assert normalise_tags(["Q3   Launch"]) == ["q3-launch"]
    assert normalise_tags(["\tq3\tlaunch\n"]) == ["q3-launch"]


def test_normalise_tags_dedupes_case_insensitively() -> None:
    from app.simulation.project_tags import normalise_tags

    # First occurrence wins; order is preserved.
    assert normalise_tags(["saas", "SAAS", "Saas", "v2"]) == ["saas", "v2"]


def test_normalise_tags_rejects_empty_after_strip() -> None:
    from app.simulation.project_tags import normalise_tags

    with pytest.raises(ValueError):
        normalise_tags([""])
    with pytest.raises(ValueError):
        normalise_tags(["   "])


def test_normalise_tags_rejects_non_string() -> None:
    from app.simulation.project_tags import normalise_tags

    with pytest.raises(ValueError):
        normalise_tags([123])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        normalise_tags([None])  # type: ignore[list-item]


def test_normalise_tags_rejects_disallowed_chars() -> None:
    from app.simulation.project_tags import normalise_tags

    # Note: "with space" is *not* here because internal whitespace is
    # collapsed to a dash before character-set validation (so
    # ``"two words"`` becomes ``"two-words"``, which is allowed).
    for bad in ["with.dot", "with/slash", "with$dollar", "नमस्ते"]:
        with pytest.raises(ValueError):
            normalise_tags([bad])


def test_normalise_tags_allows_dash_and_underscore() -> None:
    from app.simulation.project_tags import normalise_tags

    assert normalise_tags(["ab-test", "hero_v1", "v2-beta_test"]) == [
        "ab-test",
        "hero_v1",
        "v2-beta_test",
    ]


def test_normalise_tags_rejects_overlong() -> None:
    from app.simulation.project_tags import MAX_TAG_LEN, normalise_tags

    too_long = "a" * (MAX_TAG_LEN + 1)
    with pytest.raises(ValueError):
        normalise_tags([too_long])


def test_normalise_tags_at_max_length_is_ok() -> None:
    from app.simulation.project_tags import MAX_TAG_LEN, normalise_tags

    at_limit = "a" * MAX_TAG_LEN
    assert normalise_tags([at_limit]) == [at_limit]


def test_normalise_tags_rejects_over_cap_after_dedup() -> None:
    from app.simulation.project_tags import MAX_TAGS_PER_PROJECT, normalise_tags

    # All unique, but more than the cap.
    too_many = [f"tag{i}" for i in range(MAX_TAGS_PER_PROJECT + 1)]
    with pytest.raises(ValueError):
        normalise_tags(too_many)


def test_normalise_tags_at_cap_after_dedup_is_ok() -> None:
    from app.simulation.project_tags import MAX_TAGS_PER_PROJECT, normalise_tags

    at_cap = [f"tag{i}" for i in range(MAX_TAGS_PER_PROJECT)]
    assert normalise_tags(at_cap) == at_cap


def test_normalise_tags_cap_counts_after_dedup() -> None:
    """The cap is on the *stored* list, not the raw input. If dedup
    drops the count to within the cap, the call succeeds."""
    from app.simulation.project_tags import MAX_TAGS_PER_PROJECT, normalise_tags

    raw = ["SAAS"] * (MAX_TAGS_PER_PROJECT + 5)  # all the same canonical
    assert normalise_tags(raw) == ["saas"]


def test_normalise_tags_preserves_order() -> None:
    from app.simulation.project_tags import normalise_tags

    # Insertion order is the output order; first occurrence wins on dedup.
    assert normalise_tags(["c", "a", "b", "A"]) == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_project_tags_patch_schema_default_empty() -> None:
    from app.schemas.project import ProjectTagsPatch

    p = ProjectTagsPatch()
    assert p.tags == []


def test_project_tags_patch_schema_caps_list_length() -> None:
    from app.schemas.project import ProjectTagsPatch

    # 20 is the cap; 21 must be rejected.
    ProjectTagsPatch(tags=[f"t{i}" for i in range(20)])
    with pytest.raises(Exception):
        ProjectTagsPatch(tags=[f"t{i}" for i in range(21)])


def test_project_tags_out_schema_shape() -> None:
    from app.schemas.project import ProjectTagsOut

    out = ProjectTagsOut(id=42, tags=["saas", "v2"])
    assert out.id == 42
    assert out.tags == ["saas", "v2"]


def test_project_out_includes_tags_default_empty() -> None:
    from app.schemas.project import ProjectOut

    # ``from_attributes`` lets the model fill defaults; here we just
    # confirm the field is exposed on the schema with a default.
    assert ProjectOut.model_fields["tags"].default == []


# ---------------------------------------------------------------------------
# Duplicate payload — tags must carry across
# ---------------------------------------------------------------------------


def test_duplicate_payload_copies_tags() -> None:
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={
            "title": "Source",
            "description": "An idea",
            "tags": ["saas", "v2"],
        },
        environment=None,
    )
    assert built["project"]["tags"] == ["saas", "v2"]


def test_duplicate_payload_drops_garbage_tags() -> None:
    """Non-string / non-truthy entries in the source tags list must be
    silently dropped, not propagated to the new project."""
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={
            "title": "Source",
            "description": "An idea",
            "tags": ["saas", 123, None, "", "v2"],
        },
        environment=None,
    )
    assert built["project"]["tags"] == ["saas", "v2"]


def test_duplicate_payload_handles_missing_tags_field() -> None:
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={"title": "Source", "description": "An idea"},
        environment=None,
    )
    assert built["project"]["tags"] == []


def test_duplicate_payload_handles_null_tags_field() -> None:
    from app.simulation.project_duplicate import duplicate_project_payload

    built = duplicate_project_payload(
        project={"title": "Source", "description": "An idea", "tags": None},
        environment=None,
    )
    assert built["project"]["tags"] == []


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _install_razorpay_stub() -> None:
    """Some test modules import the full app, which transitively
    imports Razorpay. Stub it out so registration tests don't need
    the real package installed."""
    if "razorpay" in sys.modules:
        return
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def test_tags_routes_registered() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    _install_razorpay_stub()
    from app.api.v1 import projects as projects_mod

    paths = {r.path for r in projects_mod.router.routes}
    assert "/projects/{project_id}/tags" in paths
    assert "/projects/{project_id}/tags/{tag}" in paths
    assert "/projects/tags" in paths


def test_tags_route_methods() -> None:
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    _install_razorpay_stub()
    from app.api.v1 import projects as projects_mod

    methods_by_path: dict[str, set[str]] = {}
    for r in projects_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "PUT" in methods_by_path["/projects/{project_id}/tags"]
    assert "DELETE" in methods_by_path["/projects/{project_id}/tags/{tag}"]
    assert "GET" in methods_by_path["/projects/tags"]


def test_list_projects_supports_tag_query_param() -> None:
    """The list endpoint must accept ``?tag=foo`` so the UI can
    filter the dashboard without a separate route."""
    pytest.importorskip("scipy", reason="Route registration requires scipy")
    _install_razorpay_stub()
    from app.api.v1 import projects as projects_mod

    # Find the GET "" route and inspect its dependency-injected params.
    for r in projects_mod.router.routes:
        if r.path == "" and "GET" in (r.methods or set()):
            # The route function is ``list_projects``; check its signature
            # has a ``tag`` parameter (FastAPI inspects it on registration).
            assert "tag" in r.dependant.path_params or any(
                p.name == "tag" for p in r.dependant.query_params
            )
            return
    raise AssertionError("GET /projects (list) route not found")