"""OptiMCP MCP server.

Exposes four tools over MCP (stdio by default; optional HTTP):

* ``check_consistency`` - hand it a JSON document + declared rules, get back
  *exactly which rule broke* (computed vs expected, with the delta). Headline.
* ``solve_decision``    - hand it a decision spec, get back a verified answer.
* ``verify_solution``   - check an assignment the agent *already* has in mind.
* ``capabilities``      - what shapes/limits are supported.

Run with the ``optimcp`` console script or ``python -m optimcp.server``.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

from optimcp.check import check_consistency as _check_consistency
from optimcp.check.rules import AGG_FNS, CALC_FNS, MAX_RULES, Rule
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
        "A consistency checker that can't lie about the numbers. Call "
        "check_consistency with a JSON document (a budget, invoice, schedule, "
        "financial table) and a list of declared rules; it recomputes every "
        "rule independently (no LLM, exact decimal arithmetic) and tells you "
        "PROVABLY which rule broke - the computed value, the expected value, and "
        "the delta. A rule it cannot evaluate (missing/non-numeric field) is "
        "reported as failed, never silently skipped. Use this to audit your own "
        "structured output before you commit to it. solve_decision (and its "
        "optional repair path) can additionally produce a corrected answer for "
        "linear numeric problems."
    ),
)


@mcp.tool()
def check_consistency(
    document: Dict[str, Any], rules: List[Rule]
) -> Dict[str, Any]:
    """Check whether a JSON ``document`` obeys its declared numeric/logical ``rules``.

    Each rule asserts ``lhs <op> rhs`` where ``lhs``/``rhs`` are expressions over
    the document: literals, field refs (``"invoice.total"``,
    ``"line_items[0].amount"``), aggregations over a wildcard path
    (``sum``/``avg``/``min``/``max``/``count`` of ``"line_items[*].amount"``), and
    arithmetic (``add``/``sub``/``mul``/``div``/``neg``/``abs``/``round``/``pow``/
    ``pct_change``). Returns a report naming every VIOLATED rule with its computed
    value, expected value and delta, plus any rule that could not be evaluated.
    Use this to catch totals that do not match their line items, growth
    percentages computed the wrong way, allocations that do not sum to the
    budget, and similar arithmetic-invariant failures.
    """
    return _check_consistency(document, rules).model_dump()


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
    """Describe what this server can check/solve and its limits."""
    return {
        "primary_tool": "check_consistency",
        "check_consistency": {
            "purpose": (
                "Deterministically verify that a JSON document obeys declared "
                "numeric/logical rules, and report exactly which rule broke."
            ),
            "expression_kinds": ["lit", "ref", "agg", "calc"],
            "aggregations": sorted(AGG_FNS),
            "arithmetic": sorted(CALC_FNS),
            "operators": ["<=", ">=", "==", "!=", "<", ">"],
            "path_syntax": "dot paths with [i] indexing and [*] wildcards, e.g. line_items[*].amount",
            "tolerance": "per-rule abs_tol + rel_tol*|rhs|; comparisons run in exact Decimal arithmetic",
            "max_rules": MAX_RULES,
            "guarantee": (
                "No LLM is used; every number is recomputed independently. A "
                "rule that cannot be evaluated (missing/non-numeric field) is "
                "reported as failed, never silently skipped."
            ),
        },
        "solve_decision": {
            "purpose": "Optional repair/optimization for linear numeric problems.",
            "variable_kinds": ["binary", "integer"],
            "objective_senses": ["maximize", "minimize"],
            "constraint_operators": ["<=", ">=", "==", "!=", "<", ">"],
            "max_variables": MAX_VARIABLES,
            "max_term_degree": MAX_TERM_DEGREE,
            "engines": ["cp-sat", "simulated-annealing"],
            "guarantee": "constraint satisfaction (independently verified), not global optimality",
            "reliability_tiers": {
                "verified_feasible": (
                    "Any returned answer with status='solved' is independently "
                    "re-checked to satisfy every constraint and variable domain."
                ),
                "exact_optimum": (
                    "The CP-SAT engine (OR-Tools) solves exactly; when it reports "
                    "OPTIMAL the answer is provably optimal, and it can also PROVE "
                    "infeasibility (status='infeasible')."
                ),
                "heuristic": (
                    "A simulated-annealing engine provides an independent second "
                    "opinion; on hard problems it may only find a feasible answer, "
                    "or none within its budget."
                ),
            },
        },
        "notes": [
            "check_consistency reads arbitrary nested JSON; solve_decision uses "
            "flat binary/integer variables with linear/quadratic terms.",
            "Field/variable names are case-sensitive; unknown or missing names "
            "are reported, never silently ignored.",
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
