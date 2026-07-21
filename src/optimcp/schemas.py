"""Function-calling tool schemas for non-MCP agents.

Exports the JSON schema for ``solve_decision`` in the shapes OpenAI and
Anthropic expect, generated directly from the Pydantic :class:`DecisionSpec`, so
any function-calling agent can register the tool without MCP.
"""

from __future__ import annotations

from typing import Any, Dict

from optimcp.spec import DecisionSpec

TOOL_NAME = "solve_decision"
TOOL_DESCRIPTION = (
    "Solve a decision-under-constraints problem and return an assignment that is "
    "independently verified to satisfy every declared constraint. Provide the "
    "decision as structured data (binary/integer variables, an objective to "
    "maximize/minimize, and hard constraints). Use this instead of guessing an "
    "answer that might violate a budget, a capacity, or a rule. "
    "IMPORTANT: use ONE consistent unit for every number across the whole spec - "
    "if costs are in thousands (e.g. 60 for $60k), the budget rhs must also be in "
    "thousands (100, not 100000). Read 'exactly N' / 'must be covered' as '==', "
    "not '<='."
)


def decision_spec_schema() -> Dict[str, Any]:
    """Raw JSON schema of the input (a ``DecisionSpec``)."""
    return DecisionSpec.model_json_schema()


def openai_tool() -> Dict[str, Any]:
    """Tool definition for the OpenAI Chat Completions / Responses API."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "parameters": decision_spec_schema(),
        },
    }


def anthropic_tool() -> Dict[str, Any]:
    """Tool definition for the Anthropic Messages API."""
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": decision_spec_schema(),
    }
