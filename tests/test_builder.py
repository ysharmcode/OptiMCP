"""Builder round-trip: spec -> QBridge problem with the right structure."""

from optimcp.builder import build_problem
from optimcp.spec import DecisionSpec


def test_build_binary_problem_structure():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "a"}, {"name": "b"}],
            "objective": {
                "sense": "maximize",
                "terms": [{"vars": ["a"], "coeff": 3}, {"vars": ["b"], "coeff": 2}],
            },
            "constraints": [
                {"terms": [{"vars": ["a"]}, {"vars": ["b"]}], "op": "<=", "rhs": 1}
            ],
        }
    )
    problem, variables = build_problem(spec)
    assert set(variables) == {"a", "b"}
    assert len(problem.constraints) == 1


def test_build_integer_problem_uses_bounds():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "n", "kind": "integer", "lb": 0, "ub": 3}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["n"], "coeff": 1}]},
            "constraints": [{"terms": [{"vars": ["n"]}], "op": "<=", "rhs": 2}],
        }
    )
    problem, variables = build_problem(spec)
    assert "n" in variables
    assert len(problem.constraints) == 1


def test_quadratic_objective_term_builds():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "a"}, {"name": "b"}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["a", "b"], "coeff": 5}]},
        }
    )
    problem, variables = build_problem(spec)
    assert set(variables) == {"a", "b"}
