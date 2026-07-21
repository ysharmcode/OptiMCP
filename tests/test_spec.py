"""Spec validation: good specs accepted, malformed specs rejected."""

import pytest
from pydantic import ValidationError

from optimcp.spec import DecisionSpec

VALID = {
    "variables": [
        {"name": "a", "kind": "binary"},
        {"name": "b", "kind": "binary"},
    ],
    "objective": {"sense": "maximize", "terms": [{"vars": ["a"], "coeff": 2}]},
    "constraints": [
        {"terms": [{"vars": ["a"]}, {"vars": ["b"]}], "op": "<=", "rhs": 1, "name": "pick_one"}
    ],
}


def test_valid_spec_parses():
    spec = DecisionSpec.model_validate(VALID)
    assert spec.variable_names() == ["a", "b"]
    assert spec.constraints[0].name == "pick_one"


def test_duplicate_variable_names_rejected():
    bad = {
        "variables": [{"name": "a"}, {"name": "a"}],
        "objective": {"sense": "maximize", "terms": []},
    }
    with pytest.raises(ValidationError, match="duplicate"):
        DecisionSpec.model_validate(bad)


def test_unknown_variable_reference_rejected():
    bad = {
        "variables": [{"name": "a"}],
        "objective": {"sense": "maximize", "terms": [{"vars": ["ghost"]}]},
    }
    with pytest.raises(ValidationError, match="unknown variable"):
        DecisionSpec.model_validate(bad)


def test_integer_without_bounds_rejected():
    bad = {
        "variables": [{"name": "n", "kind": "integer"}],
        "objective": {"sense": "minimize", "terms": [{"vars": ["n"]}]},
    }
    with pytest.raises(ValidationError, match="requires both lb and ub"):
        DecisionSpec.model_validate(bad)


def test_integer_inverted_bounds_rejected():
    bad = {
        "variables": [{"name": "n", "kind": "integer", "lb": 5, "ub": 1}],
        "objective": {"sense": "minimize", "terms": [{"vars": ["n"]}]},
    }
    with pytest.raises(ValidationError, match="lb .* > ub"):
        DecisionSpec.model_validate(bad)


def test_term_degree_capped_at_two():
    bad = {
        "variables": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        "objective": {"sense": "maximize", "terms": [{"vars": ["a", "b", "c"]}]},
    }
    with pytest.raises(ValidationError):
        DecisionSpec.model_validate(bad)


def test_too_many_variables_rejected():
    bad = {
        "variables": [{"name": f"x{i}"} for i in range(65)],
        "objective": {"sense": "maximize", "terms": []},
    }
    with pytest.raises(ValidationError, match="too many variables"):
        DecisionSpec.model_validate(bad)


def test_at_limit_variables_accepted():
    ok = {
        "variables": [{"name": f"x{i}"} for i in range(64)],
        "objective": {"sense": "maximize", "terms": []},
    }
    spec = DecisionSpec.model_validate(ok)
    assert len(spec.variables) == 64
