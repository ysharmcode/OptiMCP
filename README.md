<p align="center">
  <strong>OptiMCP</strong> — a consistency checker that can't lie about the numbers
</p>

<p align="center">
  <a href="https://pypi.org/project/optimcp/"><img alt="PyPI" src="https://img.shields.io/pypi/v/optimcp.svg?v=2"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-BUSL--1.1-green.svg"></a>
  <img alt="MCP" src="https://img.shields.io/badge/MCP-compatible-8A2BE2.svg">
</p>

**Give any AI agent (Claude, GPT, LangChain, …) a tool that checks whether its own structured output actually obeys the rules — and *provably tells you which rule broke*, with the computed value, the expected value, and the delta.**

LLMs are fluent but structurally bad at *preserving arithmetic and logical invariants*. They read a single number fine, then fall apart the moment several numbers have to combine under a rule: a total that doesn't match its line items, a growth rate computed with the wrong sign, an allocation that doesn't add up to the budget, a table that doesn't cross-foot. Worse, a model **cannot reliably audit its own arithmetic** — the same machinery that made the mistake is the one you'd be asking to catch it.

OptiMCP is the independent auditor. You hand `check_consistency` a JSON document and a set of **declared rules**, and it recomputes every rule from scratch — **no LLM, exact decimal arithmetic** — then reports exactly which rules held, which broke (with the delta), and which couldn't even be evaluated. It never silently skips a rule, and it never crashes on bad data.

```mermaid
flowchart LR
  Agent["LLM / agent"] -->|"document + declared rules"| Check["check_consistency"]
  Check --> Eval["Deterministic evaluator (Decimal, no LLM)"]
  Eval --> Report["Report: which rule broke, computed vs expected, delta"]
  Report -.->|"if broken and linear"| Solve["solve_decision (optional repair)"]
```

---

## Why this exists

A 2025–2026 research thread has converged on a clear, uncomfortable finding: LLMs operate as probabilistic next-token predictors, not arithmetic engines — they *simulate the syntax of calculation without preserving its mathematical invariants*. Concretely:

- **Accuracy collapses exactly where it matters.** Benchmarks show top models scoring ~95%+ on single-number lookups but falling toward **near-zero on multivariate calculations** — the moment several numbers must be combined under a rule (the "does this total match its line items?" mode).
- **Models can't be their own auditor.** LLMs cannot reliably detect their own reasoning errors, which is the whole justification for an *independent* verifier rather than an LLM-judge.
- **The errors are structural, not noise.** Mechanistic work frames the classic "revenue fell 50→30, model says +50% instead of −40%" as a *systematically broken computational circuit*, not an occasional slip.
- **In deterministic domains, "mostly right" is worthless.** One wrong number invalidates a whole report for a human reviewer — a 99% per-figure accuracy can mean ~0% operational trust. That is why a hard *verify-or-refuse* layer has real value.

This isn't finance-only. Anywhere an agent emits **numbers or facts subject to rules** — reporting, compliance, operations, scheduling, invoicing, analytics — the same reliability gap applies. OptiMCP is the deterministic external check that closes it.

---

## Why agents use OptiMCP

| You want… | OptiMCP gives you… |
|---|---|
| To catch output that violates its own stated rules | `check_consistency(document, rules)` → exactly which rule broke, with the delta |
| A check an LLM cannot fake | No LLM inside; every number recomputed independently in exact `Decimal` |
| To never be lied to by silence | A rule it can't evaluate (missing/non-numeric field) is reported as **failed**, never skipped |
| Real arithmetic, not float slop | `Decimal` end-to-end — money, tax and % chains don't drift |
| To catch derived-value mistakes | `pct_change`, ratios, margins, aggregations over arrays, cross-footing |
| To wire it into any stack | MCP server, OpenAI/Anthropic function schema, LangChain tool |
| A corrected answer when it makes sense | `solve_decision` — an optional repair/optimization engine for linear numeric problems |

OptiMCP is **not** an LLM wrapper or a general planner. It is a **deterministic checker with an independent-verification core**. The guarantee is that the verdict for each rule is computed correctly and independently — not that your rules capture everything you *meant* (see [What "guaranteed" means](#what-guaranteed-means-honestly)).

---

## Table of contents

1. [Install](#install)
2. [60-second quickstart](#60-second-quickstart)
3. [Add it to your agent](#add-it-to-your-agent)
4. [The rule language](#the-rule-language)
5. [The report payload](#the-report-payload)
6. [What it catches (worked example)](#what-it-catches-worked-example)
7. [How it works](#how-it-works)
8. [Does it actually help? (benchmark)](#does-it-actually-help-benchmark)
9. [What "guaranteed" means (honestly)](#what-guaranteed-means-honestly)
10. [Optional: repair a broken answer](#optional-repair-a-broken-answer)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)
13. [Repository layout](#repository-layout)
14. [License](#license)

---

## Install

**Requirements**

- Python **3.10+**
- The checker itself is pure Python + Pydantic. The optional repair engine uses Google OR-Tools CP-SAT and D-Wave `dwave-samplers` — pure-CPU wheels that install automatically from PyPI on Windows/macOS/Linux. No GPU, no CUDA, no WSL.

**PyPI**

```bash
pip install optimcp
```

**Extras**

```bash
pip install "optimcp[langchain]"  # LangChain StructuredTool adapters
pip install "optimcp[dev]"        # pytest for the test suite
```

**Source checkout**

```bash
git clone https://github.com/ProfessionalQwerty/OptiMCP.git
cd OptiMCP
pip install -e ".[dev]"
```

This installs:

| Command / module | Purpose |
|---|---|
| `optimcp` | Launches the MCP stdio server (`check_consistency`, `solve_decision`, `verify_solution`, `capabilities`) |
| `import optimcp` | `check_consistency`, `Rule`, `Ruleset`, report models (and the solver API) |
| `optimcp.schemas` | OpenAI / Anthropic function-tool JSON schema export |
| `optimcp.adapters.langchain` | LangChain `StructuredTool` wrappers |

---

## 60-second quickstart

**Call it directly in Python:**

```python
from optimcp import check_consistency

# A document an LLM produced (an invoice). Two numbers are wrong.
invoice = {
    "line_items": [{"amount": 100}, {"amount": 120}, {"amount": 110}],
    "subtotal": 320,        # WRONG: the items sum to 330
    "tax": 25.6,
    "total": 345.6,         # WRONG vs subtotal + tax
}

rules = [
    {"id": "subtotal_foots",
     "lhs": {"kind": "ref", "path": "subtotal"}, "op": "==",
     "rhs": {"kind": "agg", "fn": "sum", "path": "line_items[*].amount"}},
    {"id": "total_correct",
     "lhs": {"kind": "ref", "path": "total"}, "op": "==",
     "rhs": {"kind": "calc", "fn": "add",
             "args": [{"kind": "ref", "path": "subtotal"},
                      {"kind": "ref", "path": "tax"}]}},
]

report = check_consistency(invoice, rules)
print(report.consistent)      # False
print(report.broken_rules)    # ['subtotal_foots']
print(report.summary)
# 1 of 2 rule(s) VIOLATED: subtotal_foots: 320 == 330: VIOLATED (off by 10)
```

**Or as an MCP server (Claude Desktop, Cursor, any MCP client).** The `optimcp` command speaks MCP over stdio. Add it to your client config (see [`examples/mcp_config.json`](examples/mcp_config.json)):

```json
{
  "mcpServers": {
    "optimcp": { "command": "optimcp", "args": [] }
  }
}
```

Your agent now has: `check_consistency`, `solve_decision`, `verify_solution`, `capabilities`.

---

## Add it to your agent

### OpenAI / Anthropic function calling

```python
from optimcp.schemas import openai_tool, anthropic_tool   # -> check_consistency
from optimcp import check_consistency

tools = [openai_tool()]           # or [anthropic_tool()]

def dispatch(name, arguments):    # call this from your tool-call loop
    if name == "check_consistency":
        return check_consistency(arguments["document"], arguments["rules"]).model_dump()
```

Full, runnable example (a live model drafts an invoice, OptiMCP audits its arithmetic): [`examples/check_consistency.py`](examples/check_consistency.py).

### LangChain / LangGraph

```python
from optimcp.adapters.langchain import build_check_consistency_tool

tool = build_check_consistency_tool()   # a StructuredTool; pass to tools=[...]
```

Requires `pip install "optimcp[langchain]"`.

---

## The rule language

A **rule** asserts `lhs <op> rhs` (within tolerance), where each side is an **expression** over the document. Rules are pure data — no natural language, no LLM — which is exactly what makes the verdict deterministic.

### Operators

`==` `!=` `<=` `>=` `<` `>` — compared in exact `Decimal` arithmetic with a per-rule tolerance (`abs_tol` default `1e-6`, plus optional `rel_tol` × |rhs|).

### Expressions (`Expr`)

| `kind` | Fields | Meaning |
|---|---|---|
| `lit` | `value` | A literal number |
| `ref` | `path` | One field, by path: `"invoice.total"`, `"line_items[0].amount"` |
| `agg` | `fn`, `path` | Aggregate over a wildcard path: `sum`/`avg`/`min`/`max`/`count` of `"line_items[*].amount"` |
| `calc` | `fn`, `args` | Arithmetic over sub-expressions |

**`calc` functions:** `add`, `sub`, `mul`, `div`, `neg`, `abs`, `round` (2nd arg literal), `pow`, and `pct_change(old, new)` = `(new − old) / old × 100`.

### Paths

Dot paths with `[i]` indexing and `[*]` wildcards. Wildcards may branch: `rows[*][0]` collects the first cell of every row (useful for column totals). Wildcards are only allowed inside an `agg` path.

### A rule, fully spelled out

```python
# "total must equal subtotal + tax"
{
  "id": "total_correct",
  "lhs": {"kind": "ref", "path": "total"},
  "op": "==",
  "rhs": {"kind": "calc", "fn": "add",
          "args": [{"kind": "ref", "path": "subtotal"},
                   {"kind": "ref", "path": "tax"}]},
  "abs_tol": 0.005,
  "message": "total = subtotal + tax"
}
```

### Numbers in strings

Values like `"$1,200.00"`, `"(500)"` (accounting-negative), `"40%"` and `"1.2m"` are normalized to numbers — and **every non-trivial coercion is reported** in `notes`, because a silently "fixed" unit is precisely the transcription bug this tool exists to surface.

---

## The report payload

`check_consistency` returns a `ConsistencyReport`:

| Field | Type | Meaning |
|---|---|---|
| `consistent` | bool | True iff every rule was evaluable **and** held |
| `checks` | list[`RuleCheck`] | Per-rule verdict (below) |
| `broken_rules` | list[str] | Ids of rules that were evaluated and **VIOLATED** |
| `unevaluable` | list[str] | Ids of rules that couldn't be evaluated (missing/non-numeric field) |
| `summary` | str | One-line human summary |
| `notes` | list[str] | All string/unit coercions applied, de-duplicated |

Each `RuleCheck`:

| Field | Type | Meaning |
|---|---|---|
| `id` | str | The rule's id |
| `passed` | bool | Held within tolerance |
| `lhs_value`, `rhs_value` | float? | Independently computed sides (`None` if unevaluable) |
| `delta` | float? | `lhs − rhs` |
| `tolerance` | float | Effective tolerance used |
| `detail` | str | e.g. `"total: 345.6 == 355.6: VIOLATED (off by 10)"` |
| `missing` | list[str] | Field paths that were absent/non-numeric |
| `error` | str? | Why the rule couldn't be evaluated |

**Verify-or-refuse:** a rule that references a missing or non-numeric field is reported as `unevaluable` (and `consistent` is `False`) — never silently treated as satisfied.

---

## What it catches (worked example)

The two failure modes the literature calls *structural* for LLMs — a wrongly-directed growth percentage and a table that doesn't cross-foot — caught deterministically ([`examples/check_financial_report.py`](examples/check_financial_report.py), no API key needed):

```text
Auditing financial report for Q3 2026 (4 rules, deterministic, no LLM)

  [XX ] growth_direction: 50 == -40: VIOLATED (off by 90) - growth% = (new - old) / old * 100
  [XX ] segments_foot_to_total: 30 == 32: VIOLATED (off by 2) - segment revenues must sum to total_revenue
  [ok ] gross_profit_identity: 18 == 18: SATISFIED - gross_profit = total_revenue - cogs
  [ok ] gross_margin: 60 == 60: SATISFIED - gross_margin% = gross_profit / total_revenue * 100

  consistent  : False
  broken      : ['growth_direction', 'segments_foot_to_total']
```

The revenue fell 50 → 30 (−40%) but the report claimed +50% — the exact "50M to 30M answered 50%" failure — and the segment revenues (18+9+5=32) don't match the stated total of 30. Both are named, with the delta.

---

## How it works

1. Each rule's two sides are evaluated **independently** by a small deterministic interpreter over the JSON document. There is no LLM anywhere in this path.
2. All arithmetic runs in Python's `decimal.Decimal` at high precision, so tax/percentage/total chains do not accumulate binary-float error.
3. Field access is explicit and case-sensitive. A missing key, an out-of-range index, a non-numeric value, or a boolean-where-a-number-belongs makes the rule **unevaluable** — reported, never crashed, never assumed satisfied.
4. String values are normalized (commas, currency symbols, accounting parentheses, `k`/`m`/`b` suffixes, trailing `%`) and every coercion is recorded so unit-transcription bugs surface instead of hiding.

That independence is the whole point: it is the check an LLM's own reasoning cannot provide for itself.

---

## Does it actually help? (benchmark)

Two things measured separately, and reported honestly.

**1. Is the checker trustworthy?** We generate **1200 known-correct documents** across six scenario types and check them. A correct document must produce zero violations:

| Known-correct documents checked | False positives |
|---:|---:|
| **1200** | **0** |

**2. Does a capable model emit self-inconsistent numbers — and where?** A capable model (`gemini-flash-lite-latest`, N=20 per scenario, 120 generations) produces structured output; the checker measures how often that output breaks its own stated rules:

| Scenario | Category | Self-violation rate |
|---|---|:---:|
| invoice / budget / crossfoot | multivariate | **0%** (0/60) |
| growth | derived | **0%** (0/20) |
| perturbed income statement | perturbed | **0%** (0/20) |
| **long-context aggregation** (sum ~24 amounts buried in a long log) | long-context | **100%** (20/20) |

The finding is specific and honest: **on short, self-contained tasks a capable model is reliable** — OptiMCP doesn't pretend otherwise. But the moment it has to **aggregate many numbers scattered through a long context**, it gets the total wrong *every single time* (while still counting the items and finding the max correctly — it can *see* the data, it just can't reliably *combine* it). That is exactly the "collapses on multivariate calculation under context" mode the research describes, and it is precisely what the model **cannot self-detect**. The deterministic checker catches 100% of these with 0 false positives — that gap is the product.

Full methodology and numbers: [`benchmarks/CONSISTENCY_BENCHMARK.md`](benchmarks/CONSISTENCY_BENCHMARK.md). Reproduce:

```bash
# deterministic false-positive audit (no API key):
python benchmarks/consistency_benchmark.py --fp-only

# full run (LLM self-violation + FP audit):
setx GEMINI_API_KEY ...     # or OPENROUTER_API_KEY / OPENAI_API_KEY
python benchmarks/consistency_benchmark.py
```

---

## What "guaranteed" means (honestly)

- **Guaranteed:** for each rule, the verdict (held / violated / unevaluable) is computed **correctly and independently** of whatever produced the document, in exact arithmetic. A false "consistent" cannot come from float drift, a silently skipped rule, or a missing field.
- **Scope:** the checker verifies the rules you *wrote down*, not the ones you *meant*. If you forget to declare "segments must sum to total," it won't invent it. Declare the invariants that matter; the report echoes each one back.
- **Not claimed:** that your ruleset is complete, or that a `consistent` document is "correct" in some larger sense — only that it satisfies the stated rules.
- **False positives:** the checker is audited against known-correct documents and flags zero of them (see the benchmark). It errs toward *reporting* problems (unevaluable rules count as failures), never toward hiding them.

---

## Optional: repair a broken answer

Detecting the break is the product. Sometimes you also want a corrected answer. When (and only when) your rules are **linear over scalar fields**, OptiMCP can reduce them to a solvable spec and hand it to a solver that returns an independently-verified fix:

```python
from optimcp.check.rules import Ruleset, Rule
from optimcp.check.repair import try_repair

rules = Ruleset(rules=[
    Rule.model_validate({"id": "sum", "op": "==", "rhs": {"kind": "lit", "value": 10},
        "lhs": {"kind": "calc", "fn": "add",
                "args": [{"kind": "ref", "path": "a"}, {"kind": "ref", "path": "b"}]}}),
    Rule.model_validate({"id": "diff", "op": "==", "rhs": {"kind": "lit", "value": 2},
        "lhs": {"kind": "calc", "fn": "sub",
                "args": [{"kind": "ref", "path": "a"}, {"kind": "ref", "path": "b"}]}}),
])

# You supply the variable domains + what to optimize (the rules alone don't say).
fixed = try_repair(
    rules,
    variables=[{"name": "a", "kind": "integer", "lb": 0, "ub": 10},
               {"name": "b", "kind": "integer", "lb": 0, "ub": 10}],
    objective={"sense": "maximize", "terms": [{"vars": ["a"]}]},
)
print(fixed.assignment)   # {'a': 6, 'b': 4}   (a+b=10, a-b=2), independently verified
```

Anything outside the linear-scalar subset (aggregations, division by a variable, products of two fields) returns `None` — OptiMCP reports the violation and refuses to guess. The underlying solver runs two independent engines (OR-Tools CP-SAT for exact answers, D-Wave simulated annealing for a second opinion) and re-verifies every candidate; `solve_decision` / `verify_solution` remain available directly for classic decision problems.

---

## Examples

| File | Shows |
|---|---|
| [`examples/check_consistency.py`](examples/check_consistency.py) | A live model drafts an invoice; OptiMCP audits its multivariate arithmetic |
| [`examples/check_financial_report.py`](examples/check_financial_report.py) | Catching a wrong growth % and a cross-footing error (no API key) |
| [`examples/mcp_config.json`](examples/mcp_config.json) | One-line MCP client registration |

The live example works with an `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `OPENROUTER_API_KEY`; set `OPTIMCP_MODEL` to override the model.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Rule shows up in `unevaluable` | A referenced field is missing, miscased, or non-numeric | Fix the `path` (case-sensitive) or the document; check `RuleCheck.error` |
| `consistent=False` but you expected pass | A real violation — read `broken_rules` and the per-rule `detail`/`delta` | Trust it; the arithmetic is independent |
| A coercion note you didn't expect | A value was a string like `"$1,200"` and got normalized | Confirm the intended unit; emit numbers, not strings, if possible |
| `pct_change` rule is unevaluable | Base (`old`) is zero → undefined | Guard the case or use a different rule |
| `division by zero` error on a rule | `div`/ratio with a zero denominator | Handle the zero case in your rules |
| Validation error on a rule | Malformed `Expr` (e.g. `agg` path without `[*]`, wrong arity) | See [The rule language](#the-rule-language) |
| MCP client shows no tools | Server not launched / wrong command | Ensure `optimcp` is on PATH; test `optimcp --help` |

---

## Repository layout

```text
OptiMCP/
  pyproject.toml            Package metadata; optimcp console entry
  LICENSE                   Business Source License 1.1
  README.md                 This file
  src/optimcp/
    check/
      rules.py              Rule language: Expr AST, Rule, Ruleset (validated)
      paths.py              Deterministic path resolver (., [i], [*])
      eval.py               Decimal evaluator; verify-or-refuse; coercion notes
      result.py             RuleCheck / ConsistencyReport models
      repair.py             Optional: linear rules -> DecisionSpec -> solver fix
      __init__.py           check_consistency() entry point
    spec.py                 DecisionSpec + validation (solver input contract)
    verify.py               Independent constraint/domain verifier (solver side)
    solve.py                Solver orchestrator: two engines, verify, best wins
    engines/                CP-SAT (exact) + simulated annealing (heuristic)
    result.py               DecisionResult / VerificationCertificate models
    server.py               FastMCP server (check_consistency + solver tools)
    schemas.py              OpenAI / Anthropic function-tool schema export
    adapters/langchain.py   LangChain StructuredTool wrappers
  examples/                 Consistency-check demos + MCP config
  benchmarks/               Consistency benchmark (harness, results, writeup)
  tests/                    check / paths / repair / spec / verify / solve / server
```

---

## License

Business Source License 1.1 — see [LICENSE](LICENSE). On the Change Date it converts to Apache 2.0.
