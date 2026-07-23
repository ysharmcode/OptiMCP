"""The deterministic consistency checker - the product's core guarantee.

These tests pin the behaviours the whole pitch rests on: exact arithmetic (no
float drift), derived values computed correctly, aggregations over arrays, and -
above all - that a rule which cannot be evaluated is reported as failed, never
silently skipped and never raised.
"""

import pytest

from optimcp import check_consistency
from optimcp.check.paths import PathError, parse_path, resolve_all, resolve_ref
from optimcp.check.rules import Expr, Rule, Ruleset


# --------------------------- path resolution ---------------------------


def test_dot_and_index_paths():
    doc = {"a": {"b": [10, 20, 30]}}
    assert resolve_ref(doc, "a.b[1]") == 20
    assert resolve_ref(doc, "a.b[-1]") == 30


def test_wildcard_collects_leaves():
    doc = {"items": [{"amt": 1}, {"amt": 2}, {"amt": 3}]}
    assert resolve_all(doc, "items[*].amt") == [1, 2, 3]


def test_missing_path_raises_patherror_not_keyerror():
    with pytest.raises(PathError):
        resolve_ref({"a": 1}, "b")
    with pytest.raises(PathError):
        resolve_ref({"a": {"b": 1}}, "a.c")


def test_malformed_path_rejected():
    with pytest.raises(PathError):
        parse_path("")


# --------------------------- literal / ref / calc ---------------------------


def _rule(**kw):
    return Rule.model_validate(kw)


def test_simple_ref_equality():
    doc = {"x": 5, "y": 5}
    rep = check_consistency(doc, [_rule(
        id="xy", lhs={"kind": "ref", "path": "x"}, op="==",
        rhs={"kind": "ref", "path": "y"})])
    assert rep.consistent
    assert rep.checks[0].lhs_value == 5.0


def test_total_matches_line_items():
    doc = {"total": 330, "items": [{"amt": 100}, {"amt": 120}, {"amt": 110}]}
    rep = check_consistency(doc, [_rule(
        id="foot", lhs={"kind": "ref", "path": "total"}, op="==",
        rhs={"kind": "agg", "fn": "sum", "path": "items[*].amt"})])
    assert rep.consistent


def test_total_mismatch_is_named_with_delta():
    doc = {"total": 320, "items": [{"amt": 100}, {"amt": 120}, {"amt": 110}]}
    rep = check_consistency(doc, [_rule(
        id="foot", lhs={"kind": "ref", "path": "total"}, op="==",
        rhs={"kind": "agg", "fn": "sum", "path": "items[*].amt"})])
    assert not rep.consistent
    assert rep.broken_rules == ["foot"]
    assert rep.checks[0].delta == -10.0
    assert "off by 10" in rep.checks[0].detail


# --------------------------- aggregations ---------------------------


def test_all_aggregations():
    doc = {"v": [{"n": 2}, {"n": 4}, {"n": 6}]}
    fns = {"sum": 12, "avg": 4, "min": 2, "max": 6, "count": 3}
    for fn, expected in fns.items():
        rep = check_consistency(doc, [_rule(
            id=fn, lhs={"kind": "agg", "fn": fn, "path": "v[*].n"}, op="==",
            rhs={"kind": "lit", "value": expected})])
        assert rep.consistent, (fn, rep.summary)


def test_count_of_missing_array_is_unevaluable():
    rep = check_consistency({}, [_rule(
        id="c", lhs={"kind": "agg", "fn": "count", "path": "v[*].n"}, op="==",
        rhs={"kind": "lit", "value": 0})])
    assert "c" in rep.unevaluable


# --------------------------- Decimal precision ---------------------------


def test_tax_chain_no_float_drift():
    # 0.08 * 330 = 26.4 exactly; naive float would risk 26.400000000000002.
    doc = {"subtotal": 330, "tax": 26.4}
    rep = check_consistency(doc, [_rule(
        id="tax", lhs={"kind": "ref", "path": "tax"}, op="==",
        rhs={"kind": "calc", "fn": "mul", "args": [
            {"kind": "ref", "path": "subtotal"}, {"kind": "lit", "value": 0.08}]})])
    assert rep.consistent, rep.summary


# --------------------------- derived value: pct_change ---------------------------


def test_pct_change_direction_50M_to_30M_is_minus_40():
    doc = {"prev": 50, "curr": 30, "stated": -40}
    rep = check_consistency(doc, [_rule(
        id="growth", lhs={"kind": "ref", "path": "stated"}, op="==",
        rhs={"kind": "calc", "fn": "pct_change", "args": [
            {"kind": "ref", "path": "prev"}, {"kind": "ref", "path": "curr"}]})])
    assert rep.consistent, rep.summary


def test_pct_change_wrong_sign_is_caught():
    doc = {"prev": 50, "curr": 30, "stated": 50}  # the classic hallucinated +50%
    rep = check_consistency(doc, [_rule(
        id="growth", lhs={"kind": "ref", "path": "stated"}, op="==",
        rhs={"kind": "calc", "fn": "pct_change", "args": [
            {"kind": "ref", "path": "prev"}, {"kind": "ref", "path": "curr"}]})])
    assert rep.broken_rules == ["growth"]
    assert rep.checks[0].rhs_value == -40.0


def test_pct_change_zero_base_is_unevaluable_not_crash():
    doc = {"prev": 0, "curr": 30, "stated": 0}
    rep = check_consistency(doc, [_rule(
        id="growth", lhs={"kind": "ref", "path": "stated"}, op="==",
        rhs={"kind": "calc", "fn": "pct_change", "args": [
            {"kind": "ref", "path": "prev"}, {"kind": "ref", "path": "curr"}]})])
    assert "growth" in rep.unevaluable


# --------------------------- tolerance ---------------------------


def test_abs_tolerance_absorbs_rounding():
    doc = {"a": 100.004, "b": 100}
    strict = check_consistency(doc, [_rule(
        id="t", lhs={"kind": "ref", "path": "a"}, op="==",
        rhs={"kind": "ref", "path": "b"})])
    assert not strict.consistent
    loose = check_consistency(doc, [_rule(
        id="t", lhs={"kind": "ref", "path": "a"}, op="==",
        rhs={"kind": "ref", "path": "b"}, abs_tol=0.01)])
    assert loose.consistent


def test_relative_tolerance():
    doc = {"a": 1010, "b": 1000}
    rep = check_consistency(doc, [_rule(
        id="t", lhs={"kind": "ref", "path": "a"}, op="==",
        rhs={"kind": "ref", "path": "b"}, rel_tol=0.02)])  # 2% of 1000 = 20
    assert rep.consistent


# --------------------------- inequality operators ---------------------------


def test_inequality_ops():
    doc = {"spend": 90, "budget": 100}
    ok = check_consistency(doc, [_rule(
        id="cap", lhs={"kind": "ref", "path": "spend"}, op="<=",
        rhs={"kind": "ref", "path": "budget"})])
    assert ok.consistent
    doc2 = {"spend": 110, "budget": 100}
    bad = check_consistency(doc2, [_rule(
        id="cap", lhs={"kind": "ref", "path": "spend"}, op="<=",
        rhs={"kind": "ref", "path": "budget"})])
    assert bad.broken_rules == ["cap"]


# --------------------------- verify-or-refuse ---------------------------


def test_missing_field_is_unevaluable_not_crash():
    rep = check_consistency({"a": 1}, [_rule(
        id="m", lhs={"kind": "ref", "path": "missing"}, op="==",
        rhs={"kind": "lit", "value": 1})])
    assert not rep.consistent
    assert rep.unevaluable == ["m"]
    assert rep.checks[0].error


def test_non_numeric_field_is_unevaluable():
    rep = check_consistency({"a": "hello"}, [_rule(
        id="n", lhs={"kind": "ref", "path": "a"}, op="==",
        rhs={"kind": "lit", "value": 1})])
    assert "n" in rep.unevaluable


def test_boolean_where_number_expected_is_refused():
    rep = check_consistency({"flag": True}, [_rule(
        id="b", lhs={"kind": "ref", "path": "flag"}, op="==",
        rhs={"kind": "lit", "value": 1})])
    assert "b" in rep.unevaluable


# --------------------------- adversarial / coercion ---------------------------


def test_extra_keys_are_ignored():
    doc = {"x": 5, "junk": {"deep": [1, 2, 3]}, "extra": "noise"}
    rep = check_consistency(doc, [_rule(
        id="x5", lhs={"kind": "ref", "path": "x"}, op="==",
        rhs={"kind": "lit", "value": 5})])
    assert rep.consistent


def test_currency_and_comma_string_coerced_with_note():
    doc = {"fee": "$1,200.00", "cap": 1000}
    rep = check_consistency(doc, [_rule(
        id="fee", lhs={"kind": "ref", "path": "fee"}, op="<=",
        rhs={"kind": "ref", "path": "cap"})])
    assert rep.broken_rules == ["fee"]  # 1200 > 1000
    assert rep.checks[0].lhs_value == 1200.0
    assert any("coerced" in n for n in rep.notes)


def test_accounting_parentheses_are_negative():
    doc = {"net": "(500)"}
    rep = check_consistency(doc, [_rule(
        id="neg", lhs={"kind": "ref", "path": "net"}, op="==",
        rhs={"kind": "lit", "value": -500})])
    assert rep.consistent


def test_casing_mismatch_is_unevaluable():
    # A miscased path must be caught, not silently satisfied.
    rep = check_consistency({"Total": 10}, [_rule(
        id="t", lhs={"kind": "ref", "path": "total"}, op="==",
        rhs={"kind": "lit", "value": 10})])
    assert "t" in rep.unevaluable


def test_nan_and_inf_are_unevaluable():
    import math

    rep = check_consistency(
        {"a": math.nan, "b": math.inf},
        [
            _rule(id="nan", lhs={"kind": "ref", "path": "a"}, op="==",
                  rhs={"kind": "lit", "value": 0}),
            _rule(id="inf", lhs={"kind": "ref", "path": "b"}, op="==",
                  rhs={"kind": "lit", "value": 0}),
        ],
    )
    assert set(rep.unevaluable) == {"nan", "inf"}
    assert not rep.consistent


# --------------------------- report shape / robustness ---------------------------


def test_mixed_report_has_both_broken_and_unevaluable():
    doc = {"a": 5, "b": 6}
    rep = check_consistency(doc, [
        _rule(id="ok", lhs={"kind": "ref", "path": "a"}, op="==",
              rhs={"kind": "lit", "value": 5}),
        _rule(id="broke", lhs={"kind": "ref", "path": "b"}, op="==",
              rhs={"kind": "lit", "value": 99}),
        _rule(id="cant", lhs={"kind": "ref", "path": "z"}, op="==",
              rhs={"kind": "lit", "value": 1}),
    ])
    assert rep.broken_rules == ["broke"]
    assert rep.unevaluable == ["cant"]
    assert not rep.consistent
    assert "3" in rep.summary or "of 3" in rep.summary


def test_accepts_ruleset_object_and_dict_forms():
    doc = {"a": 1}
    rule = {"id": "r", "lhs": {"kind": "ref", "path": "a"}, "op": "==",
            "rhs": {"kind": "lit", "value": 1}}
    assert check_consistency(doc, Ruleset(rules=[Rule.model_validate(rule)])).consistent
    assert check_consistency(doc, {"rules": [rule]}).consistent
    assert check_consistency(doc, [rule]).consistent


def test_invalid_expr_rejected_at_validation():
    with pytest.raises(Exception):
        Expr.model_validate({"kind": "agg", "fn": "sum", "path": "no_wildcard.here"})
    with pytest.raises(Exception):
        Expr.model_validate({"kind": "calc", "fn": "sub", "args": [
            {"kind": "lit", "value": 1}]})  # sub needs 2 args
