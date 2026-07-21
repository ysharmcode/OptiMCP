"""Solve orchestrator: verified feasible answers, honest statuses, fallback."""

from optimcp.solve import solve_decision
from optimcp.spec import DecisionSpec

BUDGET_SPEC = DecisionSpec.model_validate(
    {
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
)


def test_solve_returns_verified_feasible():
    result = solve_decision(BUDGET_SPEC)
    assert result.status == "solved"
    assert result.feasible
    assert result.verification.all_satisfied
    # every declared constraint respected
    cost = 55 * result.assignment["a"] + 45 * result.assignment["b"] + 50 * result.assignment["c"]
    assert cost <= 100


def test_solve_finds_optimum_on_small_instance():
    # exact fallback (or engine) should reach the true optimum {a,b} = 100
    result = solve_decision(BUDGET_SPEC)
    assert result.objective_value == 100


def test_forced_fallback_still_solves():
    # Skip the engine entirely; the classical backbone must still return verified.
    result = solve_decision(BUDGET_SPEC, _force_engine_failure=True)
    assert result.status == "solved"
    assert result.verification.all_satisfied


def test_infeasible_spec_reported_honestly():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "a"}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["a"]}]},
            "constraints": [
                {"terms": [{"vars": ["a"]}], "op": ">=", "rhs": 1, "name": "must_be_one"},
                {"terms": [{"vars": ["a"]}], "op": "<=", "rhs": 0, "name": "must_be_zero"},
            ],
        }
    )
    result = solve_decision(spec)
    assert result.status == "infeasible"
    assert not result.feasible
    assert result.assignment == {}


def test_diagnostics_opt_in_only():
    assert solve_decision(BUDGET_SPEC).diagnostics is None
    diag = solve_decision(BUDGET_SPEC, include_diagnostics=True).diagnostics
    assert diag is not None and "winning_source" in diag


def test_returns_exact_optimum_not_just_feasible():
    # Weekend-shift reluctance: exactly one person per shift (==1). A merely
    # *feasible* answer (e.g. Ana takes both) costs 9; the true optimum is 3
    # (Ana-Sat + Ben-Sun). The orchestrator must return the optimum on a problem
    # this small, not whatever feasible sample the engine happened to produce.
    spec = DecisionSpec.model_validate(
        {
            "variables": [
                {"name": "ana_sat"},
                {"name": "ana_sun"},
                {"name": "ben_sat"},
                {"name": "ben_sun"},
            ],
            "objective": {
                "sense": "minimize",
                "terms": [
                    {"vars": ["ana_sat"], "coeff": 1},
                    {"vars": ["ana_sun"], "coeff": 8},
                    {"vars": ["ben_sat"], "coeff": 6},
                    {"vars": ["ben_sun"], "coeff": 2},
                ],
            },
            "constraints": [
                {"terms": [{"vars": ["ana_sat"]}, {"vars": ["ben_sat"]}], "op": "==", "rhs": 1, "name": "sat"},
                {"terms": [{"vars": ["ana_sun"]}, {"vars": ["ben_sun"]}], "op": "==", "rhs": 1, "name": "sun"},
            ],
        }
    )
    result = solve_decision(spec)
    assert result.status == "solved"
    assert result.objective_value == 3
    assert result.assignment == {"ana_sat": 1, "ana_sun": 0, "ben_sat": 0, "ben_sun": 1}


def test_integer_decision_solves():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "n", "kind": "integer", "lb": 0, "ub": 5}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["n"], "coeff": 1}]},
            "constraints": [{"terms": [{"vars": ["n"]}], "op": "<=", "rhs": 3, "name": "cap"}],
        }
    )
    result = solve_decision(spec)
    assert result.status == "solved"
    assert result.assignment["n"] <= 3
