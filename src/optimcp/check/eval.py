"""Deterministic evaluation of rules against a document.

All arithmetic runs in :class:`decimal.Decimal` so money, tax and percentage
chains do not pick up binary-float drift (a report that says "off by
0.00000001" would be worse than useless). String values are normalized (commas,
currency symbols, accounting parentheses, ``k``/``m``/``b`` suffixes, trailing
``%``) and every non-trivial coercion is recorded, because a silently-"fixed"
unit is precisely the transcription bug this tool exists to surface.
"""

from __future__ import annotations

import re
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
from typing import Any, List, Tuple

from optimcp.check.paths import PathError, resolve_all, resolve_ref
from optimcp.check.result import ConsistencyReport, RuleCheck
from optimcp.check.rules import Expr, Rule, Ruleset

getcontext().prec = 50

_SUFFIX = {"k": Decimal(10) ** 3, "m": Decimal(10) ** 6, "b": Decimal(10) ** 9,
           "bn": Decimal(10) ** 9, "t": Decimal(10) ** 12}
_STRIP = re.compile(r"[,\s_$£€¥]")


class EvalError(Exception):
    """A rule could not be evaluated. Carries the offending paths (if any)."""

    def __init__(self, message: str, missing: List[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.missing = missing or []


class _Ctx:
    """Mutable accumulator threaded through one rule's evaluation."""

    def __init__(self) -> None:
        self.notes: List[str] = []


def _coerce(raw: Any, path: str, ctx: _Ctx) -> Decimal:
    """Turn a raw JSON leaf into a Decimal, recording any real normalization."""
    if isinstance(raw, bool):
        # bool is an int subclass; a true/false where a number is expected is
        # almost always a modelling mistake, so refuse rather than read 1/0.
        raise EvalError(f"value at {path!r} is a boolean, not a number", [path])
    if isinstance(raw, (int, float, Decimal)):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            raise EvalError(f"value at {path!r} is not a finite number", [path])
    if isinstance(raw, str):
        s = raw.strip()
        original = s
        neg = False
        if s.startswith("(") and s.endswith(")"):
            neg, s = True, s[1:-1]
        s = _STRIP.sub("", s)
        percent = False
        if s.endswith("%"):
            percent, s = True, s[:-1]
        scale = Decimal(1)
        m = re.match(r"^(-?\d*\.?\d+)([a-zA-Z]+)$", s)
        if m and m.group(2).lower() in _SUFFIX:
            scale = _SUFFIX[m.group(2).lower()]
            s = m.group(1)
        try:
            val = Decimal(s) * scale
        except InvalidOperation:
            raise EvalError(f"value at {path!r} is not numeric: {raw!r}", [path])
        if neg:
            val = -val
        # note only when normalization actually changed the token
        if percent or scale != 1 or _STRIP.search(original) or (neg and "(" in raw):
            ctx.notes.append(
                f"{path}: coerced string {raw!r} -> {val} "
                "(check the intended unit)"
            )
        return val
    raise EvalError(f"value at {path!r} is not a number: {type(raw).__name__}", [path])


def _eval(expr: Expr, document: Any, ctx: _Ctx) -> Decimal:
    if expr.kind == "lit":
        return Decimal(str(expr.value))

    if expr.kind == "ref":
        try:
            raw = resolve_ref(document, expr.path)  # type: ignore[arg-type]
        except PathError as e:
            raise EvalError(str(e), [expr.path or ""])
        return _coerce(raw, expr.path or "", ctx)

    if expr.kind == "agg":
        path = expr.path or ""
        try:
            raws = resolve_all(document, path)
        except PathError as e:
            raise EvalError(str(e), [path])
        if expr.fn == "count":
            return Decimal(len(raws))
        values = [_coerce(r, path, ctx) for r in raws]
        if not values:
            raise EvalError(f"aggregation {expr.fn} over {path!r} matched no values", [path])
        if expr.fn == "sum":
            return sum(values, Decimal(0))
        if expr.fn == "avg":
            return sum(values, Decimal(0)) / Decimal(len(values))
        if expr.fn == "min":
            return min(values)
        if expr.fn == "max":
            return max(values)
        raise EvalError(f"unknown aggregation {expr.fn!r}")  # pragma: no cover

    # calc
    args = [_eval(a, document, ctx) for a in expr.args]
    fn = expr.fn
    try:
        if fn == "add":
            return sum(args, Decimal(0))
        if fn == "mul":
            out = Decimal(1)
            for a in args:
                out *= a
            return out
        if fn == "sub":
            return args[0] - args[1]
        if fn == "div":
            if args[1] == 0:
                raise EvalError("division by zero")
            return args[0] / args[1]
        if fn == "neg":
            return -args[0]
        if fn == "abs":
            return abs(args[0])
        if fn == "round":
            ndigits = int(args[1])
            quant = Decimal(1).scaleb(-ndigits)
            return args[0].quantize(quant)
        if fn == "pow":
            return args[0] ** args[1]
        if fn == "pct_change":
            old, new = args[0], args[1]
            if old == 0:
                raise EvalError("pct_change from a base of zero is undefined")
            return (new - old) / old * Decimal(100)
    except (DivisionByZero, InvalidOperation) as e:
        raise EvalError(f"arithmetic error in {fn!r}: {e}")
    raise EvalError(f"unknown calc {fn!r}")  # pragma: no cover


def _compare(lhs: Decimal, op: str, rhs: Decimal, tol: Decimal) -> bool:
    d = lhs - rhs
    if op == "==":
        return abs(d) <= tol
    if op == "!=":
        return abs(d) > tol
    if op == "<=":
        return lhs <= rhs + tol
    if op == ">=":
        return lhs >= rhs - tol
    if op == "<":
        return lhs < rhs - tol
    if op == ">":
        return lhs > rhs + tol
    raise EvalError(f"unknown operator {op!r}")  # pragma: no cover


def _fmt(d: Decimal) -> str:
    """Compact human formatting: drop trailing zeros but keep it readable."""
    d = d.normalize()
    s = format(d, "f")
    return s


def check_rule(rule: Rule, document: Any) -> RuleCheck:
    """Evaluate a single rule; always returns a verdict, never raises."""
    ctx = _Ctx()
    try:
        lhs = _eval(rule.lhs, document, ctx)
        rhs = _eval(rule.rhs, document, ctx)
    except EvalError as e:
        return RuleCheck(
            id=rule.id,
            passed=False,
            op=rule.op,
            detail=(f"{rule.id}: could not evaluate - {e.message}"
                    + (f" ({rule.message})" if rule.message else "")),
            missing=e.missing,
            notes=ctx.notes,
            error=e.message,
        )

    tol = Decimal(str(rule.abs_tol)) + Decimal(str(rule.rel_tol)) * abs(rhs)
    passed = _compare(lhs, rule.op, rhs, tol)
    delta = lhs - rhs
    status = "SATISFIED" if passed else "VIOLATED"
    detail = f"{rule.id}: {_fmt(lhs)} {rule.op} {_fmt(rhs)}: {status}"
    if not passed:
        detail += f" (off by {_fmt(abs(delta))})"
    if rule.message:
        detail += f" - {rule.message}"
    return RuleCheck(
        id=rule.id,
        passed=passed,
        op=rule.op,
        lhs_value=float(lhs),
        rhs_value=float(rhs),
        delta=float(delta),
        tolerance=float(tol),
        detail=detail,
        notes=ctx.notes,
    )


def _summary(checks: List[RuleCheck], broken: List[str], unevaluable: List[str]) -> str:
    n = len(checks)
    if not broken and not unevaluable:
        return f"All {n} rule(s) consistent."
    parts: List[str] = []
    if broken:
        shown = "; ".join(c.detail for c in checks if c.id in set(broken))
        parts.append(f"{len(broken)} of {n} rule(s) VIOLATED: {shown}")
    if unevaluable:
        shown = "; ".join(
            f"{c.id} ({c.error})" for c in checks if c.id in set(unevaluable)
        )
        parts.append(f"{len(unevaluable)} of {n} rule(s) unevaluable: {shown}")
    return " | ".join(parts)


def check_document(document: Any, ruleset: Ruleset) -> ConsistencyReport:
    """Evaluate every rule against ``document`` and build the report."""
    checks = [check_rule(rule, document) for rule in ruleset.rules]
    broken = [c.id for c in checks if not c.passed and c.error is None]
    unevaluable = [c.id for c in checks if c.error is not None]
    consistent = not broken and not unevaluable
    notes: List[str] = []
    for c in checks:
        for note in c.notes:
            if note not in notes:
                notes.append(note)
    return ConsistencyReport(
        consistent=consistent,
        checks=checks,
        broken_rules=broken,
        unevaluable=unevaluable,
        summary=_summary(checks, broken, unevaluable),
        notes=notes,
    )
