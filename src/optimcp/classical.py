"""Classical reliability backbone.

When the (quantum) engine does not return a verified feasible answer, OptiMCP
falls back to a classical solver so the agent still gets a correct answer
whenever one exists. For small problems this is exact enumeration (and can also
*prove* infeasibility); for larger problems it is a simple randomized local
search that returns the best feasible answer it finds.

This module depends only on the raw :class:`DecisionSpec` and the independent
verifier - never on the quantum path - so it is a genuinely separate solver.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from optimcp.spec import DecisionSpec
from optimcp.verify import _eval_terms, verify_assignment

# Max joint states to enumerate exhaustively (keeps exact search sub-second).
MAX_EXACT_STATES = 2_000_000
_MAX_EXACT_STATES = MAX_EXACT_STATES  # backwards-compatible alias
# Iterations for the heuristic fallback on larger problems.
_HEURISTIC_ITERS = 20_000


@dataclass
class ClassicalResult:
    assignment: Optional[Dict[str, int]]
    method: str
    exhaustive: bool
    states_considered: int = 0
    notes: str = ""


def _domains(spec: DecisionSpec) -> List[Tuple[str, List[int]]]:
    domains: List[Tuple[str, List[int]]] = []
    for var in spec.variables:
        if var.kind == "binary":
            domains.append((var.name, [0, 1]))
        else:
            domains.append((var.name, list(range(int(var.lb), int(var.ub) + 1))))
    return domains


def _state_count(domains: List[Tuple[str, List[int]]]) -> int:
    total = 1
    for _, values in domains:
        total *= len(values)
        if total > _MAX_EXACT_STATES:
            return total
    return total


def _better(candidate: float, best: Optional[float], sense: str) -> bool:
    if best is None:
        return True
    return candidate > best if sense == "maximize" else candidate < best


def _feasible(spec: DecisionSpec, assignment: Dict[str, int]) -> bool:
    return verify_assignment(spec, assignment).all_satisfied


def _exact(spec: DecisionSpec, domains: List[Tuple[str, List[int]]]) -> ClassicalResult:
    names = [n for n, _ in domains]
    value_lists = [v for _, v in domains]
    sense = spec.objective.sense
    best_assignment: Optional[Dict[str, int]] = None
    best_value: Optional[float] = None
    considered = 0
    for combo in itertools.product(*value_lists):
        considered += 1
        assignment = {name: int(val) for name, val in zip(names, combo)}
        if not _feasible(spec, assignment):
            continue
        value = _eval_terms(spec.objective.terms, assignment)
        if _better(value, best_value, sense):
            best_value = value
            best_assignment = assignment
    return ClassicalResult(
        assignment=best_assignment,
        method="exact_enumeration",
        exhaustive=True,
        states_considered=considered,
        notes="proved infeasible" if best_assignment is None else "exact optimum over feasible set",
    )


def _heuristic(spec: DecisionSpec, domains: List[Tuple[str, List[int]]]) -> ClassicalResult:
    rng = random.Random(20260721)
    names = [n for n, _ in domains]
    value_lists = {n: v for n, v in domains}
    sense = spec.objective.sense
    best_assignment: Optional[Dict[str, int]] = None
    best_value: Optional[float] = None

    def random_assignment() -> Dict[str, int]:
        return {n: rng.choice(value_lists[n]) for n in names}

    current = random_assignment()
    for step in range(_HEURISTIC_ITERS):
        if step and step % 200 == 0:
            current = random_assignment()  # restart to escape local minima
        # single-variable random move
        candidate = dict(current)
        pick = rng.choice(names)
        candidate[pick] = rng.choice(value_lists[pick])
        if _feasible(spec, candidate):
            value = _eval_terms(spec.objective.terms, candidate)
            if _better(value, best_value, sense):
                best_value = value
                best_assignment = candidate
            current = candidate
    return ClassicalResult(
        assignment=best_assignment,
        method="heuristic_local_search",
        exhaustive=False,
        states_considered=_HEURISTIC_ITERS,
        notes="best feasible answer found (not proven optimal)",
    )


def classical_solve(spec: DecisionSpec) -> ClassicalResult:
    """Exact when small enough (can prove infeasibility), heuristic otherwise."""
    domains = _domains(spec)
    if _state_count(domains) <= _MAX_EXACT_STATES:
        return _exact(spec, domains)
    return _heuristic(spec, domains)
