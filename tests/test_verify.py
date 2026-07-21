"""Independent verifier: catches constraint violations and domain errors."""

from optimcp.spec import DecisionSpec
from optimcp.verify import verify_assignment

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


def test_verify_accepts_feasible():
    cert = verify_assignment(BUDGET_SPEC, {"a": 1, "b": 1, "c": 0})
    assert cert.all_satisfied
    assert cert.objective_value == 100
    assert cert.constraint_checks[0].satisfied


def test_verify_catches_budget_violation():
    cert = verify_assignment(BUDGET_SPEC, {"a": 1, "b": 1, "c": 1})
    assert not cert.all_satisfied
    assert not cert.constraint_checks[0].satisfied
    assert "VIOLATED" in cert.constraint_checks[0].detail


def test_verify_catches_domain_violation():
    cert = verify_assignment(BUDGET_SPEC, {"a": 2, "b": 0, "c": 0})
    assert not cert.all_satisfied
    assert not cert.domain_valid
    assert any("binary" in issue for issue in cert.issues)


def test_integer_off_by_one_above_bound_caught():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "n", "kind": "integer", "lb": 0, "ub": 3}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["n"]}]},
            "constraints": [{"terms": [{"vars": ["n"]}], "op": "<=", "rhs": 3, "name": "cap"}],
        }
    )
    cert = verify_assignment(spec, {"n": 4})
    assert not cert.all_satisfied
    assert not cert.domain_valid
    assert any("above ub" in issue for issue in cert.issues)


def test_casing_mismatch_does_not_crash_and_is_flagged():
    # The whole value prop rests on this: a miscased key must be caught,
    # never raise, never look satisfied.
    cert = verify_assignment(BUDGET_SPEC, {"A": 1, "B": 1, "C": 0})
    assert not cert.all_satisfied
    assert not cert.domain_valid
    assert any("unknown variable 'A'" in i for i in cert.issues)
    assert any("missing value for variable 'a'" in i for i in cert.issues)
    # constraint referencing missing vars is reported as not evaluable
    assert not cert.constraint_checks[0].satisfied
    assert "cannot evaluate" in cert.constraint_checks[0].detail


def test_missing_variable_does_not_crash():
    cert = verify_assignment(BUDGET_SPEC, {"a": 1})  # b, c missing
    assert not cert.all_satisfied
    assert any("missing value for variable 'b'" in i for i in cert.issues)


def test_unknown_extra_key_flagged():
    cert = verify_assignment(BUDGET_SPEC, {"a": 1, "b": 0, "c": 0, "z": 999})
    assert not cert.all_satisfied
    assert any("unknown variable 'z'" in i for i in cert.issues)


def test_zero_coefficient_term_still_enforced():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "x"}, {"name": "y"}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["x"]}]},
            "constraints": [
                {
                    "terms": [{"vars": ["x"], "coeff": 0}, {"vars": ["y"], "coeff": 1}],
                    "op": "<=",
                    "rhs": 0,
                    "name": "y_zero",
                }
            ],
        }
    )
    # x has zero weight; only y matters
    assert verify_assignment(spec, {"x": 1, "y": 0}).all_satisfied
    assert not verify_assignment(spec, {"x": 1, "y": 1}).all_satisfied


def test_fractional_binary_rejected():
    cert = verify_assignment(BUDGET_SPEC, {"a": 0.5, "b": 0, "c": 0})
    assert not cert.all_satisfied
    assert any("integral" in i for i in cert.issues)


def test_equality_constraint_tolerance():
    spec = DecisionSpec.model_validate(
        {
            "variables": [{"name": "a"}, {"name": "b"}],
            "objective": {"sense": "maximize", "terms": [{"vars": ["a"]}]},
            "constraints": [
                {"terms": [{"vars": ["a"]}, {"vars": ["b"]}], "op": "==", "rhs": 1}
            ],
        }
    )
    assert verify_assignment(spec, {"a": 1, "b": 0}).all_satisfied
    assert not verify_assignment(spec, {"a": 1, "b": 1}).all_satisfied
