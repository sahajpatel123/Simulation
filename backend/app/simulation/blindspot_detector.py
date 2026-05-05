"""
BlindspotDetector — pattern scan across simulations for ignored high-fit clusters
and under-explored targeting dimensions (deterministic heuristics).
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
