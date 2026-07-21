"""OptiMCP MCP server.

Exposes three tools over MCP (stdio by default; optional HTTP):

* ``solve_decision``   - hand it a decision spec, get back a verified answer.
* ``verify_solution``  - check an assignment the agent *already* has in mind.
* ``capabilities``     - what shapes/limits are supported.

Run with the ``optimcp`` console script or ``python -m optimcp.server``.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from optimcp.classical import MAX_EXACT_STATES
from optimcp.result import DecisionResult, VerificationCertificate
from optimcp.solve import solve_decision as _solve_decision
from optimcp.spec import (
    MAX_TERM_DEGREE,
    MAX_VARIABLES,
    DecisionSpec,
)
from optimcp.verify import verify_assignment as _verify_assignment

mcp = FastMCP(
    "optimcp",
    instructions=(
        "A decision engine that can't lie about the constraints. Call "
        "solve_decision with a structured decision (variables, objective, "
        "constraints) to get back an assignment that is independently verified "
        "to satisfy every constraint - never an unchecked answer. Use "
        "verify_solution to check an assignment you already have. The guarantee "
        "is constraint satisfaction (independently verified), not global "
        "optimality."
    ),
)


@mcp.tool()
def solve_decision(spec: DecisionSpec) -> Dict[str, Any]:
    """Solve a decision-under-constraints problem and return a verified answer.

    Provide the decision as structured data: ``variables`` (binary yes/no or
    bounded integer), an ``objective`` to maximize/minimize, and hard
    ``constraints``. Returns the chosen ``assignment``, its ``objective_value``,
    and a per-constraint ``verification`` certificate. ``status == 'solved'``
    means the answer was independently verified to satisfy every constraint.
    """
    result: DecisionResult = _solve_decision(spec)
    return result.model_dump()


@mcp.tool()
def verify_solution(spec: DecisionSpec, assignment: Dict[str, float]) -> Dict[str, Any]:
    """Check whether a proposed ``assignment`` satisfies a decision's constraints.

    Lets an agent verify an answer it produced itself (in text) against the hard
    constraints, instead of trusting its own reasoning. Returns a certificate
    with per-constraint satisfied/violated details and any domain issues.
    """
    certificate: VerificationCertificate = _verify_assignment(spec, assignment)
    return certificate.model_dump()


@mcp.tool()
def capabilities() -> Dict[str, Any]:
    """Describe the decision shapes and limits this server supports."""
    return {
        "variable_kinds": ["binary", "integer"],
        "objective_senses": ["maximize", "minimize"],
        "constraint_operators": ["<=", ">=", "==", "!=", "<", ">"],
        "max_variables": MAX_VARIABLES,
        "max_term_degree": MAX_TERM_DEGREE,
        "exact_fallback_max_states": MAX_EXACT_STATES,
        "guarantee": "constraint satisfaction (independently verified), not global optimality",
        "reliability_tiers": {
            "verified_feasible": (
                "Any returned answer with status='solved' is independently "
                "re-checked to satisfy every constraint and variable domain."
            ),
            "exact_optimum": (
                "When the joint state space is <= "
                f"{MAX_EXACT_STATES:,} assignments, the classical fallback "
                "searches exhaustively and can also PROVE infeasibility."
            ),
            "heuristic": (
                "Larger problems use a heuristic; it may return "
                "status='no_feasible_found' even when a feasible answer exists."
            ),
        },
        "limits": {
            "max_variables": MAX_VARIABLES,
            "rejects_over_limit": (
                f"Specs with more than {MAX_VARIABLES} variables are rejected at "
                "validation time (decompose into sub-decisions)."
            ),
        },
        "notes": [
            "Objectives and constraints are sums of linear/quadratic terms.",
            "Assignments must use exact variable names (case-sensitive); unknown "
            "or missing names are reported, never silently ignored.",
        ],
    }


def main() -> None:
    """Console entry point for the ``optimcp`` script."""
    parser = argparse.ArgumentParser(description="OptiMCP MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="MCP transport (default: stdio, for Claude Desktop / Cursor / local agents).",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
