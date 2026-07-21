"""Independent constraint verification.

Deliberately computed here straight from the raw :class:`DecisionSpec`, with no
dependency on any solver's internals, so the "this answer satisfies your
constraints" certificate comes from a second, independent code path from the one
that produced the answer. That independence is the whole point: it is what an
LLM's own reasoning cannot provide.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from optimcp.result import ConstraintCheck, VerificationCertificate
from optimcp.spec import ConstraintSpec, DecisionSpec, Op, Term

# Tolerance for floating-point comparisons (coeffs/rhs may be non-integer).
_EPS = 1e-6

AssignmentValue = float


def _missing_terms(terms: Sequence[Term], assignment: Dict[str, float]) -> set:
    """Variable names referenced by ``terms`` that are absent from ``assignment``."""
    missing = set()
    for term in terms:
        for var_name in term.vars:
            if var_name not in assignment:
                missing.add(var_name)
    return missing


def _eval_terms(terms: Sequence[Term], assignment: Dict[str, float]) -> float:
    total = 0.0
    for term in terms:
        product = 1.0
        for var_name in term.vars:
            product *= float(assignment[var_name])
        total += term.coeff * product
    return total


def _compare(lhs: float, op: Op, rhs: float) -> bool:
    if op == "<=":
        return lhs <= rhs + _EPS
    if op == ">=":
        return lhs >= rhs - _EPS
    if op == "==":
        return abs(lhs - rhs) <= _EPS
    if op == "!=":
        return abs(lhs - rhs) > _EPS
    if op == "<":
        return lhs < rhs - _EPS
    if op == ">":
        return lhs > rhs + _EPS
    raise ValueError(f"unknown operator: {op!r}")


def _constraint_label(constraint: ConstraintSpec, index: int) -> str:
    return constraint.name or f"constraint[{index}]"


def _check_domains(spec: DecisionSpec, assignment: Dict[str, float]) -> List[str]:
    issues: List[str] = []
    known = {var.name for var in spec.variables}
    # Unknown keys are almost always a spelling/casing mistake by the caller;
    # surface them instead of silently ignoring (a silent ignore is how a tool
    # like this "lies" - it would look satisfied while the caller meant a
    # different variable).
    for key in assignment:
        if key not in known:
            issues.append(
                f"unknown variable {key!r} in assignment (check spelling/casing)"
            )
    for var in spec.variables:
        if var.name not in assignment:
            issues.append(f"missing value for variable {var.name!r}")
            continue
        value = assignment[var.name]
        if float(value) != int(value):
            issues.append(f"variable {var.name!r} must be integral, got {value}")
            continue
        ivalue = int(value)
        if var.kind == "binary":
            if ivalue not in (0, 1):
                issues.append(f"binary variable {var.name!r} must be 0 or 1, got {ivalue}")
        else:  # integer
            if var.lb is not None and ivalue < var.lb:
                issues.append(f"variable {var.name!r} = {ivalue} below lb {var.lb}")
            if var.ub is not None and ivalue > var.ub:
                issues.append(f"variable {var.name!r} = {ivalue} above ub {var.ub}")
    return issues


def verify_assignment(
    spec: DecisionSpec, assignment: Dict[str, float]
) -> VerificationCertificate:
    """Independently check ``assignment`` against every domain and constraint."""
    domain_issues = _check_domains(spec, assignment)
    domain_valid = not domain_issues

    checks: List[ConstraintCheck] = []
    all_constraints_ok = True
    for index, constraint in enumerate(spec.constraints):
        label = _constraint_label(constraint, index)
        missing_here = _missing_terms(constraint.terms, assignment)
        if missing_here:
            # A constraint we cannot even evaluate is treated as NOT satisfied,
            # never as an exception - the tool must always return a verdict.
            all_constraints_ok = False
            checks.append(
                ConstraintCheck(
                    name=constraint.name,
                    satisfied=False,
                    detail=(
                        f"{label}: cannot evaluate - missing value(s) for "
                        f"{sorted(missing_here)}"
                    ),
                )
            )
            continue
        lhs = _eval_terms(constraint.terms, assignment)
        satisfied = _compare(lhs, constraint.op, constraint.rhs)
        all_constraints_ok = all_constraints_ok and satisfied
        status = "satisfied" if satisfied else "VIOLATED"
        checks.append(
            ConstraintCheck(
                name=constraint.name,
                satisfied=satisfied,
                detail=f"{label}: {lhs:g} {constraint.op} {constraint.rhs:g}: {status}",
            )
        )

    if _missing_terms(spec.objective.terms, assignment):
        objective_value = float("nan")
    else:
        objective_value = _eval_terms(spec.objective.terms, assignment)

    return VerificationCertificate(
        all_satisfied=bool(domain_valid and all_constraints_ok),
        objective_value=objective_value,
        constraint_checks=checks,
        domain_valid=domain_valid,
        issues=domain_issues,
    )
