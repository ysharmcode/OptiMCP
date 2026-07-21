"""Function-calling tool schemas for non-MCP agents.

Exports JSON schemas for both tools in the shapes OpenAI and Anthropic expect,
generated directly from the Pydantic models, so any function-calling agent can
register them without MCP. ``check_consistency`` is the primary tool;
``solve_decision`` is the optional repair/optimization tool.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field

from optimcp.check.rules import Rule
from optimcp.spec import DecisionSpec


class CheckConsistencyArgs(BaseModel):
    """Arguments for the ``check_consistency`` tool."""

    document: Dict[str, Any] = Field(
        ..., description="The JSON object to audit (budget, invoice, schedule, table...)."
    )
    rules: list[Rule] = Field(
        ..., description="Declared rules; each asserts lhs <op> rhs over the document."
    )


# ---- primary tool: check_consistency --------------------------------------

TOOL_NAME = "check_consistency"
TOOL_DESCRIPTION = (
    "Verify that a JSON document obeys its declared numeric/logical rules, and "
    "report PROVABLY which rule broke (computed value vs expected value, with the "
    "delta). Rules are pure data checked with exact arithmetic and no LLM. Each "
    "rule is lhs <op> rhs, where an expression is a literal ({'kind':'lit',"
    "'value':N}), a field ref ({'kind':'ref','path':'invoice.total'}), an "
    "aggregation over a wildcard path ({'kind':'agg','fn':'sum','path':"
    "'line_items[*].amount'}), or arithmetic ({'kind':'calc','fn':'sub','args':"
    "[...]}; fns: add,sub,mul,div,neg,abs,round,pow,pct_change). Use this to catch "
    "totals that don't match their line items, growth percentages computed the "
    "wrong way (pct_change(old,new)=(new-old)/old*100), allocations that don't sum "
    "to the budget, and similar failures - instead of trusting your own arithmetic."
)


def check_consistency_schema() -> Dict[str, Any]:
    """Raw JSON schema of the ``check_consistency`` input."""
    return CheckConsistencyArgs.model_json_schema()


def openai_tool() -> Dict[str, Any]:
    """`check_consistency` for the OpenAI Chat Completions / Responses API."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "parameters": check_consistency_schema(),
        },
    }


def anthropic_tool() -> Dict[str, Any]:
    """`check_consistency` for the Anthropic Messages API."""
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": check_consistency_schema(),
    }


# ---- optional tool: solve_decision ----------------------------------------

SOLVE_TOOL_NAME = "solve_decision"
SOLVE_TOOL_DESCRIPTION = (
    "Solve a decision-under-constraints problem and return an assignment that is "
    "independently verified to satisfy every declared constraint. Provide the "
    "decision as structured data (binary/integer variables, an objective to "
    "maximize/minimize, and hard constraints). Use this to produce a corrected, "
    "verified answer when check_consistency reports a violation on a linear "
    "numeric problem. IMPORTANT: use ONE consistent unit for every number across "
    "the whole spec - if costs are in thousands (e.g. 60 for $60k), the budget "
    "rhs must also be in thousands (100, not 100000). Read 'exactly N' / 'must be "
    "covered' as '==', not '<='."
)


def decision_spec_schema() -> Dict[str, Any]:
    """Raw JSON schema of the ``solve_decision`` input (a ``DecisionSpec``)."""
    return DecisionSpec.model_json_schema()


def solve_openai_tool() -> Dict[str, Any]:
    """`solve_decision` for the OpenAI Chat Completions / Responses API."""
    return {
        "type": "function",
        "function": {
            "name": SOLVE_TOOL_NAME,
            "description": SOLVE_TOOL_DESCRIPTION,
            "parameters": decision_spec_schema(),
        },
    }


def solve_anthropic_tool() -> Dict[str, Any]:
    """`solve_decision` for the Anthropic Messages API."""
    return {
        "name": SOLVE_TOOL_NAME,
        "description": SOLVE_TOOL_DESCRIPTION,
        "input_schema": decision_spec_schema(),
    }
