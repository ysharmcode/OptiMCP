"""Consistency-checker benchmark.

Two independent measurements:

1. **Model self-violation rate (needs an LLM).** For tasks in the regime the
   research flags as hard - multivariate arithmetic, derived values (growth %,
   margins), long context, and perturbed financials - we ask a capable model for
   structured output and use ``check_consistency`` to measure how often that
   output violates its own stated rules (or the ground truth we handed it).

2. **Checker false-positive rate (no LLM).** We generate many *known-correct*
   documents for the same scenarios and confirm the checker flags exactly zero -
   a checker that cries wolf would be worse than useless.

Usage::

    # false-positive audit only (fast, no API key):
    python consistency_benchmark.py --fp-only

    # full run (LLM self-violation + FP audit):
    setx GEMINI_API_KEY ...     # or OPENROUTER_API_KEY / OPENAI_API_KEY
    python consistency_benchmark.py            # N from PROBE_N (default 8)

Environment: OPTIMCP_MODEL, PROBE_N, PROBE_SLEEP, GEMINI_API_KEY /
OPENROUTER_API_KEY / OPENAI_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from optimcp import check_consistency  # noqa: E402


# ------------------------- tiny expression helpers -------------------------

def ref(p: str) -> dict:
    return {"kind": "ref", "path": p}


def lit(v: float) -> dict:
    return {"kind": "lit", "value": v}


def agg(fn: str, p: str) -> dict:
    return {"kind": "agg", "fn": fn, "path": p}


def calc(fn: str, *args: dict) -> dict:
    return {"kind": "calc", "fn": fn, "args": list(args)}


def rule(id: str, lhs: dict, op: str, rhs: dict, tol: float = 0.01, msg: str = "") -> dict:
    r = {"id": id, "lhs": lhs, "op": op, "rhs": rhs, "abs_tol": tol}
    if msg:
        r["message"] = msg
    return r


@dataclass
class Scenario:
    id: str
    category: str
    prompt: str
    rules: List[dict]
    correct_doc: Dict[str, Any]
    max_tokens: int = 900


# ------------------------------ scenarios ------------------------------

def _money(rng: random.Random, lo: int, hi: int, step: int = 1) -> float:
    return float(rng.randrange(lo, hi, step))


def scn_invoice(rng: random.Random) -> Scenario:
    names = rng.sample(
        ["Consulting", "Design review", "Hosting", "Training", "Support", "Licensing"], 3
    )
    items = []
    for nm in names:
        qty = rng.randint(1, 12)
        price = round(rng.uniform(20, 400), 2)
        items.append({"description": nm, "qty": qty, "unit_price": price,
                      "line_total": round(qty * price, 2)})
    subtotal = round(sum(i["line_total"] for i in items), 2)
    tax_rate = rng.choice([0.05, 0.07, 0.08, 0.10])
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    doc = {"line_items": items, "subtotal": subtotal, "tax_rate": tax_rate,
           "tax": tax, "total": total}

    lines = "\n".join(
        f'- "{i["description"]}", {i["qty"]} units at ${i["unit_price"]:.2f} each'
        for i in items
    )
    prompt = (
        "Produce an invoice as JSON with keys line_items (each: description, qty, "
        "unit_price, line_total), subtotal, tax_rate, tax, total.\n\n"
        f"Items:\n{lines}\n\ntax_rate = {tax_rate}. "
        "line_total = qty*unit_price; subtotal = sum of line_total; "
        "tax = subtotal*tax_rate; total = subtotal+tax. Return ONLY the JSON."
    )
    rules = [rule("subtotal_foots", ref("subtotal"), "==",
                  agg("sum", "line_items[*].line_total"), 0.02,
                  "subtotal must equal sum of line totals"),
             rule("tax_correct", ref("tax"), "==",
                  calc("mul", ref("subtotal"), ref("tax_rate")), 0.02,
                  "tax = subtotal * tax_rate"),
             rule("total_correct", ref("total"), "==",
                  calc("add", ref("subtotal"), ref("tax")), 0.02,
                  "total = subtotal + tax")]
    for idx in range(len(items)):
        rules.append(rule(
            f"line_{idx}_correct", ref(f"line_items[{idx}].line_total"), "==",
            calc("mul", ref(f"line_items[{idx}].qty"),
                 ref(f"line_items[{idx}].unit_price")), 0.02,
            "line_total = qty * unit_price"))
    return Scenario("invoice", "multivariate", prompt, rules, doc)


def scn_budget(rng: random.Random) -> Scenario:
    teams = ["eng", "sales", "mkt", "ops", "hr"]
    total = _money(rng, 1_000_000, 3_000_000, 50_000)
    # random split summing to total, each at least 100k
    mins = 100_000
    remaining = total - mins * len(teams)
    cuts = sorted(rng.uniform(0, remaining) for _ in range(len(teams) - 1))
    alloc, prev = [], 0.0
    for c in list(cuts) + [remaining]:
        alloc.append(round(mins + (c - prev)))
        prev = c
    # fix rounding so they sum exactly
    diff = int(total - sum(alloc))
    alloc[0] += diff
    allocations = [{"team": t, "amount": float(a)} for t, a in zip(teams, alloc)]
    doc = {"total_budget": total, "allocations": allocations}

    prompt = (
        "Allocate a budget as JSON with keys total_budget and allocations (a list "
        f"of {{team, amount}}). total_budget = {int(total)}. Teams: "
        f"{', '.join(teams)}. Every team gets at least {mins}. The amounts MUST "
        "sum to exactly total_budget. Return ONLY the JSON."
    )
    rules = [rule("alloc_sums_to_total", agg("sum", "allocations[*].amount"), "==",
                  ref("total_budget"), 0.5, "allocations must sum to total_budget")]
    for idx in range(len(teams)):
        rules.append(rule(f"team_{idx}_min", ref(f"allocations[{idx}].amount"),
                          ">=", lit(mins), 0.5, "each team >= minimum"))
    return Scenario("budget", "multivariate", prompt, rules, doc)


def scn_growth(rng: random.Random) -> Scenario:
    prev = _money(rng, 20, 200, 5)
    curr = _money(rng, 20, 200, 5)
    growth = float((Decimal(str(curr)) - Decimal(str(prev))) / Decimal(str(prev)) * 100)
    cogs = round(curr * rng.uniform(0.3, 0.7), 1)
    gp = round(curr - cogs, 4)
    margin = float(Decimal(str(gp)) / Decimal(str(curr)) * 100)
    doc = {"prev_revenue": prev, "revenue": curr,
           "revenue_growth_pct": round(growth, 2), "cogs": cogs,
           "gross_profit": gp, "gross_margin_pct": round(margin, 2)}

    prompt = (
        "Return JSON with keys prev_revenue, revenue, revenue_growth_pct, cogs, "
        "gross_profit, gross_margin_pct.\n"
        f"prev_revenue = {prev} (million), revenue = {curr} (million), "
        f"cogs = {cogs} (million).\n"
        "revenue_growth_pct = (revenue - prev_revenue)/prev_revenue*100; "
        "gross_profit = revenue - cogs; gross_margin_pct = "
        "gross_profit/revenue*100. Return ONLY the JSON."
    )
    rules = [
        rule("growth_direction", ref("revenue_growth_pct"), "==",
             calc("pct_change", ref("prev_revenue"), ref("revenue")), 0.1,
             "growth% = (new-old)/old*100"),
        rule("gross_profit_id", ref("gross_profit"), "==",
             calc("sub", ref("revenue"), ref("cogs")), 0.05,
             "gross_profit = revenue - cogs"),
        rule("gross_margin", ref("gross_margin_pct"), "==",
             calc("mul", calc("div", ref("gross_profit"), ref("revenue")), lit(100)),
             0.1, "gross_margin% = gross_profit/revenue*100"),
    ]
    return Scenario("growth", "derived", prompt, rules, doc)


def scn_crossfoot(rng: random.Random) -> Scenario:
    rows = [[rng.randint(1, 40) for _ in range(3)] for _ in range(3)]
    row_totals = [float(sum(r)) for r in rows]
    col_totals = [float(sum(rows[i][j] for i in range(3))) for j in range(3)]
    grand = float(sum(row_totals))
    doc = {"rows": rows, "row_totals": row_totals, "col_totals": col_totals,
           "grand_total": grand}

    grid = "\n".join("  " + ", ".join(str(x) for x in r) for r in rows)
    prompt = (
        "Here is a 3x3 grid of integers (row by row):\n" + grid + "\n\n"
        "Return JSON with keys rows (the 3x3 grid), row_totals (3 row sums), "
        "col_totals (3 column sums), grand_total (sum of all cells). Return ONLY "
        "the JSON."
    )
    rules = [rule("grand_from_rows", ref("grand_total"), "==",
                  agg("sum", "row_totals[*]"), 0.5),
             rule("grand_from_cols", ref("grand_total"), "==",
                  agg("sum", "col_totals[*]"), 0.5)]
    for i in range(3):
        rules.append(rule(f"row_{i}", ref(f"row_totals[{i}]"), "==",
                          agg("sum", f"rows[{i}][*]"), 0.5))
    for j in range(3):
        rules.append(rule(f"col_{j}", ref(f"col_totals[{j}]"), "==",
                          agg("sum", f"rows[*][{j}]"), 0.5))
    return Scenario("crossfoot", "multivariate", prompt, rules, doc)


def scn_longctx(rng: random.Random) -> Scenario:
    vendors = ["Acme", "Globex", "Initech", "Umbrella", "Soylent", "Stark",
               "Wayne", "Wonka", "Cyberdyne", "Hooli"]
    n = rng.randint(18, 26)
    txns = [{"vendor": rng.choice(vendors), "amount": round(rng.uniform(10, 990), 2)}
            for _ in range(n)]
    total = float(round(sum(Decimal(str(t["amount"])) for t in txns), 2))
    mx = max(t["amount"] for t in txns)
    avg = float(round(Decimal(str(total)) / Decimal(n), 2))
    doc = {"transaction_count": n, "total_spend": total, "max_single": mx,
           "average": avg}

    # Bury the numbers in a long narrative to force recombination under context.
    filler = (
        "Below is this month's raw expense log exported from the finance system. "
        "It is deliberately verbose; read carefully. Each line records a single "
        "purchase. Do not skip any line.\n\n"
    )
    body = "\n".join(
        f"On day {i+1}, the team paid {t['vendor']} the sum of ${t['amount']:.2f} "
        f"for miscellaneous operating expenses (ref #{rng.randint(10000,99999)})."
        for i, t in enumerate(txns)
    )
    prompt = (
        filler + body + "\n\n"
        "Now return JSON with keys transaction_count (how many purchases), "
        "total_spend (sum of all amounts), max_single (largest single amount), "
        "average (total_spend / transaction_count, 2 decimals). Return ONLY JSON."
    )
    rules = [
        rule("count_correct", ref("transaction_count"), "==", lit(n), 0.0),
        rule("total_correct", ref("total_spend"), "==", lit(total), 0.02),
        rule("max_correct", ref("max_single"), "==", lit(mx), 0.02),
        rule("avg_correct", ref("average"), "==", lit(avg), 0.02),
    ]
    return Scenario("longctx", "long-context", prompt, rules, doc, max_tokens=400)


def scn_perturbed(rng: random.Random) -> Scenario:
    # Deliberately "unusual" figures so a model cannot pattern-match a memorized
    # statement; it has to actually compute the derived ratios.
    rev_prev = round(rng.uniform(137.3, 981.7), 1)
    rev = round(rng.uniform(137.3, 981.7), 1)
    cogs = round(rev * rng.uniform(0.41, 0.73), 1)
    opex = round(rev * rng.uniform(0.11, 0.29), 1)
    D = Decimal
    yoy = float(round((D(str(rev)) - D(str(rev_prev))) / D(str(rev_prev)) * 100, 2))
    gm = float(round((D(str(rev)) - D(str(cogs))) / D(str(rev)) * 100, 2))
    op_income = float(round(D(str(rev)) - D(str(cogs)) - D(str(opex)), 2))
    om = float(round(D(str(op_income)) / D(str(rev)) * 100, 2))
    doc = {"revenue_prev": rev_prev, "revenue": rev, "cogs": cogs, "opex": opex,
           "yoy_growth_pct": yoy, "gross_margin_pct": gm,
           "operating_income": op_income, "operating_margin_pct": om}

    prompt = (
        "Given this income statement, compute the derived figures and return JSON "
        "with keys revenue_prev, revenue, cogs, opex, yoy_growth_pct, "
        "gross_margin_pct, operating_income, operating_margin_pct.\n"
        f"revenue_prev = {rev_prev}, revenue = {rev}, cogs = {cogs}, opex = {opex} "
        "(all in $M).\n"
        "yoy_growth_pct = (revenue-revenue_prev)/revenue_prev*100; "
        "gross_margin_pct = (revenue-cogs)/revenue*100; "
        "operating_income = revenue-cogs-opex; "
        "operating_margin_pct = operating_income/revenue*100. Return ONLY JSON."
    )
    rules = [
        rule("yoy", ref("yoy_growth_pct"), "==",
             calc("pct_change", ref("revenue_prev"), ref("revenue")), 0.1),
        rule("gm", ref("gross_margin_pct"), "==",
             calc("mul", calc("div", calc("sub", ref("revenue"), ref("cogs")),
                              ref("revenue")), lit(100)), 0.1),
        rule("op_income", ref("operating_income"), "==",
             calc("sub", calc("sub", ref("revenue"), ref("cogs")), ref("opex")),
             0.05),
        rule("op_margin", ref("operating_margin_pct"), "==",
             calc("mul", calc("div", ref("operating_income"), ref("revenue")),
                  lit(100)), 0.1),
    ]
    return Scenario("perturbed", "perturbed", prompt, rules, doc, max_tokens=500)


FACTORIES: List[Callable[[random.Random], Scenario]] = [
    scn_invoice, scn_budget, scn_growth, scn_crossfoot, scn_longctx, scn_perturbed,
]


# ------------------------- false-positive audit -------------------------

def fp_audit(trials: int = 200) -> Dict[str, Any]:
    """Run the checker on known-correct documents; expect zero flags."""
    rng = random.Random(20260722)
    per_cat: Dict[str, List[int]] = {}
    false_positives = 0
    total = 0
    offenders: List[str] = []
    for _ in range(trials):
        for fac in FACTORIES:
            sc = fac(rng)
            rep = check_consistency(sc.correct_doc, sc.rules)
            total += 1
            per_cat.setdefault(sc.id, [0, 0])
            per_cat[sc.id][1] += 1
            if not rep.consistent:
                false_positives += 1
                per_cat[sc.id][0] += 1
                if len(offenders) < 10:
                    offenders.append(f"{sc.id}: {rep.summary}")
    return {"total": total, "false_positives": false_positives,
            "per_category": per_cat, "offenders": offenders}


# ------------------------------ LLM plumbing ------------------------------

_GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"


def make_client():
    from openai import OpenAI
    model = os.getenv("OPTIMCP_MODEL")
    gem = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gem:
        return OpenAI(api_key=gem, base_url=_GEMINI), model or "gemini-flash-lite-latest"
    if os.getenv("OPENROUTER_API_KEY"):
        return (OpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                       base_url="https://openrouter.ai/api/v1"),
                model or "openai/gpt-4o-mini")
    if os.getenv("OPENAI_API_KEY"):
        return OpenAI(), model or "gpt-4o-mini"
    raise SystemExit("Set GEMINI_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY.")


def call(client, model, prompt, max_tokens, retries=4):
    for attempt in range(retries):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Return only valid JSON. Compute every figure carefully."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=max_tokens,
            )
            c = r.choices[0].message.content if r.choices else None
            if c:
                return c
            time.sleep(2.0 * (attempt + 1))
        except Exception as exc:
            msg = str(exc)
            if "PerDay" in msg or "RequestsPerDay" in msg:
                return f"__DAILYCAP__ {msg[:140]}"
            if attempt == retries - 1:
                return f"__ERROR__ {msg[:140]}"
            time.sleep(12.0 if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else 2.0)
    return None


def extract_json(text: str):
    if not text or text.startswith("__"):
        return None
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        return json.loads(text[s:e + 1])
    except Exception:
        return None


def llm_run(n: int) -> Dict[str, Any]:
    client, model = make_client()
    sleep = float(os.getenv("PROBE_SLEEP", "4.5"))
    rng = random.Random(7)  # fixed scenarios so prompts/rules are stable
    scenarios = [fac(rng) for fac in FACTORIES]
    print(f"model = {model}   N = {n}\n", flush=True)
    print(f"{'scenario':12} {'category':13} | {'runs':>4} {'parseFail':>9} "
          f"{'selfViol':>8} {'viol%':>6} | top broken", flush=True)
    print("-" * 96, flush=True)

    results = {"model": model, "n": n, "scenarios": {}}
    cat_tot: Dict[str, List[int]] = {}
    for sc in scenarios:
        parsefail = viol = 0
        broken_counter: Dict[str, int] = {}
        for _ in range(n):
            txt = call(client, model, sc.prompt, sc.max_tokens)
            doc = extract_json(txt or "")
            if doc is None:
                parsefail += 1
                continue
            rep = check_consistency(doc, sc.rules)
            if not rep.consistent:
                viol += 1
                for b in rep.broken_rules + rep.unevaluable:
                    broken_counter[b] = broken_counter.get(b, 0) + 1
            time.sleep(sleep)
        evaluated = n - parsefail
        rate = 100.0 * viol / evaluated if evaluated else 0.0
        top = ", ".join(f"{k}({v})" for k, v in
                        sorted(broken_counter.items(), key=lambda x: -x[1])[:3])
        print(f"{sc.id:12} {sc.category:13} | {n:>4} {parsefail:>9} {viol:>8} "
              f"{rate:>5.0f}% | {top}", flush=True)
        results["scenarios"][sc.id] = {
            "category": sc.category, "runs": n, "parse_fail": parsefail,
            "self_violations": viol, "rate_pct": round(rate, 1),
            "top_broken": broken_counter,
        }
        cat_tot.setdefault(sc.category, [0, 0])
        cat_tot[sc.category][0] += viol
        cat_tot[sc.category][1] += evaluated

    print("-" * 96, flush=True)
    tv = tr = 0
    for cat, (v, r) in cat_tot.items():
        tv += v
        tr += r
        print(f"{cat:26} self-violation: {100.0*v/r if r else 0:.0f}%  ({v}/{r})",
              flush=True)
    print(f"{'OVERALL':26} self-violation: {100.0*tv/tr if tr else 0:.0f}%  ({tv}/{tr})",
          flush=True)
    results["overall"] = {"violations": tv, "evaluated": tr,
                          "rate_pct": round(100.0 * tv / tr, 1) if tr else 0.0}
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fp-only", action="store_true", help="Only run the FP audit (no LLM).")
    ap.add_argument("--out", default=None, help="Write JSON results here.")
    args = ap.parse_args()

    print("=== False-positive audit (deterministic, no LLM) ===", flush=True)
    fp = fp_audit()
    print(f"known-correct documents checked : {fp['total']}", flush=True)
    print(f"false positives                 : {fp['false_positives']}", flush=True)
    if fp["offenders"]:
        for o in fp["offenders"]:
            print("  FP:", o, flush=True)
    print("", flush=True)

    out = {"false_positive_audit": fp}
    if not args.fp_only:
        print("=== Model self-violation (LLM) ===", flush=True)
        out["llm"] = llm_run(int(os.getenv("PROBE_N", "8")))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"\nWrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
