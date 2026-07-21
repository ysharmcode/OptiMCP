"""Adapters and the optional repair bridge for the consistency checker."""

import pytest

from optimcp.check.repair import build_repair_spec, rule_to_constraint, try_repair
from optimcp.check.rules import Rule, Ruleset


def _rule(**kw):
    return Rule.model_validate(kw)


# --------------------------- repair bridge ---------------------------

LINEAR_RULES = Ruleset(rules=[
    _rule(id="sum", lhs={"kind": "calc", "fn": "add", "args": [
        {"kind": "ref", "path": "a"}, {"kind": "ref", "path": "b"}]},
        op="==", rhs={"kind": "lit", "value": 10}),
    _rule(id="diff", lhs={"kind": "calc", "fn": "sub", "args": [
        {"kind": "ref", "path": "a"}, {"kind": "ref", "path": "b"}]},
        op="==", rhs={"kind": "lit", "value": 2}),
])

VARIABLES = [
    {"name": "a", "kind": "integer", "lb": 0, "ub": 10},
    {"name": "b", "kind": "integer", "lb": 0, "ub": 10},
]
OBJECTIVE = {"sense": "maximize", "terms": [{"vars": ["a"]}]}


def test_rule_to_constraint_linearizes():
    c = rule_to_constraint(LINEAR_RULES.rules[0])
    assert c is not None
    assert c.op == "=="
    # a + b == 10  ->  terms {a:1, b:1}, rhs 10
    coeffs = {t.vars[0]: t.coeff for t in c.terms}
    assert coeffs == {"a": 1.0, "b": 1.0}
    assert c.rhs == 10.0


def test_build_repair_spec_and_solve():
    spec = build_repair_spec(LINEAR_RULES, variables=VARIABLES, objective=OBJECTIVE)
    assert spec is not None
    result = try_repair(LINEAR_RULES, variables=VARIABLES, objective=OBJECTIVE)
    assert result is not None
    assert result.status == "solved"
    # a + b = 10, a - b = 2  ->  a = 6, b = 4
    assert result.assignment == {"a": 6, "b": 4}
    assert result.verification.all_satisfied


def test_nonlinear_ruleset_is_not_repairable():
    nonlinear = Ruleset(rules=[_rule(
        id="agg", lhs={"kind": "agg", "fn": "sum", "path": "items[*].x"},
        op="==", rhs={"kind": "lit", "value": 5})])
    assert build_repair_spec(nonlinear, variables=VARIABLES, objective=OBJECTIVE) is None
    assert try_repair(nonlinear, variables=VARIABLES, objective=OBJECTIVE) is None

    product = Ruleset(rules=[_rule(
        id="prod", lhs={"kind": "calc", "fn": "mul", "args": [
            {"kind": "ref", "path": "a"}, {"kind": "ref", "path": "b"}]},
        op="==", rhs={"kind": "lit", "value": 5})])
    assert build_repair_spec(product, variables=VARIABLES, objective=OBJECTIVE) is None


# --------------------------- langchain check tool ---------------------------


def test_langchain_check_tool_runs_end_to_end():
    pytest.importorskip("langchain_core")
    from optimcp.adapters.langchain import build_check_consistency_tool

    tool = build_check_consistency_tool()
    assert tool.name == "check_consistency"
    out = tool.invoke({
        "document": {"total": 320, "items": [{"amt": 100}, {"amt": 120}, {"amt": 110}]},
        "rules": [{
            "id": "foot",
            "lhs": {"kind": "ref", "path": "total"},
            "op": "==",
            "rhs": {"kind": "agg", "fn": "sum", "path": "items[*].amt"},
        }],
    })
    assert out["consistent"] is False
    assert "foot" in out["broken_rules"]
