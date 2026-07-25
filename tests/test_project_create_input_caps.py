"""Regression tests for input caps on ProjectCreate / ProjectPatch.

ProjectCreate and ProjectPatch both accept user-supplied text that flows
into the database, the LLM, or both. Without per-item / per-field caps,
a single request could send a 10MB string (or 50 entries of 10MB each)
to the LLM, paying token cost and worker time even though the model
only uses a few thousand tokens of context.

These tests pin the cap on every text input so the gating cannot
silently regress.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreate, ProjectPatch


class TestProjectCreateCaps:
    def test_description_caps_at_5000(self) -> None:
        assert ProjectCreate(description="x" * 5000).description == "x" * 5000
        with pytest.raises(ValidationError):
            ProjectCreate(description="x" * 5001)

    def test_title_caps_at_500(self) -> None:
        assert ProjectCreate(description="d", title="x" * 500).title == "x" * 500
        with pytest.raises(ValidationError):
            ProjectCreate(description="d", title="x" * 501)

    def test_landing_page_url_caps_at_2048(self) -> None:
        r = ProjectCreate(
            description="d", landing_page_url="https://example.com/" + "x" * 2028
        )
        assert r.landing_page_url is not None
        with pytest.raises(ValidationError):
            ProjectCreate(
                description="d", landing_page_url="https://example.com/" + "x" * 2029
            )

    def test_mvp_feature_list_caps_at_50_entries(self) -> None:
        assert (
            ProjectCreate(description="d", mvp_feature_list=["x"] * 50).mvp_feature_list
            == ["x"] * 50
        )
        with pytest.raises(ValidationError):
            ProjectCreate(description="d", mvp_feature_list=["x"] * 51)

    def test_mvp_feature_list_items_cap_at_200(self) -> None:
        """Each item must be ≤200 chars; before this cap, a user could
        submit 50 strings of arbitrary length."""
        assert (
            ProjectCreate(description="d", mvp_feature_list=["x" * 200]).mvp_feature_list
            == ["x" * 200]
        )
        with pytest.raises(ValidationError):
            ProjectCreate(description="d", mvp_feature_list=["x" * 201])

    def test_existing_product_description_caps_at_5000(self) -> None:
        assert (
            ProjectCreate(
                description="d", existing_product_description="x" * 5000
            ).existing_product_description
            == "x" * 5000
        )
        with pytest.raises(ValidationError):
            ProjectCreate(description="d", existing_product_description="x" * 5001)


class TestProjectPatchCaps:
    def test_title_cap_applies_to_patch(self) -> None:
        # PATCH allows None to mean "don't change"; the cap applies
        # only when a value is supplied.
        assert ProjectPatch(title="x" * 500).title == "x" * 500
        with pytest.raises(ValidationError):
            ProjectPatch(title="x" * 501)

    def test_description_cap_applies_to_patch(self) -> None:
        assert ProjectPatch(description="x" * 5000).description == "x" * 5000
        with pytest.raises(ValidationError):
            ProjectPatch(description="x" * 5001)

    def test_patch_fields_remain_optional(self) -> None:
        assert ProjectPatch().title is None
        assert ProjectPatch().description is None
