"""In-process MCP round-trip through the FastMCP server."""

import asyncio
import json

from optimcp.server import mcp

SPEC = {
    "variables": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
    "objective": {
        "sense": "maximize",
        "terms": [
            {"vars": ["a"], "coeff": 60},
            {"vars": ["b"], "coeff": 40},
            {"vars": ["c"], "coeff": 35},
        ],
    },
    "constraints": [
        {
            "name": "budget",
            "terms": [
                {"vars": ["a"], "coeff": 55},
                {"vars": ["b"], "coeff": 45},
                {"vars": ["c"], "coeff": 50},
            ],
            "op": "<=",
            "rhs": 100,
        }
    ],
}


def _structured(raw):
    """Normalize FastMCP.call_tool output to the structured dict result."""
    if isinstance(raw, tuple):
        raw = raw[1]
    if isinstance(raw, dict):
        # FastMCP may wrap a non-dict return under 'result'; ours is already a dict.
        return raw.get("result", raw)
    # Fallback: list of content blocks -> parse the text JSON.
    return json.loads(raw[0].text)


def test_list_tools_exposes_the_three_tools():
    async def go():
        return await mcp.list_tools()

    names = {t.name for t in asyncio.run(go())}
    assert {"solve_decision", "verify_solution", "capabilities"} <= names


def test_solve_decision_tool_round_trip():
    async def go():
        return await mcp.call_tool("solve_decision", {"spec": SPEC})

    result = _structured(asyncio.run(go()))
    assert result["status"] == "solved"
    assert result["feasible"] is True
    assert result["verification"]["all_satisfied"] is True


def test_verify_solution_tool_catches_violation():
    async def go():
        return await mcp.call_tool(
            "verify_solution", {"spec": SPEC, "assignment": {"a": 1, "b": 1, "c": 1}}
        )

    cert = _structured(asyncio.run(go()))
    assert cert["all_satisfied"] is False
    assert cert["constraint_checks"][0]["satisfied"] is False


def test_capabilities_tool():
    async def go():
        return await mcp.call_tool("capabilities", {})

    caps = _structured(asyncio.run(go()))
    assert "binary" in caps["variable_kinds"]
    assert caps["max_variables"] == 64
    assert caps["exact_fallback_max_states"] == 2_000_000
    assert set(caps["reliability_tiers"]) == {
        "verified_feasible",
        "exact_optimum",
        "heuristic",
    }
