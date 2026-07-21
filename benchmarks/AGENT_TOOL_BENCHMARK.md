# Does the OptiMCP tool actually make an agent's constrained decisions correct?

An honest, reproducible measurement — including the results that argue *against* a
broad pitch. Short version: **for a capable model, the tool does not help on
simple decisions it already gets right, clearly helps on a constraint the model
tends to forget (cardinality), and can actively hurt when serializing the problem
for the tool introduces a transcription error that free-form reasoning avoids.**

> **Status: PROVISIONAL (N=8).** These are directional numbers from a single
> clean N=8 run. The *patterns* below are robust; the *exact* percentages
> (e.g. 87.5%→100%, 100%→25%) are thin at N=8 and should be re-measured at
> **N≥20** before being quoted as final. A planned N=25 re-run was abandoned when
> the API balance ran out mid-run (HTTP 402 on nearly every call) and its numbers
> were discarded rather than published contaminated.

## Method

- **Model:** `gpt-4o-mini` (via OpenRouter's OpenAI-compatible API), `temperature=0.7`, `max_tokens=1024`.
- **N:** 8 runs per scenario per condition.
- **Conditions:**
  - **tool absent** — the model reasons alone and reports a final decision as JSON.
  - **tool present** — the model may call `solve_decision`, then reports a final decision as JSON.
- **Scoring:** every final decision is checked against **ground truth**, which is recomputed by exact enumeration of the *true* spec (with the correct operators — e.g. "exactly one" is `==`). We record the **feasibility rate** (fraction satisfying all true constraints) and **optimality rate** (feasible *and* hitting the true optimum). For the tool condition we also record the **tool-call rate**.
- **Battery:** budget / scheduling / portfolio, each with an "easy" case and a deliberate **trap** where a plausible-sounding wrong answer exists.
- **Harness:** [`agent_benchmark.py`](agent_benchmark.py); **scenarios:** [`scenarios.py`](scenarios.py); **raw output:** [`agent_benchmark_result.json`](agent_benchmark_result.json).

## Results (N=8)

| Scenario | Category | Trap | No-tool feasible | No-tool optimal | With-tool feasible | With-tool optimal | Tool-call rate | Δ feasible |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| budget_easy | budget | – | 100% | 100% | 100% | 100% | 100% | 0 |
| **budget_trap** | budget | ✓ | **100%** | **100%** | **25%** | **25%** | 100% | **−75pp** |
| scheduling_easy | scheduling | – | 100% | 100% | 100% | 100% | 100% | 0 |
| scheduling_trap | scheduling | ✓ | 100% | 100% | 100% | 100% | 100% | 0 |
| portfolio_easy | portfolio | – | 100% | 100% | 100% | 100% | 100% | 0 |
| **portfolio_trap** | portfolio | ✓ | **87.5%** | **87.5%** | **100%** | **100%** | 100% | **+12.5pp** |

## Honest reading

### 1. On simple decisions, the tool changes nothing — the model already gets them right.

Every "easy" scenario is 100% with and without the tool, and even two of the three *traps* (`scheduling_trap`, and reasoning-alone on `budget_trap`) are solved by reasoning alone. This is the **boring-but-real** finding: for a decent model at this scale, constrained arithmetic over a handful of options is not where an external solver earns its keep. It narrows the honest pitch from "matters on any budget question" to **"matters as the constraint structure gets harder to hold in your head."**

### 2. Where the model tends to *forget a constraint*, the tool helps.

`portfolio_trap` requires holding **exactly 3** assets. Reasoning alone, the model occasionally maximizes return and quietly picks the 2 highest-return assets (violating "exactly 3") — 87.5% feasible. With the tool it is **100%**: the `== 3` constraint is enforced by construction. This is the tool's real niche — **constraints an LLM drops while chasing the objective** (cardinality, coverage, mutual exclusion).

### 3. Where serializing the problem introduces a scale error, the tool can *hurt*.

`budget_trap` is the cautionary result: **100% correct by reasoning, but only 25% correct with the tool** — and the model called the tool every time. Inspecting the specs it produced, the root cause is a **unit-transcription error**:

```text
objective:  100·p_a + 95·p_b + 60·p_c + 55·p_d        (returns, in $k)
constraint: 60·p_a + 60·p_b + 40·p_c + 40·p_d  <=  100000   (costs in $k, budget in $!)
```

The model kept costs in "thousands" (60, 40) but expanded the "$100k" budget to `100000`. The constraint `60·p_a + … <= 100000` is a perfectly valid rule, so the tool faithfully "solves" it — and funds **everything** (objective 310), which blows the *real* $100k budget. Runs where the units were consistent (rhs = 100, or costs also in full dollars) returned the correct answer (160). `budget_easy` hides this because there the model happened to keep units consistent; the trap surfaces it.

The lesson is uncomfortable but important: **the guarantee is only as good as the encoding.** The tool cannot know that `<= 100000` was meant to be `<= 100`. Free-form reasoning avoided the mistake because the model never had to commit the problem to a rigid schema.

## What we changed because of this

- The function/tool description now explicitly instructs the model to **use one consistent unit across the whole spec** and to read "exactly N" / "must be covered" as `==`. (See `optimcp/schemas.py`.)
- The README's guarantee section states plainly that verification covers the constraints **as encoded, not as intended**, and points agents at `verify_solution` + the echoed certificate (a human reviewing `budget: … <= 100000` would catch the unit error immediately).

## Where the tool is (and isn't) worth calling

- **Worth it:** decisions with constraints an LLM reliably drops or mis-weights — cardinality (`== k`), coverage, mutual exclusion, and larger/denser problems where the arithmetic stops being easy.
- **Not worth it (yet):** tiny budget-style arithmetic a capable model already nails — and actively risky if the serialization step can garble units/scale. Mitigations: consistent-unit guidance (added), and using `verify_solution` on the model's *own* proposed answer rather than re-deriving the spec.

## Caveats

- One model (`gpt-4o-mini`), small N (8), tiny problems (≤ 5 binary variables), `temperature=0.7`. These are directional signals, not a leaderboard.
- Rates are per-scenario over 8 samples, so ±1 run is ~12.5pp of noise.
- The `budget_trap` failure is a *serialization* failure, not a solver failure; a model better at structured extraction (or with a schema that normalizes units) would likely close most of that gap.

## Reproduce

```bash
pip install "optimcp" openai
set OPENROUTER_API_KEY=...      # or OPENAI_API_KEY / GEMINI_API_KEY
python benchmarks/agent_benchmark.py --n 8 --model openai/gpt-4o-mini
```
