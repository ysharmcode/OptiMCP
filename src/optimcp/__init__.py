"""OptiMCP - verification layer over agent structured emissions.

OptiMCP checks whether structured output obeys declared numeric/logical rules
and *provably tells you which rule broke*. Use :func:`check_consistency` for
one-shot checks, or register named rulesets and run the self-hosted daemon for
always-on monitoring with observe/refuse policies.

No LLM is used inside OptiMCP: every number is recomputed in exact Decimal
arithmetic. The optional solver (:func:`solve_decision`) remains available as a
repair path for linear numeric problems.
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
from optimcp.monitor import (
    MonitorService,
    MonitorStore,
    RulesetRecord,
    VerifyResult,
    document_hash,
)

__version__ = "0.2.0"

__all__ = [
    "ConstraintCheck",
    "ConstraintSpec",
    "ConsistencyReport",
    "DecisionResult",
    "DecisionSpec",
    "Expr",
    "MonitorService",
    "MonitorStore",
    "ObjectiveSpec",
    "Rule",
    "RuleCheck",
    "Ruleset",
    "RulesetRecord",
    "Term",
    "VariableSpec",
    "VerificationCertificate",
    "VerifyResult",
    "check_consistency",
    "document_hash",
    "solve_decision",
    "verify_assignment",
]
