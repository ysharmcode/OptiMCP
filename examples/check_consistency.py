"""Real end-to-end: an LLM drafts an invoice, OptiMCP checks its arithmetic.

This is the actual product experience. A live model is asked to produce a
structured invoice (line items, subtotal, tax, total) - a multivariate
arithmetic task, exactly the regime where LLMs quietly get numbers wrong. We
then run ``check_consistency`` with a handful of declared rules and it tells us,
deterministically and with no LLM, whether the model's own output obeys its own
stated rules - and if not, *which rule broke*, with the delta.

Run it:

    # OpenAI:
    setx OPENAI_API_KEY sk-...        # then open a new shell
    python check_consistency.py

    # or Gemini / OpenRouter (OpenAI-compatible):
    setx GEMINI_API_KEY ...
    setx OPENROUTER_API_KEY sk-or-...

Optionally override the model with OPTIMCP_MODEL.
"""

import json
import os

from openai import OpenAI

from optimcp import check_consistency

USER_PROMPT = """\
Create an invoice as a JSON object with EXACTLY this shape:

{
  "line_items": [{"description": "...", "qty": <int>, "unit_price": <number>,
                  "line_total": <number>}, ...],
  "subtotal": <number>,
  "tax_rate": 0.08,
  "tax": <number>,
  "total": <number>
}

Line items to bill:
- "Consulting", 12 hours at $145.00/hour
- "Design review", 3 units at $220.00 each
- "Hosting (annual)", 1 unit at $1,199.00

Rules you must follow: each line_total = qty * unit_price; subtotal = sum of all
line_total; tax = subtotal * tax_rate; total = subtotal + tax. Reply with ONLY
the JSON object, no prose.
"""

SYSTEM_PROMPT = (
    "You produce precise structured financial data. Compute every figure "
    "carefully and return valid JSON only."
)

# Declared, deterministic rules - the contract the invoice must satisfy.
RULES = [
    {
        "id": "line_totals_correct",
        # every line_total == qty * unit_price  ->  sum(line_total) == sum(qty*unit_price)
        "lhs": {"kind": "agg", "fn": "sum", "path": "line_items[*].line_total"},
        "op": "==",
        "rhs": {
            "kind": "calc", "fn": "add", "args": [
                {"kind": "calc", "fn": "mul", "args": [
                    {"kind": "ref", "path": "line_items[0].qty"},
                    {"kind": "ref", "path": "line_items[0].unit_price"}]},
                {"kind": "calc", "fn": "mul", "args": [
                    {"kind": "ref", "path": "line_items[1].qty"},
                    {"kind": "ref", "path": "line_items[1].unit_price"}]},
                {"kind": "calc", "fn": "mul", "args": [
                    {"kind": "ref", "path": "line_items[2].qty"},
                    {"kind": "ref", "path": "line_items[2].unit_price"}]},
            ],
        },
        "abs_tol": 0.005,
        "message": "sum of line totals must equal sum of qty * unit_price",
    },
    {
        "id": "subtotal_foots",
        "lhs": {"kind": "ref", "path": "subtotal"},
        "op": "==",
        "rhs": {"kind": "agg", "fn": "sum", "path": "line_items[*].line_total"},
        "abs_tol": 0.005,
        "message": "subtotal must equal the sum of line totals",
    },
    {
        "id": "tax_correct",
        "lhs": {"kind": "ref", "path": "tax"},
        "op": "==",
        "rhs": {"kind": "calc", "fn": "mul", "args": [
            {"kind": "ref", "path": "subtotal"}, {"kind": "ref", "path": "tax_rate"}]},
        "abs_tol": 0.005,
        "message": "tax must equal subtotal * tax_rate",
    },
    {
        "id": "total_correct",
        "lhs": {"kind": "ref", "path": "total"},
        "op": "==",
        "rhs": {"kind": "calc", "fn": "add", "args": [
            {"kind": "ref", "path": "subtotal"}, {"kind": "ref", "path": "tax"}]},
        "abs_tol": 0.005,
        "message": "total must equal subtotal + tax",
    },
]


def make_client():
    """Return (client, model): OpenAI, Gemini (OpenAI-compat), or OpenRouter."""
    model = os.getenv("OPTIMCP_MODEL")
    if os.getenv("OPENAI_API_KEY"):
        return OpenAI(), model or "gpt-4o-mini"
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        return (
            OpenAI(api_key=gemini_key,
                   base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
            model or "gemini-flash-lite-latest",
        )
    if os.getenv("OPENROUTER_API_KEY"):
        return (
            OpenAI(api_key=os.environ["OPENROUTER_API_KEY"],
                   base_url="https://openrouter.ai/api/v1"),
            model or "openai/gpt-4o-mini",
        )
    raise SystemExit("Set OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY.")


def extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise SystemExit(f"Model did not return JSON:\n{text}")
    return json.loads(text[start:end + 1])


def main() -> None:
    client, model = make_client()
    print(f"[model] {model}\n")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        temperature=0.2,
        max_tokens=800,
    )
    invoice = extract_json(resp.choices[0].message.content or "")
    print("[LLM -> document] the invoice the model produced:")
    print(json.dumps(invoice, indent=2))

    report = check_consistency(invoice, RULES)
    print("\n[checker -> verdict] (deterministic, no LLM):")
    print(f"  consistent   : {report.consistent}")
    for c in report.checks:
        print(f"  - {c.detail}")
    if report.notes:
        print("  notes:")
        for n in report.notes:
            print(f"    * {n}")
    print(f"\n  SUMMARY: {report.summary}")
    if report.consistent:
        print("\nThe model's arithmetic checks out this time. Run again - it won't always.")
    else:
        print("\nCaught it: the model's own output violates its own stated rules.")


if __name__ == "__main__":
    main()
