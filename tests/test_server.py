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


CHECK_DOC = {
    "invoice": {"subtotal": 320, "tax": 25.6, "total": 345.6},
    "line_items": [{"amount": 100}, {"amount": 120}, {"amount": 110}],
}
CHECK_RULES = [
    {
        "id": "subtotal_matches_items",
        "lhs": {"kind": "ref", "path": "invoice.subtotal"},
        "op": "==",
        "rhs": {"kind": "agg", "fn": "sum", "path": "line_items[*].amount"},
    },
    {
        "id": "total_ok",
        "lhs": {"kind": "ref", "path": "invoice.total"},
        "op": "==",
        "rhs": {
            "kind": "calc",
            "fn": "add",
            "args": [
                {"kind": "ref", "path": "invoice.subtotal"},
                {"kind": "ref", "path": "invoice.tax"},
            ],
        },
    },
]


def test_list_tools_exposes_all_tools():
    async def go():
        return await mcp.list_tools()

    names = {t.name for t in asyncio.run(go())}
    assert {
        "check_consistency",
        "solve_decision",
        "verify_solution",
        "capabilities",
    } <= names


def test_check_consistency_tool_round_trip():
    async def go():
        return await mcp.call_tool(
            "check_consistency", {"document": CHECK_DOC, "rules": CHECK_RULES}
        )

    report = _structured(asyncio.run(go()))
    # subtotal (320) != sum of items (330) -> that rule is broken and named.
    assert report["consistent"] is False
    assert "subtotal_matches_items" in report["broken_rules"]


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
    assert caps["primary_tool"] == "check_consistency"
    cc = caps["check_consistency"]
    assert set(cc["expression_kinds"]) == {"lit", "ref", "agg", "calc"}
    assert "sum" in cc["aggregations"]
    assert "pct_change" in cc["arithmetic"]
    sd = caps["solve_decision"]
    assert "binary" in sd["variable_kinds"]
    assert sd["max_variables"] == 64
    assert sd["engines"] == ["cp-sat", "simulated-annealing"]
    assert set(sd["reliability_tiers"]) == {
        "verified_feasible",
        "exact_optimum",
        "heuristic",
    }
