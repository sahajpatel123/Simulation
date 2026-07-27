"""Pure helpers for the per-project adoption milestones digest.

Composes a single onboarding progress payload ("have you
done the basics?") so the dashboard can show a milestone
progress bar without each component being checked
separately.

The helper is pure-Python (no SQL, no I/O). The route
layer checks each milestone source (brief, assumptions,
sims, decisions, outcomes, premortem, interventions) and
hands the booleans to :func:`build_adoption_milestones`.

Standard milestones
-------------------
1.  brief_completed         - ``brief_completed_at`` set
2.  assumptions_extracted   - at least 3 non-hidden
                              Assumption rows
3.  first_sim_run           - at least 1 Simulation
4.  first_decision_enqueued - at least 1 Decision
5.  first_outcome_recorded  - at least 1 Outcome
6.  premortem_run           - ``premortem_json`` set
7.  interventions_run       - ``interventions_json`` set
"""
from __future__ import annotations

from typing import Iterable

# Ordered list of standard onboarding milestones. The
# order is significant - the dashboard renders the
# progress bar in this exact sequence.
STANDARD_MILESTONES: tuple[str, ...] = (
    "brief_completed",
    "assumptions_extracted",
    "first_sim_run",
    "first_decision_enqueued",
    "first_outcome_recorded",
    "premortem_run",
    "interventions_run",
)

# Minimum assumption count to consider the user "done"
# extracting. Below this the founder probably re-extracted
# too early.
MIN_ASSUMPTIONS_FOR_EXTRACTED: int = 3

# Signal severity buckets — keep aligned with other tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"


def build_adoption_milestones(
    brief_completed: bool = False,
    assumption_count: int = 0,
    simulation_count: int = 0,
    decision_count: int = 0,
    outcome_count: int = 0,
    premortem_present: bool = False,
    interventions_present: bool = False,
) -> dict:
    """Compose the per-project adoption milestone progress.

    Args:
        brief_completed: ``True`` when project.brief_completed_at is set.
        assumption_count: count of non-hidden Assumption rows.
        simulation_count: count of Simulation rows.
        decision_count: count of Decision rows.
        outcome_count: count of Outcome rows.
        premortem_present: ``True`` when project.premortem_json is set.
        interventions_present: ``True`` when project.interventions_json is set.

    Returns:
        Dict matching the schema described in the module
        docstring.
    """
    completed: dict[str, bool] = {
        "brief_completed": brief_completed,
        "assumptions_extracted": (
            assumption_count >= MIN_ASSUMPTIONS_FOR_EXTRACTED
        ),
        "first_sim_run": simulation_count >= 1,
        "first_decision_enqueued": decision_count >= 1,
        "first_outcome_recorded": outcome_count >= 1,
        "premortem_run": premortem_present,
        "interventions_run": interventions_present,
    }
    completed_count = sum(1 for v in completed.values() if v)
    milestone_count = len(STANDARD_MILESTONES)
    progress_pct = (
        round(100.0 * completed_count / milestone_count)
        if milestone_count else 0
    )

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "milestone_progress_pct",
        "value": progress_pct,
        "severity": (
            SIGNAL_OK
            if completed_count == milestone_count else SIGNAL_WATCH
        ),
        "display": (
            f"{completed_count}/{milestone_count} milestones "
            f"completed ({progress_pct}%)"
        ),
    })
    if completed_count < milestone_count:
        next_milestone = next(
            (
                name for name in STANDARD_MILESTONES
                if not completed.get(name)
            ),
            None,
        )
        if next_milestone is not None:
            key_signals.append({
                "label": "next_milestone",
                "value": next_milestone,
                "severity": SIGNAL_WATCH,
                "display": f"Next: {next_milestone.replace('_', ' ')}",
            })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"{completed_count}/{milestone_count} onboarding "
        f"milestones complete ({progress_pct}%)."
    )
    if completed_count == milestone_count:
        sentences.append(
            "All standard milestones reached — you have a "
            "fully-instrumented project."
        )
    elif completed_count < milestone_count // 2:
        sentences.append(
            "The project is still in its early stages — "
            "consider running the missing steps above."
        )
    narrative = " ".join(sentences)

    return {
        "milestone_count": milestone_count,
        "completed_count": completed_count,
        "progress_pct": progress_pct,
        "milestones": completed,
        "milestone_order": list(STANDARD_MILESTONES),
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "STANDARD_MILESTONES",
    "MIN_ASSUMPTIONS_FOR_EXTRACTED",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "build_adoption_milestones",
]  # noqa: E501