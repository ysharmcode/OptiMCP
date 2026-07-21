"""Optional repair path: turn broken *linear* rules into a solvable spec.

The checker's job is to *detect* which rule broke. Sometimes the caller also
wants a corrected answer. When (and only when) the rules are linear over a set
of scalar fields, we can reduce them to a :class:`DecisionSpec` and hand it to
the existing solver, which returns an independently-verified fix. Anything
outside that subset (aggregations over arrays, division, products of two fields,
percentage-of-a-variable, ...) cannot be repaired this way and returns ``None``:
we never guess.

The caller must still supply the variable domains and the objective - a bag of
consistency rules does not, by itself, say whether ``x`` is a 0/1 choice or a
count in ``[0, 100]``, nor what to optimize. Inventing those would be exactly
the kind of silent assumption this project refuses to make.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from optimcp.check.rules import Expr, Rule, Ruleset
from optimcp.result import DecisionResult
from optimcp.solve import solve_decision
from optimcp.spec import ConstraintSpec, DecisionSpec, ObjectiveSpec, Term, VariableSpec


class NotLinear(Exception):
    """Raised when an expression is not a linear combination of scalar refs."""


# A linear form is (coefficients-by-variable, constant term).
LinForm = Tuple[Dict[str, Decimal], Decimal]


def _linearize(expr: Expr) -> LinForm:
    """Reduce ``expr`` to ``(coeffs, const)`` or raise :class:`NotLinear`."""
    if expr.kind == "lit":
        return {}, Decimal(str(expr.value))
    if expr.kind == "ref":
        if "[" in (expr.path or ""):
            raise NotLinear("indexed/array refs are not supported for repair")
        return {expr.path: Decimal(1)}, Decimal(0)  # type: ignore[dict-item]
    if expr.kind == "agg":
        raise NotLinear("aggregations cannot be linearized")

    fn = expr.fn
    if fn == "add":
        coeffs: Dict[str, Decimal] = {}
        const = Decimal(0)
        for a in expr.args:
            c, k = _linearize(a)
            for v, w in c.items():
                coeffs[v] = coeffs.get(v, Decimal(0)) + w
            const += k
        return coeffs, const
    if fn == "sub":
        c0, k0 = _linearize(expr.args[0])
        c1, k1 = _linearize(expr.args[1])
        out = dict(c0)
        for v, w in c1.items():
            out[v] = out.get(v, Decimal(0)) - w
        return out, k0 - k1
    if fn == "neg":
        c, k = _linearize(expr.args[0])
        return {v: -w for v, w in c.items()}, -k
    if fn == "mul":
        # linear only if at most one factor is non-constant
        var_forms: List[LinForm] = []
        scale = Decimal(1)
        for a in expr.args:
            c, k = _linearize(a)
            if c:
                var_forms.append((c, k))
            else:
                scale *= k
        if len(var_forms) > 1:
            raise NotLinear("product of two variable expressions is non-linear")
        if not var_forms:
            return {}, scale
        c, k = var_forms[0]
        return {v: w * scale for v, w in c.items()}, k * scale
    if fn == "div":
        c1, k1 = _linearize(expr.args[1])
        if c1:
            raise NotLinear("division by a variable is non-linear")
        if k1 == 0:
            raise NotLinear("division by zero")
        c0, k0 = _linearize(expr.args[0])
        return {v: w / k1 for v, w in c0.items()}, k0 / k1
    raise NotLinear(f"calc {fn!r} is not linear")


def rule_to_constraint(rule: Rule) -> Optional[ConstraintSpec]:
    """Convert a linear rule to a ``ConstraintSpec`` (or None if non-linear)."""
    try:
        cl, kl = _linearize(rule.lhs)
        cr, kr = _linearize(rule.rhs)
    except NotLinear:
        return None
    # Move everything to the left: (lhs - rhs) <op> 0  ->  terms <op> (kr - kl)
    coeffs: Dict[str, Decimal] = dict(cl)
    for v, w in cr.items():
        coeffs[v] = coeffs.get(v, Decimal(0)) - w
    terms = [
        Term(vars=[v], coeff=float(w)) for v, w in coeffs.items() if w != 0
    ]
    if not terms:
        return None
    return ConstraintSpec(
        terms=terms, op=rule.op, rhs=float(kr - kl), name=rule.id
    )


def build_repair_spec(
    ruleset: Ruleset,
    *,
    variables: List[Dict[str, Any]],
    objective: Dict[str, Any],
) -> Optional[DecisionSpec]:
    """Assemble a ``DecisionSpec`` from linear rules + caller-supplied domains.

    Returns ``None`` if any rule falls outside the linear-scalar subset.
    """
    constraints = []
    for rule in ruleset.rules:
        c = rule_to_constraint(rule)
        if c is None:
            return None
        constraints.append(c)
    try:
        return DecisionSpec(
            variables=[VariableSpec.model_validate(v) for v in variables],
            objective=ObjectiveSpec.model_validate(objective),
            constraints=constraints,
        )
    except Exception:
        return None


def try_repair(
    ruleset: Ruleset,
    *,
    variables: List[Dict[str, Any]],
    objective: Dict[str, Any],
) -> Optional[DecisionResult]:
    """Best-effort corrected answer for a broken *linear* ruleset.

    Returns a verified :class:`DecisionResult`, or ``None`` when the rules are
    not linear-over-scalars (in which case: report the violation, do not guess).
    """
    spec = build_repair_spec(ruleset, variables=variables, objective=objective)
    if spec is None:
        return None
    return solve_decision(spec)
