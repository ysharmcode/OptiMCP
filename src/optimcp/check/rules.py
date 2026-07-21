"""The declarative rule language for the consistency checker.

A *rule* asserts a numeric/logical relationship between two expressions computed
from a JSON document, e.g. ``sum(line_items[*].amount) == invoice.total`` or
``pct_change(prev_revenue, revenue) == stated_growth``. Rules are pure data:
there is no natural-language parsing and no LLM anywhere in this package, which
is exactly what lets the "provably tells you which rule broke" guarantee hold -
the mapping from (document, rules) to a verdict is deterministic.

An :class:`Expr` is a tiny JSON AST with four node kinds:

* ``lit``  - a literal number (``value``).
* ``ref``  - a single field, by path (``path``), e.g. ``"invoice.total"`` or
  ``"line_items[0].amount"``. No wildcards.
* ``agg``  - an aggregation (``fn`` in :data:`AGG_FNS`) over a wildcard path
  (``path`` containing ``[*]``), e.g. ``sum`` of ``"line_items[*].amount"``.
* ``calc`` - arithmetic (``fn`` in :data:`CALC_FNS`) over sub-expressions
  (``args``), e.g. ``sub(total, subtotal)`` or ``pct_change(old, new)``.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from optimcp.spec import Op

# ---- vocabulary ------------------------------------------------------------

ExprKind = Literal["lit", "ref", "agg", "calc"]

#: Aggregations over a wildcard (``[*]``) path.
AGG_FNS = frozenset({"sum", "avg", "min", "max", "count"})

#: Arithmetic combinators over sub-expressions, with their fixed arities.
#: ``None`` means variadic (>= 1 argument).
CALC_ARITY = {
    "add": None,   # a + b + ...
    "sub": 2,      # a - b
    "mul": None,   # a * b * ...
    "div": 2,      # a / b
    "neg": 1,      # -a
    "abs": 1,      # |a|
    "round": 2,    # round(a, ndigits)  (ndigits must be a literal)
    "pow": 2,      # a ** b
    "pct_change": 2,  # (new - old) / old * 100, called as pct_change(old, new)
}
CALC_FNS = frozenset(CALC_ARITY)

# Guard rails: keep rulesets and expressions in a sane range.
MAX_RULES = 500
MAX_EXPR_NODES = 200


class Expr(BaseModel):
    """A single node of the expression AST (see module docstring)."""

    kind: ExprKind
    value: Optional[float] = Field(None, description="Literal number (kind='lit').")
    path: Optional[str] = Field(
        None,
        description=(
            "Field path (kind='ref', no wildcard) or wildcard path "
            "(kind='agg', must contain '[*]'). Supports '.', '[i]', '[*]'."
        ),
    )
    fn: Optional[str] = Field(
        None,
        description="Aggregation (kind='agg') or arithmetic op (kind='calc').",
    )
    args: List["Expr"] = Field(
        default_factory=list,
        description="Operand sub-expressions (kind='calc').",
    )

    @model_validator(mode="after")
    def _validate(self) -> "Expr":
        if self.kind == "lit":
            if self.value is None:
                raise ValueError("lit expression requires 'value'")
        elif self.kind == "ref":
            if not self.path:
                raise ValueError("ref expression requires 'path'")
            if "[*]" in self.path:
                raise ValueError(
                    "ref path may not contain a wildcard '[*]'; use kind='agg'"
                )
        elif self.kind == "agg":
            if self.fn not in AGG_FNS:
                raise ValueError(f"agg fn must be one of {sorted(AGG_FNS)}")
            if not self.path:
                raise ValueError("agg expression requires a wildcard 'path'")
            if "[*]" not in self.path:
                raise ValueError("agg path must contain a wildcard '[*]'")
        elif self.kind == "calc":
            if self.fn not in CALC_FNS:
                raise ValueError(f"calc fn must be one of {sorted(CALC_FNS)}")
            arity = CALC_ARITY[self.fn]
            if arity is None:
                if len(self.args) < 1:
                    raise ValueError(f"calc '{self.fn}' needs at least 1 argument")
            elif len(self.args) != arity:
                raise ValueError(
                    f"calc '{self.fn}' needs exactly {arity} arguments, "
                    f"got {len(self.args)}"
                )
            if self.fn == "round" and self.args[1].kind != "lit":
                raise ValueError("round's second argument (ndigits) must be a literal")
        if self._node_count() > MAX_EXPR_NODES:
            raise ValueError(f"expression too large (> {MAX_EXPR_NODES} nodes)")
        return self

    def _node_count(self) -> int:
        return 1 + sum(a._node_count() for a in self.args)


class Rule(BaseModel):
    """One assertion: ``lhs <op> rhs`` (within tolerance)."""

    id: str = Field(..., description="Stable label, echoed back in the report.")
    lhs: Expr
    op: Op = Field(..., description="Comparison operator.")
    rhs: Expr
    abs_tol: float = Field(
        1e-6, ge=0.0, description="Absolute tolerance for the comparison."
    )
    rel_tol: float = Field(
        0.0,
        ge=0.0,
        description="Relative tolerance (fraction of |rhs|) added to abs_tol.",
    )
    message: Optional[str] = Field(
        None, description="Optional human phrasing, echoed on violation."
    )

    @model_validator(mode="after")
    def _validate(self) -> "Rule":
        if not self.id or not self.id.strip():
            raise ValueError("rule id must be a non-empty string")
        return self


class Ruleset(BaseModel):
    """A bag of rules to evaluate against one document."""

    rules: List[Rule] = Field(..., min_length=1, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _validate(self) -> "Ruleset":
        seen = set()
        for r in self.rules:
            if r.id in seen:
                raise ValueError(f"duplicate rule id: {r.id!r}")
            seen.add(r.id)
        return self


Expr.model_rebuild()
