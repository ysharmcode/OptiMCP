"""Deterministic translation of a :class:`DecisionSpec` into a QBridge problem.

Pure and mechanical: no heuristics, no LLM. The same spec always produces the
same ``OptimizationProblem``.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import qbridge as qb

from optimcp.spec import DecisionSpec, Op, Term


def _term_expression(term: Term, variables: Dict[str, object]):
    product = None
    for var_name in term.vars:
        var = variables[var_name]
        product = var if product is None else product * var
    return term.coeff * product


def _sum_terms(terms: Sequence[Term], variables: Dict[str, object]):
    total = None
    for term in terms:
        expr = _term_expression(term, variables)
        total = expr if total is None else total + expr
    return total


def _as_constraint(lhs, op: Op, rhs: float):
    if op == "<=":
        return lhs <= rhs
    if op == ">=":
        return lhs >= rhs
    if op == "==":
        return lhs == rhs
    if op == "!=":
        return lhs != rhs
    if op == "<":
        return lhs < rhs
    if op == ">":
        return lhs > rhs
    raise ValueError(f"unknown operator: {op!r}")


def build_problem(spec: DecisionSpec) -> Tuple[qb.OptimizationProblem, Dict[str, object]]:
    """Build a QBridge ``OptimizationProblem`` and the name->variable map."""
    variables: Dict[str, object] = {}
    for var in spec.variables:
        if var.kind == "binary":
            variables[var.name] = qb.Binary(var.name)
        else:  # integer (bounds validated in the spec)
            variables[var.name] = qb.Integer(var.name, lb=int(var.lb), ub=int(var.ub))

    problem = qb.OptimizationProblem()

    objective = _sum_terms(spec.objective.terms, variables)
    if objective is None:
        # No objective terms => "find any feasible answer". Use a trivial 0*x
        # objective so the container has a well-formed expression.
        first = next(iter(variables.values()))
        objective = 0 * first

    if spec.objective.sense == "maximize":
        problem.maximize(objective)
    else:
        problem.minimize(objective)

    for constraint in spec.constraints:
        lhs = _sum_terms(constraint.terms, variables)
        problem.add_constraint(_as_constraint(lhs, constraint.op, constraint.rhs))

    return problem, variables
