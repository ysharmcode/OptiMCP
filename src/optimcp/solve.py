"""Solve orchestrator: engine + classical, independently verified, best wins.

Flow:
  1. Build the problem and run the QBridge engine (QOKit by default; entirely
     invisible to the caller).
  2. Also run the classical solver - exact enumeration when the problem is small
     enough (which yields the true optimum and can prove infeasibility), a
     heuristic otherwise.
  3. Independently verify every candidate against the raw spec and return the
     **best feasible one by objective value**. On small problems this guarantees
     the exact optimum rather than whatever feasible sample the engine produced;
     on large problems it returns the best verified answer found.
  4. ``status == 'solved'`` always means "independently verified to satisfy every
     constraint" - never an unchecked answer. Optimality is guaranteed only on
     the exact tier (see ``capabilities()``).
"""

from __future__ import annotations

import contextlib
import sys
import time
from typing import Any, Dict, Optional

from optimcp.builder import build_problem
from optimcp.classical import classical_solve
from optimcp.result import DecisionResult, VerificationCertificate
from optimcp.spec import DecisionSpec
from optimcp.verify import verify_assignment

# Engine kwargs we allow callers/tools to forward; everything else is ignored so
# the tool surface stays small and quantum-free.
_ENGINE_KWARGS = {"p", "alpha", "maxiter", "shots", "n_seeds", "presolve", "mixer"}


def _coerce_assignment(
    spec: DecisionSpec, raw: Dict[str, Any]
) -> Optional[Dict[str, int]]:
    assignment: Dict[str, int] = {}
    for name in spec.variable_names():
        if name not in raw:
            return None
        value = raw[name]
        try:
            assignment[name] = int(round(float(value)))
        except (TypeError, ValueError):
            return None
    return assignment


def _try_engine(
    spec: DecisionSpec, engine_kwargs: Dict[str, Any]
) -> tuple[Optional[Dict[str, int]], Optional[str]]:
    """Run the engine; return (assignment, error). Never raises."""
    try:
        problem, _ = build_problem(spec)
        # The engine prints solver progress to stdout; on an MCP stdio server
        # that would corrupt the JSON-RPC stream, so route it to stderr.
        with contextlib.redirect_stdout(sys.stderr):
            result = problem.solve(**engine_kwargs)
        assignment = _coerce_assignment(spec, dict(result.assignment))
        return assignment, None
    except Exception as exc:  # noqa: BLE001 - engine failure must fall back, not crash
        return None, f"{type(exc).__name__}: {exc}"


def solve_decision(
    spec: DecisionSpec,
    *,
    include_diagnostics: bool = False,
    _force_engine_failure: bool = False,
    **engine_kwargs: Any,
) -> DecisionResult:
    """Return a verified, constraint-satisfying answer for ``spec`` if one exists.

    ``include_diagnostics=True`` attaches an internal ``diagnostics`` block
    (which engine produced the answer, timings). It is off by default so the
    response carries no quantum vocabulary.
    """
    started = time.perf_counter()
    filtered = {k: v for k, v in engine_kwargs.items() if k in _ENGINE_KWARGS}

    engine_error: Optional[str] = None
    # Each candidate: (assignment, objective_value, source, certificate)
    candidates: list[tuple[Dict[str, int], float, str, VerificationCertificate]] = []

    def consider(candidate: Optional[Dict[str, int]], source: str) -> None:
        if candidate is None:
            return
        cert = verify_assignment(spec, candidate)
        if cert.all_satisfied:
            candidates.append((candidate, cert.objective_value, source, cert))

    # 1) Engine attempt (quantum, invisible) - skippable for fallback testing.
    if not _force_engine_failure:
        engine_assignment, engine_error = _try_engine(spec, filtered)
        consider(engine_assignment, "qbridge")
    else:
        engine_error = "engine skipped (forced fallback)"

    # 2) Classical solver - exact (optimal, can prove infeasibility) when small,
    #    heuristic otherwise. Always run so small problems return the true optimum
    #    instead of just any feasible engine sample.
    classical = classical_solve(spec)
    classical_notes = classical.notes
    consider(classical.assignment, classical.method)
    proven_infeasible = classical.assignment is None and classical.exhaustive

    # 3) Pick the best verified candidate by objective sense.
    assignment: Optional[Dict[str, int]] = None
    certificate: Optional[VerificationCertificate] = None
    engine_used = "none"
    if candidates:
        maximize = spec.objective.sense == "maximize"
        best = (max if maximize else min)(candidates, key=lambda c: c[1])
        assignment, _obj, engine_used, certificate = best

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # 3) Build the response.
    if assignment is not None and certificate is not None:
        status = "solved"
        message = "Verified: the returned assignment satisfies every declared constraint."
        result = DecisionResult(
            status=status,
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
            message = "No assignment can satisfy all constraints (proven by exhaustive search)."
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
            "winning_source": engine_used,
            "sources_considered": [c[2] for c in candidates],
            "engine_error": engine_error,
            "classical_notes": classical_notes,
            "elapsed_ms": round(elapsed_ms, 2),
        }
    return result
