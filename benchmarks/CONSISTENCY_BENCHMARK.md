# Consistency-checker benchmark

Two questions, measured separately and honestly:

1. **Does a capable model actually emit self-inconsistent numbers** — output that
   violates its *own* stated rules — and *where*?
2. **Can the checker be trusted** — i.e. does it ever flag a document that is in
   fact correct?

The point of OptiMCP is a deterministic, independent verdict. So the headline is
not "LLMs are bad at math everywhere" (they aren't — see below); it is that the
failures are **concentrated and predictable**, and that a deterministic checker
catches them with **zero false positives**.

## Setup

- **Model (self-violation):** `gemini-flash-lite-latest`, `temperature=0.4`,
  **N=20** generations per scenario (120 generations total).
- **Checker:** `optimcp.check_consistency` — no LLM, exact `Decimal` arithmetic.
  The *same* declared rules are used to (a) audit correctness and (b) generate
  known-correct documents for the false-positive test.
- **Scenarios** span the regimes the 2025–2026 literature flags as hard:
  multivariate arithmetic, derived values, cross-footing, long context, and
  perturbed financials.
- Reproduce: `python benchmarks/consistency_benchmark.py`
  (add `--fp-only` for the no-API-key audit). Raw output:
  [`consistency_results.json`](consistency_results.json).

## Result 1 — checker false-positive rate (no LLM)

For every scenario we generate **200 randomized, known-correct documents** and
run the checker over them. A correct document must produce zero violations, or
the checker cries wolf.

| Documents checked | False positives |
|---:|---:|
| **1200** | **0** |

**0 / 1200.** Across all six scenario types, the checker never flags a correct
document. (Note the checker is conservative by design: a rule it *cannot*
evaluate — missing or non-numeric field — counts as a failure, not a pass, so
the direction of any error is toward reporting, never toward hiding.)

## Result 2 — model self-violation rate (LLM), N=20

How often does the model's output break its own stated rules?

| Scenario | Category | Runs | Self-violations | Rate | Rules that broke |
|---|---|---:|---:|---:|---|
| invoice | multivariate | 20 | 0 | **0%** | — |
| budget | multivariate | 20 | 0 | **0%** | — |
| growth | derived | 20 | 0 | **0%** | — |
| crossfoot | multivariate | 20 | 0 | **0%** | — |
| perturbed | perturbed | 20 | 0 | **0%** | — |
| **longctx** | **long-context** | 20 | **20** | **100%** | `total_correct` (20), `avg_correct` (20) |

By category:

| Category | Self-violation rate |
|---|---:|
| multivariate (invoice, budget, crossfoot) | 0% (0/60) |
| derived (growth) | 0% (0/20) |
| perturbed financials | 0% (0/20) |
| **long-context aggregation** | **100% (20/20)** |
| **Overall** | 17% (20/120) |

## Reading this honestly

- **On short, self-contained tasks, a capable model is reliable.** Invoices that
  foot, tax chains, growth-direction, gross margins, 3×3 cross-footing, and
  perturbed income statements: **0 violations in 100 generations.** OptiMCP does
  not pretend otherwise. If your numbers fit in one clean prompt, the model
  probably gets them right.

- **The failure is specific and total in long context.** When the same model has
  to sum ~24 dollar amounts scattered through a long expense log, it gets the
  **total wrong every single time (20/20)** — and, because the average is derived
  from the total, that breaks too. Tellingly, it still gets `count` and
  `max_single` right: it can *see* the data, it just can't *aggregate* it
  reliably. This is exactly the "collapses on multivariate calculation under
  context" mode the research describes.

- **This is the case for an external checker.** The model cannot self-detect this
  error (it produced a confident, well-formatted wrong total). A deterministic
  recomputation catches 100% of the failures with 0 false positives. That gap —
  100% caught vs. 0% self-caught — is the product.

## Caveats

- One model, one temperature. The **pattern** (short tasks fine; long-context
  aggregation fails) is robust and predicted by the literature; the exact rate on
  other models/tasks will differ. The long-context 20/20 and the 0/1200
  false-positive results are strong enough to state plainly.
- `longctx` and `perturbed` compare the model's numbers against ground truth we
  computed from the data we handed it; the other scenarios check the document's
  *internal* consistency. Both are legitimate "does the output obey the rules"
  measurements.
