"""Shared cache-namespace constants for API v1 route modules.

Constants used from more than one route module live here instead of inside
one of the routers, so modules like ``projects`` and ``users`` can share them
without introducing circular imports.
"""
from __future__ import annotations

# Confidence explainer - "why is my confidence X?" tile.
# 60s TTL: 4 cheap queries in the route, but the
# dashboard's project-detail page refreshes often.
_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE: str = "project-confidence-explainer"

__all__ = ["_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE"]
