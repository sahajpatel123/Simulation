"""
Base interface for all TheCee simulation architects.

Every architect (PricingArchitect, OnboardingArchitect, etc.) must
subclass BaseArchitect and implement compute() and generate_report().
The Conductor calls compute() once per cluster per simulation run,
then calls generate_report() across all outputs to produce the
cross-cluster domain summary.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.simulation.clusters.definitions import ClusterDefinition


@dataclass(frozen=True)
class ArchitectOutput:
    """Per-cluster output produced by one architect for one simulation run."""
    architect_name:     str
    cluster_id:         str
    metrics:            dict[str, float]
    flags:              dict[str, bool]
    narrative_findings: list[str]
    severity:           str          # INFO | WARNING | CRITICAL


@dataclass(frozen=True)
class DomainReport:
    """
    Cross-cluster summary produced by generate_report().
    One DomainReport per architect per simulation run.
    """
    architect_name:       str
    primary_finding:      str
    affected_cluster_ids: list[str]
    population_fraction:  float
    conversion_impact:    float
    recommended_action:   str
    severity:             str        # INFO | WARNING | CRITICAL


class BaseArchitect(ABC):
    """
    Abstract base class for all TheCee simulation architects.

    Subclasses must:
      - Declare a unique `name` property (used as architect_name in DB).
      - Declare `product_types` listing which product categories this
        architect is active for (empty list = applies to all).
      - Implement `compute()` to evaluate a single cluster/agent profile.
      - Implement `generate_report()` to aggregate cluster outputs into
        a DomainReport.

    Subclasses may optionally:
      - Override `transition_overrides()` to return Markov state-transition
        delta weights keyed by (from_state, to_state) pairs.
    """

    ALL_PRODUCT_TYPES: list[str] = [
        "saas", "marketplace", "mobile_app",
        "developer_tool", "enterprise_software",
        "consumer_hardware", "health_hardware",
        "iot_hardware", "wearable", "b2b_hardware",
    ]

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique string identifier, e.g. 'PricingArchitect'."""
        ...

    @property
    @abstractmethod
    def product_types(self) -> list[str]:
        """
        List of product type strings this architect activates for.
        Return an empty list to activate for all product types.
        Example: ['saas', 'marketplace']
        """
        ...

    @abstractmethod
    def compute(
        self,
        cluster:       "ClusterDefinition",
        agent_profile: dict[str, Any],
        assumptions:   list[dict[str, Any]],
        env_params:    dict[str, Any],
    ) -> ArchitectOutput:
        """
        Evaluate this architect's domain for a single cluster.

        Args:
            cluster:       The ClusterDefinition being evaluated.
            agent_profile: Sampled trait dict for one representative agent
                           in this cluster (income_level, digital_literacy, etc.).
            assumptions:   List of assumption dicts extracted from the project
                           description, already scored by scored_assumption.py.
                           Each dict: {id, text, category, impact_score,
                           claim_confidence, specificity_score, adjusted_score}.
            env_params:    Environment parameters (consumer_volume,
                           average_order_value, price_sensitivity, etc.).

        Returns:
            ArchitectOutput with metrics, flags, narrative_findings, severity.
        """
        ...

    @abstractmethod
    def generate_report(
        self,
        outputs: list[ArchitectOutput],
    ) -> DomainReport:
        """
        Aggregate per-cluster ArchitectOutputs into one DomainReport.

        Called by the Conductor after compute() has run for all clusters.
        Should identify the highest-severity pattern across clusters and
        return actionable recommendations.

        Args:
            outputs: All ArchitectOutputs produced by this architect
                     across all clusters in this simulation run.

        Returns:
            DomainReport summarising cross-cluster findings.
        """
        ...

    def transition_overrides(
        self,
        output: ArchitectOutput,
    ) -> dict[tuple[str, str], float]:
        """
        Optional: return Markov state-transition weight deltas.

        Keys are (from_state, to_state) pairs matching MarkovState values
        (e.g. ('aware', 'browse'), ('browse', 'dropped')).
        Values are additive deltas applied to the base transition matrix
        for the cluster associated with this output.

        Default returns an empty dict (no overrides).
        """
        return {}

    def _apply_correction(
        self,
        metrics: dict[str, float],
        cluster_id: str,
        product_type: str,
        db=None,
    ) -> dict[str, float]:
        """
        Applies architect_corrections from DB if correction
        exists and confidence_weight >= 0.20.
        No-op if db is None (pure function path preserved).
        """
        if db is None:
            return metrics
        try:
            row = db.execute(
                text("""
                    SELECT correction_scalar, confidence_weight
                    FROM architect_corrections
                    WHERE architect_name = :an
                      AND product_type   = :pt
                      AND cluster_id IN (:cid, 'ALL')
                      AND confidence_weight >= 0.20
                    ORDER BY confidence_weight DESC LIMIT 1
                """),
                {"an": self.name, "pt": product_type, "cid": cluster_id},
            ).fetchone()
            if row:
                for k in metrics:
                    if isinstance(metrics[k], float):
                        metrics[k] = max(0.0, min(1.0, metrics[k] * float(row.correction_scalar)))
        except Exception as _exc:
            logger.debug(
                "%s suppressed: %s",
                __name__,
                _exc,
            )
        return metrics
