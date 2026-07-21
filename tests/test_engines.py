"""Engine adapters: CP-SAT (exact) and simulated annealing (heuristic)."""

from optimcp.engines.annealer import solve_annealer
from optimcp.engines.cpsat import solve_cpsat
from optimcp.spec import DecisionSpec

KNAPSACK = DecisionSpec.model_validate(
    {
        "variables": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}],
        "objective": {
            "sense": "maximize",
            "terms": [
                {"vars": ["a"], "coeff": 60},
                {"vars": ["b"], "coeff": 100},
                {"vars": ["c"], "coeff": 120},
                {"vars": ["d"], "coeff": 40},
            ],
        },
        "constraints": [
            {
                "name": "weight",
                "op": "<=",
                "rhs": 40,
                "terms": [
                    {"vars": ["a"], "coeff": 10},
                    {"vars": ["b"], "coeff": 20},
                    {"vars": ["c"], "coeff": 30},
                    {"vars": ["d"], "coeff": 15},
                ],
            }
        ],
    }
)

INFEASIBLE = DecisionSpec.model_validate(
    {
        "variables": [{"name": "a"}],
        "objective": {"sense": "maximize", "terms": [{"vars": ["a"]}]},
        "constraints": [
            {"terms": [{"vars": ["a"]}], "op": ">=", "rhs": 1, "name": "one"},
            {"terms": [{"vars": ["a"]}], "op": "<=", "rhs": 0, "name": "zero"},
        ],
    }
)


def test_cpsat_reaches_optimum_and_flags_it():
    # Capacity 40: a+c weighs exactly 40 for value 180 (b+c would weigh 50).
    out = solve_cpsat(KNAPSACK)
    assert out.assignment == {"a": 1, "b": 0, "c": 1, "d": 0}
    assert out.proven_optimal is True


def test_cpsat_proves_infeasibility():
    out = solve_cpsat(INFEASIBLE)
    assert out.assignment is None
    assert out.proven_infeasible is True


def test_cpsat_handles_fractional_coefficients():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "a"}, {"name": "b"}],
            "objective": {
                "sense": "maximize",
                "terms": [{"vars": ["a"], "coeff": 1.5}, {"vars": ["b"], "coeff": 1.1}],
            },
            "constraints": [
                {
                    "terms": [{"vars": ["a"], "coeff": 0.5}, {"vars": ["b"], "coeff": 0.5}],
                    "op": "<=",
                    "rhs": 0.5,
                    "name": "pick_one",
                }
            ],
        }
    )
    out = solve_cpsat(spec)
    assert out.assignment == {"a": 1, "b": 0}


def test_annealer_finds_feasible_knapsack():
    out = solve_annealer(KNAPSACK)
    # Heuristic: on this small instance it typically reaches the 180 optimum,
    # but we only require a verified-feasible answer (weight within capacity).
    assert out.assignment is not None
    weight = sum(
        c * out.assignment[v]
        for v, c in {"a": 10, "b": 20, "c": 30, "d": 15}.items()
    )
    assert weight <= 40


def test_annealer_skips_not_equal_operator():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "a"}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["a"]}]},
            "constraints": [{"terms": [{"vars": ["a"]}], "op": "!=", "rhs": 0, "name": "x"}],
        }
    )
    out = solve_annealer(spec)
    assert out.available is False
