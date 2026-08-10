"""
BlindspotDetector — pattern scan across simulations for ignored high-fit
clusters, under-explored targeting dimensions, unchallenged product
attributes, and missing competitive context (deterministic heuristics).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select


def get_user_simulation_history(db: Any, user_id: int, limit: int = 25) -> list[Any]:
    """Prior simulations for this user (newest first), via project ownership."""
    from app.models.project import Project
    from app.models.simulation import Simulation

    stmt = (
        select(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .where(Project.user_id == user_id)
        .order_by(Simulation.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_blindspot(
    db: Any,
    user_id: int,
    blindspot_type: str,
    blindspot_value: str,
) -> Any:
    from app.models.user_market_blindspot import UserMarketBlindspot

    stmt = select(UserMarketBlindspot).where(
        UserMarketBlindspot.user_id == user_id,
        UserMarketBlindspot.blindspot_type == blindspot_type,
        UserMarketBlindspot.blindspot_value == blindspot_value,
    )
    return db.execute(stmt).scalar_one_or_none()


def get_project_ids_with_competitive_analysis(db: Any, project_ids: set[int]) -> set[int]:
    """Return the subset of ``project_ids`` that have competitive data stored."""
    if not project_ids:
        return set()
    from app.models.project import Project

    stmt = select(Project.id).where(
        Project.id.in_(sorted(project_ids)),
        Project.competitive_json.is_not(None),
    )
    return {int(row) for row in db.execute(stmt).scalars().all()}


class BlindspotDetector:
    def scan(
        self,
        user_id: int | None,
        simulation: Any | None,
        cluster_weights: dict[str, float],
        conductor_result: Any,
        db: Any | None,
    ) -> None:
        if db is None or user_id is None:
            return

        try:
            history = get_user_simulation_history(db, user_id)
        except Exception:
            return
        if len(history) < 2:
            return

        for cluster_id, weight in cluster_weights.items():
            cluster_result = conductor_result.cluster_results.get(cluster_id)
            if cluster_result is None:
                continue
            conv = conductor_result.cluster_breakdown.get(cluster_id, 0.0)
            if conv > 0.25 and weight < 0.02:
                if self._seen_in_history(history, cluster_id):
                    self._upsert_blindspot(
                        db,
                        user_id=user_id,
                        blindspot_type="CLUSTER_IGNORED",
                        blindspot_value=cluster_id,
                    )

        missing = self._detect_missing_dimensions(history, simulation)
        for dim in missing:
            self._upsert_blindspot(
                db,
                user_id=user_id,
                blindspot_type="DIMENSION_MISSING",
                blindspot_value=dim,
            )

        for architect in self._detect_unchallenged_architects(history):
            self._upsert_blindspot(
                db,
                user_id=user_id,
                blindspot_type="ARCHITECT_UNCHALLENGED",
                blindspot_value=architect,
            )

        for value in self._detect_ignored_competitive_context(history, simulation, db):
            self._upsert_blindspot(
                db,
                user_id=user_id,
                blindspot_type="COMPETITOR_IGNORED",
                blindspot_value=value,
            )

    def _seen_in_history(self, history: list[Any], cluster_id: str) -> bool:
        """True if a prior run already showed high conversion for this cluster."""
        for sim in history[1:]:
            rj = sim.results_json or {}
            if not isinstance(rj, dict):
                continue
            cb = rj.get("cluster_breakdown")
            if cb is None and isinstance(rj.get("conductor"), dict):
                cb = rj["conductor"].get("cluster_breakdown")
            if isinstance(cb, dict) and float(cb.get(cluster_id, 0) or 0) > 0.25:
                return True
        return False

    def _detect_missing_dimensions(
        self,
        history: list[Any],
        simulation: Any | None,
    ) -> list[str]:
        """Flag geography / segment dimensions never varied across prior runs."""
        missing: list[str] = []
        geos: set[str] = set()
        segments: set[str] = set()
        for sim in history:
            rj = sim.results_json or {}
            if not isinstance(rj, dict):
                continue
            env = rj.get("env_params") or rj.get("environment_params")
            if isinstance(env, dict):
                g = str(env.get("geography", "") or env.get("target_geography", "")).upper()
                s = str(env.get("target_segment", "") or env.get("segment", "")).upper()
                if g:
                    geos.add(g)
                if s:
                    segments.add(s)
        if simulation and getattr(simulation, "results_json", None):
            rj = simulation.results_json or {}
            if isinstance(rj, dict):
                env = rj.get("env_params")
                if isinstance(env, dict):
                    g = str(env.get("geography", "") or "").upper()
                    if g:
                        geos.add(g)

        if len(geos) <= 1 and "TIER3" not in "".join(geos):
            missing.append("geography:TIER3_EXPLORATION")
        if len(segments) <= 1:
            missing.append("segment:B2B_VS_B2C")
        return missing

    def _detect_unchallenged_architects(
        self,
        history: list[Any],
    ) -> list[str]:
        """Return architects whose top finding repeats unchanged across >=2 runs.

        A finding that keeps coming back with the same wording means the
        founder is not questioning or varying that product attribute between
        simulations — the attribute deserves a deliberate experiment.
        """
        top_finding_by_architect: dict[str, str] = {}
        repeated: set[str] = set()
        for sim in history:
            rj = sim.results_json or {}
            if not isinstance(rj, dict):
                continue
            findings = rj.get("domain_findings")
            if not isinstance(findings, list):
                continue
            seen_in_run: set[str] = set()
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                architect = str(finding.get("architect_name") or "").strip()
                if not architect or architect in seen_in_run:
                    continue
                seen_in_run.add(architect)
                text = str(finding.get("finding") or "").strip().lower()
                if not text:
                    continue
                previous = top_finding_by_architect.get(architect)
                if previous is None:
                    top_finding_by_architect[architect] = text
                elif previous == text:
                    repeated.add(architect)
        return sorted(repeated)

    def _detect_ignored_competitive_context(
        self,
        history: list[Any],
        simulation: Any | None,
        db: Any,
    ) -> list[str]:
        """Flag when no project touched by this user's runs has competitive data."""
        project_ids: set[int] = {
            int(sim.project_id)
            for sim in history
            if getattr(sim, "project_id", None) is not None
        }
        current_project_id = getattr(simulation, "project_id", None)
        if current_project_id is not None:
            project_ids.add(int(current_project_id))
        if not project_ids:
            return []
        try:
            with_competitive = get_project_ids_with_competitive_analysis(db, project_ids)
        except Exception:
            return []
        if with_competitive:
            return []
        return ["competitive_analysis"]

    def _upsert_blindspot(
        self,
        db: Any,
        user_id: int,
        blindspot_type: str,
        blindspot_value: str,
    ) -> None:
        from app.models.user_market_blindspot import UserMarketBlindspot

        existing = get_blindspot(db, user_id, blindspot_type, blindspot_value)
        try:
            if existing:
                existing.occurrence_count = int(existing.occurrence_count) + 1
            else:
                db.add(
                    UserMarketBlindspot(
                        user_id=user_id,
                        blindspot_type=blindspot_type,
                        blindspot_value=blindspot_value,
                        occurrence_count=1,
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
