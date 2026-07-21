"""Result models for the consistency checker.

The :class:`ConsistencyReport` is the whole product surface: for each rule it
says whether it held, and for the ones that did not, it names them and shows the
computed value against the expected value with the exact delta. A rule that
cannot even be evaluated (a missing or non-numeric field) is reported as *not
passed* - never silently skipped - because a checker that quietly ignores a rule
is a checker that lies.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RuleCheck(BaseModel):
    """Independent verdict for a single rule."""

    id: str
    passed: bool = Field(..., description="True iff the rule held (within tolerance).")
    op: str
    lhs_value: Optional[float] = Field(
        None, description="Computed left-hand side (None if unevaluable)."
    )
    rhs_value: Optional[float] = Field(
        None, description="Computed right-hand side (None if unevaluable)."
    )
    delta: Optional[float] = Field(
        None, description="lhs - rhs (None if unevaluable)."
    )
    tolerance: float = Field(0.0, description="Effective tolerance used for the comparison.")
    detail: str = Field(..., description="Human-readable one-line verdict.")
    missing: List[str] = Field(
        default_factory=list, description="Field paths that were absent/non-numeric."
    )
    notes: List[str] = Field(
        default_factory=list,
        description="String/unit coercions applied while evaluating this rule.",
    )
    error: Optional[str] = Field(
        None, description="Why the rule could not be evaluated (if any)."
    )


class ConsistencyReport(BaseModel):
    """Deterministic verdict over a whole ruleset for one document."""

    consistent: bool = Field(
        ..., description="True iff every rule was evaluable and held."
    )
    checks: List[RuleCheck] = Field(default_factory=list)
    broken_rules: List[str] = Field(
        default_factory=list, description="Ids of rules that were evaluated and VIOLATED."
    )
    unevaluable: List[str] = Field(
        default_factory=list,
        description="Ids of rules that could not be evaluated (missing/non-numeric).",
    )
    summary: str = Field("", description="One-line human summary.")
    notes: List[str] = Field(
        default_factory=list, description="All coercion/unit notes, de-duplicated."
    )
