"""Self-contained: catch the classic financial-report arithmetic failures.

No API key needed. This shows the two failure modes the research literature
flags as structural for LLMs - a wrongly-directed growth percentage, and a table
that does not cross-foot - and how the deterministic checker names exactly which
rule broke, with the delta.

    python check_financial_report.py
"""

from optimcp import check_consistency

# A quarterly summary an LLM might emit. Two numbers are wrong on purpose:
#   * revenue fell 50 -> 30, i.e. -40%, but the report states +50% (wrong sign,
#     the exact "50M to 30M answered 50%" failure from the interpretability work);
#   * the segment revenues (18 + 9 + 5 = 32) do not add up to the stated
#     total_revenue of 30 (a cross-footing / does-the-total-match error).
REPORT = {
    "period": "Q3 2026",
    "prev_revenue": 50.0,
    "total_revenue": 30.0,
    "revenue_growth_pct": 50.0,           # WRONG: should be -40
    "segments": [
        {"name": "Cloud", "revenue": 18.0},
        {"name": "Devices", "revenue": 9.0},
        {"name": "Services", "revenue": 5.0},   # 18+9+5 = 32, not 30
    ],
    "cogs": 12.0,
    "gross_profit": 18.0,                 # 30 - 12 = 18 -> correct
    "gross_margin_pct": 60.0,             # 18/30*100 = 60 -> correct
}

RULES = [
    {
        "id": "growth_direction",
        "lhs": {"kind": "ref", "path": "revenue_growth_pct"},
        "op": "==",
        "rhs": {"kind": "calc", "fn": "pct_change", "args": [
            {"kind": "ref", "path": "prev_revenue"},
            {"kind": "ref", "path": "total_revenue"}]},
        "abs_tol": 0.05,
        "message": "growth% = (new - old) / old * 100",
    },
    {
        "id": "segments_foot_to_total",
        "lhs": {"kind": "ref", "path": "total_revenue"},
        "op": "==",
        "rhs": {"kind": "agg", "fn": "sum", "path": "segments[*].revenue"},
        "abs_tol": 0.005,
        "message": "segment revenues must sum to total_revenue",
    },
    {
        "id": "gross_profit_identity",
        "lhs": {"kind": "ref", "path": "gross_profit"},
        "op": "==",
        "rhs": {"kind": "calc", "fn": "sub", "args": [
            {"kind": "ref", "path": "total_revenue"},
            {"kind": "ref", "path": "cogs"}]},
        "abs_tol": 0.005,
        "message": "gross_profit = total_revenue - cogs",
    },
    {
        "id": "gross_margin",
        "lhs": {"kind": "ref", "path": "gross_margin_pct"},
        "op": "==",
        "rhs": {"kind": "calc", "fn": "mul", "args": [
            {"kind": "calc", "fn": "div", "args": [
                {"kind": "ref", "path": "gross_profit"},
                {"kind": "ref", "path": "total_revenue"}]},
            {"kind": "lit", "value": 100}]},
        "abs_tol": 0.05,
        "message": "gross_margin% = gross_profit / total_revenue * 100",
    },
]


def main() -> None:
    report = check_consistency(REPORT, RULES)
    print(f"Auditing financial report for {REPORT['period']} "
          f"({len(RULES)} rules, deterministic, no LLM)\n")
    for c in report.checks:
        mark = "ok " if c.passed else "XX "
        print(f"  [{mark}] {c.detail}")
    print(f"\n  consistent  : {report.consistent}")
    print(f"  broken      : {report.broken_rules}")
    print(f"  SUMMARY     : {report.summary}")


if __name__ == "__main__":
    main()
