"""Exact engine: Google OR-Tools CP-SAT.

CP-SAT is a mature, Apache-2.0 constraint/integer solver. It handles binary and
bounded-integer variables, linear and (via an auxiliary product variable)
degree-2 quadratic terms, and every operator OptiMCP exposes. Crucially it can
PROVE both optimality and infeasibility - the two claims a heuristic can never
make on its own.

CP-SAT is integer-only, so a spec with fractional coefficients is uniformly
scaled to integers first (see :func:`integer_scale`); scaling by a positive
constant leaves the feasible region and the optimal assignment unchanged.
"""

from __future__ import annotations

from typing import Dict

from optimcp.engines.common import EngineOutcome, integer_scale, var_bounds
from optimcp.spec import DecisionSpec, Term


def solve_cpsat(spec: DecisionSpec, *, max_time_s: float = 5.0) -> EngineOutcome:
    """Solve ``spec`` exactly with CP-SAT. Never raises."""
    try:
        from ortools.sat.python import cp_model
    except Exception as exc:  # pragma: no cover - only when ortools missing
        return EngineOutcome(available=False, detail=f"ortools unavailable: {exc}")
    try:
        return _solve(spec, cp_model, max_time_s)
    except Exception as exc:  # pragma: no cover - defensive
        return EngineOutcome(available=False, detail=f"cp-sat error: {type(exc).__name__}: {exc}")


def _solve(spec: DecisionSpec, cp_model, max_time_s: float) -> EngineOutcome:
    model = cp_model.CpModel()
    bounds = var_bounds(spec)
    scale = integer_scale(spec)

    dvars: Dict[str, object] = {}
    for var in spec.variables:
        lo, hi = bounds[var.name]
        dvars[var.name] = model.NewIntVar(lo, hi, var.name)

    product_cache: Dict[tuple, object] = {}

    def term_var(term: Term):
        if len(term.vars) == 1:
            return dvars[term.vars[0]]
        key = tuple(sorted(term.vars))
        if key in product_cache:
            return product_cache[key]
        (alo, ahi) = bounds[key[0]]
        (blo, bhi) = bounds[key[1]]
        corners = [alo * blo, alo * bhi, ahi * blo, ahi * bhi]
        prod = model.NewIntVar(min(corners), max(corners), f"prod_{key[0]}__{key[1]}")
        model.AddMultiplicationEquality(prod, [dvars[key[0]], dvars[key[1]]])
        product_cache[key] = prod
        return prod

    def linear(terms):
        expr = 0
        for term in terms:
            coeff = int(round(term.coeff * scale))
            if coeff:
                expr = expr + coeff * term_var(term)
        return expr

    for constraint in spec.constraints:
        lhs = linear(constraint.terms)
        rhs = int(round(constraint.rhs * scale))
        op = constraint.op
        if op == "<=":
            model.Add(lhs <= rhs)
        elif op == ">=":
            model.Add(lhs >= rhs)
        elif op == "==":
            model.Add(lhs == rhs)
        elif op == "!=":
            model.Add(lhs != rhs)
        elif op == "<":
            model.Add(lhs <= rhs - 1)
        elif op == ">":
            model.Add(lhs >= rhs + 1)

    if spec.objective.terms:
        objective = linear(spec.objective.terms)
        if spec.objective.sense == "maximize":
            model.Maximize(objective)
        else:
            model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status == cp_model.INFEASIBLE:
        return EngineOutcome(proven_infeasible=True, detail="cp-sat: proved infeasible")
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignment = {var.name: int(solver.Value(dvars[var.name])) for var in spec.variables}
        return EngineOutcome(
            assignment=assignment,
            proven_optimal=(status == cp_model.OPTIMAL),
            detail=f"cp-sat: {solver.StatusName(status)}",
        )
    return EngineOutcome(detail=f"cp-sat: {solver.StatusName(status)}")
