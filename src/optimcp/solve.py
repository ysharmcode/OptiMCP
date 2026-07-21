"""Solve orchestrator: two independent engines, independently verified, best wins.

OptiMCP implements no solver of its own. It runs two mature open-source engines
and trusts neither blindly:

  1. **CP-SAT** (OR-Tools) - an exact constraint/integer solver that proves both
     optimality and infeasibility.
  2. **Simulated annealing** (dwave-samplers over a dimod QUBO) - a
     quantum-inspired heuristic sampler; a genuinely different method.

Every assignment either engine proposes is independently re-checked against the
raw spec by :func:`optimcp.verify.verify_assignment` (this repository's actual
engineering focus). Only *verified-feasible* candidates compete, and the best one
by objective value is returned.

  * ``status == 'solved'`` always means "independently verified to satisfy every
    constraint" - never an unchecked answer.
  * ``status == 'infeasible'`` is returned only when CP-SAT *proves* no assignment
    can satisfy the constraints.
  * Optimality is guaranteed when CP-SAT reports it (see ``capabilities()``).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from optimcp.engines.annealer import solve_annealer
from optimcp.engines.cpsat import solve_cpsat
from optimcp.result import DecisionResult, VerificationCertificate
from optimcp.spec import DecisionSpec
from optimcp.verify import verify_assignment

# Ordered so the exact engine is tried first; ties in objective keep its answer.
_ENGINES = (
    ("cp-sat", solve_cpsat),
    ("simulated-annealing", solve_annealer),
)


def solve_decision(
    spec: DecisionSpec,
    *,
    include_diagnostics: bool = False,
    _engines: Optional[Tuple[str, ...]] = None,
    **_ignored: object,
) -> DecisionResult:
    """Return a verified, constraint-satisfying answer for ``spec`` if one exists.

    ``include_diagnostics=True`` attaches an internal ``diagnostics`` block (which
    engine produced the answer, per-engine candidates, timings). It is off by
    default so the response stays minimal.

    ``_engines`` restricts which engines run (used only by tests to exercise a
    single engine in isolation).
    """
    started = time.perf_counter()
    selected = [(n, fn) for n, fn in _ENGINES if _engines is None or n in _engines]

    # Each candidate: (assignment, objective_value, source, certificate)
    candidates: List[Tuple[Dict[str, int], float, str, VerificationCertificate]] = []
    engine_details: Dict[str, str] = {}
    proven_infeasible = False
    proven_optimal_sources: set[str] = set()

    for name, fn in selected:
        outcome = fn(spec)
        engine_details[name] = outcome.detail
        if outcome.proven_infeasible:
            proven_infeasible = True
        if outcome.assignment is not None:
            cert = verify_assignment(spec, outcome.assignment)
            if cert.all_satisfied:
                candidates.append((outcome.assignment, cert.objective_value, name, cert))
                if outcome.proven_optimal:
                    proven_optimal_sources.add(name)

    assignment: Optional[Dict[str, int]] = None
    certificate: Optional[VerificationCertificate] = None
    winning_source = "none"
    if candidates:
        maximize = spec.objective.sense == "maximize"
        best = (max if maximize else min)(candidates, key=lambda c: c[1])
        assignment, _obj, winning_source, certificate = best

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if assignment is not None and certificate is not None:
        proven = winning_source in proven_optimal_sources
        message = (
            "Verified: the returned assignment satisfies every declared constraint"
            + (" (and is proven optimal)." if proven else ".")
        )
        result = DecisionResult(
            status="solved",
            feasible=True,
            assignment=assignment,
            objective_value=certificate.objective_value,
            objective_sense=spec.objective.sense,
            verification=certificate,
            message=message,
        )
    else:
        if proven_infeasible:
            status = "infeasible"
            message = "No assignment can satisfy all constraints (proven by CP-SAT)."
        else:
            status = "no_feasible_found"
            message = "No feasible assignment was found within the search budget."
        result = DecisionResult(
            status=status,
            feasible=False,
            assignment={},
            objective_value=None,
            objective_sense=spec.objective.sense,
            verification=VerificationCertificate(
                all_satisfied=False,
                objective_value=float("nan"),
                constraint_checks=[],
                domain_valid=False,
                issues=[message],
            ),
            message=message,
        )

    if include_diagnostics:
        result.diagnostics = {
            "winning_source": winning_source,
            "sources_considered": [c[2] for c in candidates],
            "candidates": [{"source": c[2], "objective": c[1]} for c in candidates],
            "proven_optimal": winning_source in proven_optimal_sources,
            "proven_infeasible": proven_infeasible,
            "engine_details": engine_details,
            "elapsed_ms": round(elapsed_ms, 2),
        }
    return result
