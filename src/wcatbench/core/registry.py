"""Adapters are found through entry points: a package installed beside wcatbench adds one without a core change."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from wcatbench.core.errors import PermanentError

GROUPS = ("stores", "agents", "bindings", "datasets", "scorers")


def available(kind: str) -> dict[str, str]:
    """Adapter name to the `module:object` it loads, without importing it."""
    if kind not in GROUPS:
        raise PermanentError(f"unknown adapter kind {kind!r}; one of {', '.join(GROUPS)}")
    return {point.name: point.value for point in entry_points(group=f"wcatbench.{kind}")}


def load(kind: str, name: str) -> Any:
    points = {point.name: point for point in entry_points(group=f"wcatbench.{kind}")}
    if name not in points:
        choices = ", ".join(sorted(points)) or "none installed"
        raise PermanentError(f"no {kind[:-1]} adapter named {name!r}; installed: {choices}")
    return points[name].load()
