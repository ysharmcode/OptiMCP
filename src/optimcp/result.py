"""Result and verification-certificate models returned to the calling agent."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

Status = Literal["solved", "infeasible", "no_feasible_found"]
AssignmentValue = Union[int, float]


class ConstraintCheck(BaseModel):
    """Independent re-check of a single constraint against the returned answer."""

    name: Optional[str] = None
    satisfied: bool
    detail: str = Field(..., description="e.g. 'spend 90 <= budget 100: satisfied'.")


class VerificationCertificate(BaseModel):
    """Proof, computed independently of the solver, that an answer obeys the rules."""

    all_satisfied: bool
    objective_value: float
    constraint_checks: List[ConstraintCheck] = Field(default_factory=list)
    domain_valid: bool = True
    issues: List[str] = Field(default_factory=list)


class DecisionResult(BaseModel):
    """What an agent gets back from ``solve_decision``.

    ``status == 'solved'`` guarantees the assignment was independently verified to
    satisfy every declared constraint (and variable domain). It does NOT claim
    global optimality.
    """

    status: Status
    feasible: bool = Field(..., description="True iff a verified constraint-satisfying answer is returned.")
    assignment: Dict[str, AssignmentValue] = Field(default_factory=dict)
    objective_value: Optional[float] = None
    objective_sense: Optional[str] = None
    verification: VerificationCertificate
    message: str = ""
    diagnostics: Optional[Dict[str, object]] = Field(
        default=None,
        description="Optional internals (engine used, timings); omitted by default.",
    )
