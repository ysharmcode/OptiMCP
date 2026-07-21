"""Structured, validated decision spec.

This is the entire input contract of OptiMCP. An agent describes a decision
as data (variables, an objective, and constraints); there is no natural-language
parsing and no LLM anywhere in this package, which is exactly what lets the
"can't lie about the constraints" guarantee hold - the mapping from this spec to
a solved, verified answer is deterministic.

A problem has the shape::

    maximize / minimize   sum(coeff * x_i [* x_j])
    subject to            sum(coeff * x_i [* x_j])  <op>  rhs      (per constraint)

over binary or bounded-integer variables. Terms are degree <= 2 (linear or
quadratic), which both engines (CP-SAT and simulated annealing) handle directly.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

VarKind = Literal["binary", "integer"]
Op = Literal["<=", ">=", "==", "!=", "<", ">"]
Sense = Literal["maximize", "minimize"]

# Guard rails: keep problems in the range the engine + exact fallback can handle.
MAX_VARIABLES = 64
MAX_TERM_DEGREE = 2


class Term(BaseModel):
    """A single (possibly quadratic) monomial ``coeff * prod(vars)``."""

    vars: List[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_TERM_DEGREE,
        description="1 variable (linear term) or 2 variables (quadratic term).",
    )
    coeff: float = Field(1.0, description="Numeric coefficient multiplying the variable product.")


class VariableSpec(BaseModel):
    """A decision variable: a yes/no choice (binary) or a bounded count (integer)."""

    name: str = Field(..., description="Unique identifier used by objective/constraint terms.")
    kind: VarKind = Field("binary", description="'binary' (0/1) or 'integer' (bounded count).")
    lb: Optional[int] = Field(None, description="Lower bound (required for integer variables).")
    ub: Optional[int] = Field(None, description="Upper bound (required for integer variables).")
    description: Optional[str] = Field(None, description="Optional human-readable meaning.")

    @model_validator(mode="after")
    def _check_bounds(self) -> "VariableSpec":
        if not self.name or not self.name.strip():
            raise ValueError("variable name must be a non-empty string")
        if self.kind == "integer":
            if self.lb is None or self.ub is None:
                raise ValueError(
                    f"integer variable {self.name!r} requires both lb and ub"
                )
            if self.lb > self.ub:
                raise ValueError(
                    f"integer variable {self.name!r} has lb ({self.lb}) > ub ({self.ub})"
                )
        return self


class ObjectiveSpec(BaseModel):
    """What to maximize or minimize."""

    sense: Sense = Field(..., description="'maximize' or 'minimize'.")
    terms: List[Term] = Field(
        default_factory=list,
        description="Objective as a sum of terms; empty means 'any feasible answer'.",
    )


class ConstraintSpec(BaseModel):
    """A hard rule the answer must satisfy: ``sum(terms) <op> rhs``."""

    terms: List[Term] = Field(..., min_length=1, description="Left-hand side, a sum of terms.")
    op: Op = Field(..., description="Comparison operator.")
    rhs: float = Field(..., description="Right-hand side constant.")
    name: Optional[str] = Field(None, description="Optional label, echoed back in the certificate.")
    description: Optional[str] = Field(None, description="Optional human-readable meaning.")


class DecisionSpec(BaseModel):
    """A complete decision-under-constraints problem."""

    variables: List[VariableSpec] = Field(..., min_length=1)
    objective: ObjectiveSpec
    constraints: List[ConstraintSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "DecisionSpec":
        names = [v.name for v in self.variables]
        if len(names) > MAX_VARIABLES:
            raise ValueError(
                f"too many variables ({len(names)} > {MAX_VARIABLES}); "
                "decompose the decision into smaller sub-decisions"
            )
        seen = set()
        for n in names:
            if n in seen:
                raise ValueError(f"duplicate variable name: {n!r}")
            seen.add(n)
        known = set(names)
        all_terms: List[Term] = list(self.objective.terms)
        for c in self.constraints:
            all_terms.extend(c.terms)
        for term in all_terms:
            for vn in term.vars:
                if vn not in known:
                    raise ValueError(f"term references unknown variable {vn!r}")
        return self

    def variable_names(self) -> List[str]:
        return [v.name for v in self.variables]
