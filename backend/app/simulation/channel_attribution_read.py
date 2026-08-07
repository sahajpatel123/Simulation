"""
Pure builder for the founder-facing channel-attribution read.

Wraps the existing ``ChannelAttributionEngine`` (currently only exposed
through generated-UI runs) into a simulation-level read. For a completed
simulation it returns per-cluster channel scores, the population-weighted
market channel ranking, the lowest-CAC channel, and a recommended budget
mix — the first "where should I spend" answer without needing a UI run.

No DB / I/O — the route layer supplies ``conductor_results`` and
``cluster_registry``; all arithmetic is deterministic.
"""
from __future__ import annotations

from typing import Any

from app.schemas.channel_attribution import (
    ChannelAttributionOut,
    ChannelClusterProfile,
    ChannelRanking,
)
from app.simulation.channel_attribution import ChannelAttributionEngine


def _channel_label(channel: str) -> str:
    return channel.replace("_", " ").title()


def _clean_mix(raw: dict[str, Any]) -> dict[str, float]:
    """Coerce a recommended-channel-mix dict to finite non-negative floats."""
    out: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0.0 and parsed <= 1.0:
            out[key] = round(parsed, 6)
    return out


def build_channel_attribution(
    results: Any,
    simulation_id: int,
    project_id: int,
    status: str,
    signal_quality: float | None,
    conductor_results: dict[str, Any],
    cluster_registry: list[dict[str, Any]],
    product_type: str,
) -> ChannelAttributionOut:
    """Compose the channel-attribution read from a completed run.

    Args:
        results: Simulation ``results_json`` (reserved for shape parity
            with sibling read builders; the engine only needs conductor
            metrics).
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any.
        conductor_results: Per-cluster architect metrics from a
            ``Conductor.run`` (``{cluster_id: {Architect: {metrics}}}`).
        cluster_registry: Registry rows with ``cluster_id``, ``name``,
            and ``population_weight``.
        product_type: Detected product type for the run.
    """
    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=simulation_id,
        conductor_results=conductor_results or {},
        cluster_registry=cluster_registry or [],
        product_type=product_type,
    )
    payload = engine.to_dict(result)

    rankings = [
        ChannelRanking.model_validate(item)
        for item in payload.get("market_channel_ranking", [])
        if isinstance(item, dict)
    ]
    profiles = [
        ChannelClusterProfile.model_validate(item)
        for item in payload.get("cluster_profiles", [])
        if isinstance(item, dict)
    ]
    mix = _clean_mix(payload.get("recommended_channel_mix") or {})
    highest_roi = str(payload.get("highest_roi_channel") or "")
    lowest_cac = str(payload.get("lowest_cac_channel") or "")
    viral = bool(payload.get("viral_growth_possible"))

    top_mix = sorted(mix.items(), key=lambda item: item[1], reverse=True)
    covered_weight = round(
        min(1.0, sum(profile.population_weight for profile in profiles)),
        6,
    )

    recommendations: list[str] = []
    if top_mix:
        recommendations.append(
            f"Prioritise {_channel_label(top_mix[0][0])} early; it is your "
            "top modelled acquisition channel."
        )
    if lowest_cac:
        recommendations.append(
            f"Lowest expected CAC channel: {_channel_label(lowest_cac)}."
        )
    if highest_roi and highest_roi != lowest_cac:
        recommendations.append(
            f"Best ROI/CAC balance starts with {_channel_label(highest_roi)}."
        )
    if viral:
        recommendations.append(
            "Some clusters already show viral coefficient > 1 — add "
            "referral/word-of-mouth incentives."
        )
    else:
        recommendations.append(
            "No cluster is viral yet; pair paid channels with retention "
            "until K reaches 1.0."
        )
    if len(top_mix) > 1:
        recommendations.append(
            f"Keep a second engine running: allocate "
            f"{round(top_mix[1][1] * 100):.0f}% to "
            f"{_channel_label(top_mix[1][0])}."
        )

    meta: dict[str, Any] = {
        "total_clusters": len(profiles),
        "covered_weight": covered_weight,
        "top_channels": [channel for channel, _ in top_mix[:5]],
        "channel_mix_count": len(mix),
    }

    return ChannelAttributionOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type,
        signal_quality=signal_quality,
        highest_roi_channel=highest_roi,
        lowest_cac_channel=lowest_cac,
        viral_growth_possible=viral,
        recommended_channel_mix=mix,
        market_channel_ranking=rankings,
        cluster_profiles=profiles,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = ["build_channel_attribution"]
