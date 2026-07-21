"""OptiMCP - a decision engine that can't lie about the constraints.

OptiMCP exposes the QBridge optimization engine as an MCP server and a
function-calling tool that any agent (Claude, GPT, LangChain, ...) can call
mid-task: hand it a structured "decision under these constraints" spec and get
back a **verified, constraint-satisfying** answer, instead of the agent
hallucinating one in text.

The tool itself uses **no LLM**. The calling agent fills a structured schema;
OptiMCP compiles it deterministically, solves it (QBridge / QOKit under the
hood, invisibly), and then **independently re-verifies** the answer against the
declared constraints. The guarantee is constraint satisfaction (independently
checked), not global optimality.
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

__version__ = "0.1.0"

__all__ = [
    "ConstraintCheck",
    "ConstraintSpec",
    "DecisionResult",
    "DecisionSpec",
    "ObjectiveSpec",
    "Term",
    "VariableSpec",
    "VerificationCertificate",
    "solve_decision",
    "verify_assignment",
]
