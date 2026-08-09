"""Pure helpers for the architect-stack registry endpoint.

The conductor defines two related structures that until now were only
reachable through private module attributes:

* ``_ARCHITECTS`` — the registry of every ``BaseArchitect`` instance,
  keyed by PascalCase architect name.
* ``ARCHITECT_STACKS`` — the deterministic evaluation stack per product
  type, i.e. which architects actually run for ``saas`` vs
  ``consumer_hardware``.

This module turns those structures into an API-safe, human-readable
registry: full coverage across every product type, per-architect
activation metadata, and an optional product-type filter that shows both
the active stack (in evaluation order) and the registered architects that
are deliberately excluded for that product type.

Pure Python — no SQL, no I/O. The route layer supplies the live conductor
registry/stacks; tests can pass small fixtures instead of importing the
entire simulation engine.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping, Sequence


def _type_value(product_type: Any) -> str:
    """Normalise one product-type key (enum member or string) to a string."""
    if hasattr(product_type, "value"):
        return str(product_type.value)
    return str(product_type)


def _activation_types(architect: Any) -> list[str]:
    """Return the architect's declared product-type activation filter."""
    raw = getattr(architect, "product_types", None) or []
    return sorted({
        str(item).strip().lower()
        for item in raw
        if str(item).strip()
    })


def _normalise_product_type(
    value: str | None,
    valid_values: set[str],
) -> str | None:
    """Case/whitespace-normalise the requested product type."""
    if value is None:
        return None
    candidate = value.strip().lower()
    if candidate not in valid_values:
        raise ValueError(
            f"Unknown product_type {value!r}. Expected one of: "
            + ", ".join(sorted(valid_values))
        )
    return candidate


def build_architect_stack_registry(
    *,
    registry: Mapping[str, Any],
    stacks: Mapping[Any, Sequence[str]],
    product_type: str | None = None,
    all_product_types: Sequence[Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compose the architect-stack registry payload.

    Args:
        registry: mapping of architect name -> architect instance.
        stacks: mapping of product type -> ordered stack of architect names.
        product_type: optional filter (case-insensitive string). When set,
            the response shows every registered architect with an
            ``active_for_product_type`` flag and, for active ones, the
            stack position; when ``None``, the response is the full
            registry sorted by name.
        all_product_types: the canonical product-type ordering. Defaults to
            the stack keys in their mapping order.
        generated_at: timestamp for the payload; defaults to now (UTC).

    Returns:
        A dict matching :class:`ArchitectStackRegistryOut`.
    """
    all_types = (
        list(all_product_types)
        if all_product_types is not None
        else list(stacks)
    )
    all_values = {_type_value(pt) for pt in all_types}
    requested = _normalise_product_type(product_type, all_values)
    requested_key = next(
        (pt for pt in all_types if _type_value(pt) == requested),
        None,
    )
    requested_stack = (
        list(stacks.get(requested_key, []))
        if requested_key is not None
        else []
    )

    # Per-product coverage: how many universal / specialised architects run,
    # and how many stack entries are missing from the live registry.
    product_coverage: list[dict[str, Any]] = []
    for pt in all_types:
        pt_value = _type_value(pt)
        stack = list(stacks.get(pt, []) or [])
        universal_count = 0
        specialized_count = 0
        missing_count = 0
        for name in stack:
            architect = registry.get(name)
            if architect is None:
                missing_count += 1
                continue
            if _activation_types(architect):
                specialized_count += 1
            else:
                universal_count += 1
        product_coverage.append({
            "product_type": pt_value,
            "stack_size": len(stack),
            "universal_count": universal_count,
            "specialized_count": specialized_count,
            "missing_count": missing_count,
        })

    # Per-architect entries: activation filter, stack membership, and the
    # optional requested-product-type position.
    entries: list[dict[str, Any]] = []
    for name, architect in registry.items():
        activation = _activation_types(architect)
        universal = not activation
        stacked_types: list[str] = []
        for pt in all_types:
            pt_value = _type_value(pt)
            if name in (stacks.get(pt, []) or []):
                stacked_types.append(pt_value)
        stacked_types.sort()

        active = requested is not None and name in requested_stack
        position = (
            requested_stack.index(name) + 1
            if active
            else None
        )
        entries.append({
            "name": str(name),
            "product_types": activation,
            "universal": universal,
            "stack_count": len(stacked_types),
            "stacked_product_types": stacked_types,
            "active_for_product_type": active if requested is not None else None,
            "stack_position": position,
        })

    if requested is not None:
        entries.sort(
            key=lambda e: (
                e["stack_position"] is None,
                e["stack_position"] or 0,
                e["name"],
            )
        )
        universal_count = sum(
            1
            for e in entries
            if e["active_for_product_type"] and e["universal"]
        )
        specialized_count = len(requested_stack) - universal_count
        stack_size = len(requested_stack)
    else:
        entries.sort(key=lambda e: e["name"])
        universal_count = sum(1 for e in entries if e["universal"])
        specialized_count = len(entries) - universal_count
        stack_size = None

    return {
        "generated_at": generated_at or datetime.now(UTC),
        "product_type": requested,
        "total_architects": len(entries),
        "stack_size": stack_size,
        "universal_count": universal_count,
        "specialized_count": specialized_count,
        "architects": entries,
        "product_coverage": product_coverage,
    }


__all__ = ["build_architect_stack_registry"]
