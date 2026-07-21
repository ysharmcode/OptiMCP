"""Shared types and helpers for engine adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from optimcp.spec import DecisionSpec

Assignment = Dict[str, int]


@dataclass
class EngineOutcome:
    """A single engine's result, normalized so the orchestrator can compare them.

    ``assignment`` is the raw answer the engine proposed (or ``None``). It is NOT
    trusted yet - the orchestrator independently verifies it before use.
    """

    assignment: Optional[Assignment] = None
    proven_optimal: bool = False
    proven_infeasible: bool = False
    available: bool = True
    detail: str = ""


def var_bounds(spec: DecisionSpec) -> Dict[str, tuple[int, int]]:
    """Integer (lower, upper) bounds for every variable (binary -> (0, 1))."""
    bounds: Dict[str, tuple[int, int]] = {}
    for var in spec.variables:
        if var.kind == "binary":
            bounds[var.name] = (0, 1)
        else:
            bounds[var.name] = (int(var.lb), int(var.ub))
    return bounds


def _iter_numbers(spec: DecisionSpec) -> Iterable[float]:
    for term in spec.objective.terms:
        yield term.coeff
    for constraint in spec.constraints:
        yield constraint.rhs
        for term in constraint.terms:
            yield term.coeff


def integer_scale(spec: DecisionSpec, *, cap: int = 1_000_000) -> int:
    """Smallest power-of-ten that turns every coefficient/rhs into an integer.

    CP-SAT only accepts integer coefficients. Multiplying an entire spec by a
    single positive constant preserves the feasible region and the argmax/argmin,
    so we scale, solve, and read back the (unscaled) variable assignment.
    """
    values = [float(v) for v in _iter_numbers(spec)]
    scale = 1
    while scale <= cap:
        if all(abs(v * scale - round(v * scale)) <= 1e-9 for v in values):
            return scale
        scale *= 10
    return cap
