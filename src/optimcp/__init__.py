"""OptiMCP - a consistency checker that can't lie about the numbers.

OptiMCP is an MCP server and function-calling tool that any agent (Claude, GPT,
LangChain, ...) can call to **check whether structured output actually obeys its
own stated rules**. Hand :func:`check_consistency` a JSON document (a budget, an
invoice, a schedule, a financial table) and a set of declared rules, and it
tells you *provably which rule broke* - the computed value, the expected value,
and the delta.

The tool itself uses **no LLM**: rules are pure data and every number is
recomputed independently in exact :class:`~decimal.Decimal` arithmetic. That
independence is the whole point - it is the check an LLM's own reasoning cannot
provide for itself.

The original decision **solver** (:func:`solve_decision`, OR-Tools CP-SAT plus a
simulated-annealing second opinion, each answer independently re-verified) is
still here as an optional *repair* path: when a broken ruleset is linear, it can
return a corrected, verified answer.
"""

from optimcp.spec import (
    ConstraintSpec,
    DecisionSpec,
    ObjectiveSpec,
    Term,
    VariableSpec,
)
from optimcp.result import ConstraintCheck, DecisionResult, VerificationCertificate
from optimcp.solve import solve_decision
from optimcp.verify import verify_assignment
from optimcp.check import (
    ConsistencyReport,
    Expr,
    Rule,
    RuleCheck,
    Ruleset,
    check_consistency,
)

__version__ = "0.1.0"

__all__ = [
    "ConstraintCheck",
    "ConstraintSpec",
    "ConsistencyReport",
    "DecisionResult",
    "DecisionSpec",
    "Expr",
    "ObjectiveSpec",
    "Rule",
    "RuleCheck",
    "Ruleset",
    "Term",
    "VariableSpec",
    "VerificationCertificate",
    "check_consistency",
    "solve_decision",
    "verify_assignment",
]
