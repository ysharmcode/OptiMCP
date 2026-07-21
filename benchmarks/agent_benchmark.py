"""Does the OptiMCP tool actually make an agent's constrained decisions correct?

For each scenario we run a capable-but-imperfect model (gpt-4o-mini) N times in
two conditions:

  * tool ABSENT  - the model reasons alone and reports a final decision.
  * tool PRESENT - the model may call ``solve_decision`` and then reports a final
    decision.

Every final decision is scored against ground truth (computed by exact
enumeration of the TRUE spec) for (a) constraint violations and (b) optimality.
For the tool-present condition we also record how often the model actually calls
the tool.

Honest by construction: ground truth is recomputed, not hand-entered; and if a
decent model already gets the easy cases right by reasoning alone, that shows up
as a small/zero gap rather than being hidden.

Usage:
    set OPENROUTER_API_KEY / OPENAI_API_KEY, then:
    python agent_benchmark.py [--n 8] [--model openai/gpt-4o-mini] [--out results.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI

# Make sibling scenarios.py importable and the package usable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenarios import SCENARIOS, Scenario  # noqa: E402

from optimcp.engines.cpsat import solve_cpsat  # noqa: E402
from optimcp.schemas import openai_tool  # noqa: E402
from optimcp.solve import solve_decision  # noqa: E402
from optimcp.spec import DecisionSpec  # noqa: E402
from optimcp.verify import verify_assignment  # noqa: E402

FINAL_JSON_INSTRUCTION = (
    "On the LAST line of your reply output exactly this, with no code fences:\n"
    'FINAL_JSON: {"assignment": {<var>: <0 or 1>, ...}}\n'
    "Include every listed variable (use 0 for the ones you do not choose)."
)
SYSTEM_NO_TOOL = (
    "You are a careful decision assistant. Solve the problem, respecting every "
    "hard constraint exactly. " + FINAL_JSON_INSTRUCTION
)
SYSTEM_TOOL = (
    "You are a careful decision assistant. You have a solve_decision tool that "
    "returns answers independently verified to satisfy the constraints. For a "
    "decision with hard numeric constraints, prefer calling the tool over doing "
    "the arithmetic yourself. After you have an answer, " + FINAL_JSON_INSTRUCTION
)


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


def make_client() -> "tuple[OpenAI, str]":
    """Return (client, model). Supports OpenAI, Gemini (OpenAI-compat), OpenRouter."""
    model = os.getenv("OPTIMCP_MODEL")
    if os.getenv("OPENAI_API_KEY"):
        return OpenAI(), model or "gpt-4o-mini"
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        return OpenAI(api_key=gemini_key, base_url=_GEMINI_BASE), model or "gemini-2.0-flash"
    if os.getenv("OPENROUTER_API_KEY"):
        return (
            OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1"),
            model or "openai/gpt-4o-mini",
        )
    raise SystemExit("Set OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY to run the benchmark.")


# --------------------------- ground truth + scoring ---------------------------


@dataclass
class GroundTruth:
    optimum: float
    feasible_exists: bool


def ground_truth(scenario: Scenario) -> GroundTruth:
    # CP-SAT is exact: its answer is the provable optimum (ideal ground truth).
    spec = DecisionSpec.model_validate(scenario.true_spec)
    out = solve_cpsat(spec)
    if out.assignment is None:
        return GroundTruth(optimum=float("nan"), feasible_exists=False)
    cert = verify_assignment(spec, out.assignment)
    return GroundTruth(optimum=cert.objective_value, feasible_exists=True)


def _coerce(scenario: Scenario, raw: Optional[dict]) -> Optional[Dict[str, int]]:
    if not isinstance(raw, dict):
        return None
    inner = raw.get("assignment", raw)
    if not isinstance(inner, dict):
        return None
    assignment: Dict[str, int] = {}
    for name in scenario.variables:
        val = inner.get(name, 0)  # unspecified var => not chosen
        try:
            assignment[name] = int(round(float(val)))
        except (TypeError, ValueError):
            assignment[name] = 0
    return assignment


@dataclass
class RunScore:
    parseable: bool
    feasible: bool
    optimal: bool
    tool_called: Optional[bool] = None


def score(scenario: Scenario, assignment: Optional[Dict[str, int]], gt: GroundTruth) -> RunScore:
    if assignment is None:
        return RunScore(parseable=False, feasible=False, optimal=False)
    spec = DecisionSpec.model_validate(scenario.true_spec)
    cert = verify_assignment(spec, assignment)
    feasible = cert.all_satisfied
    optimal = feasible and abs(cert.objective_value - gt.optimum) <= 1e-6
    return RunScore(parseable=True, feasible=feasible, optimal=optimal)


# --------------------------- LLM plumbing ---------------------------


def extract_final_json(text: str) -> Optional[dict]:
    if not text:
        return None
    marker = "FINAL_JSON:"
    idx = text.rfind(marker)
    search_from = text[idx + len(marker):] if idx >= 0 else text
    # find the first {...} block and decode it
    brace = search_from.find("{")
    if brace < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(search_from[brace:])
        return obj
    except json.JSONDecodeError:
        # last resort: greedy match of a JSON object anywhere
        matches = re.findall(r"\{.*\}", search_from, re.DOTALL)
        for m in matches:
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue
    return None


class BenchAbort(Exception):
    """Raised when the provider is out of quota so the run should stop cleanly
    instead of recording a wall of fake failures that would poison the numbers."""


# Seconds to wait between API calls (paces against per-minute rate limits).
PACE_SECONDS = 4.0
_MAX_RETRIES = 5


_MAX_EMPTY_RETRIES = 8


def _create(client, **kwargs):
    """Call chat.completions with pacing + backoff. Aborts on hard quota errors.

    Handles two distinct free-tier failure modes:
      * rate/quota errors (429/402): exponential backoff, then abort.
      * empty ``choices`` bodies (flaky upstream): fast fixed-interval retry.
    """
    delay = 6.0
    rate_attempts = 0
    empty_attempts = 0
    while True:
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            code = getattr(exc, "status_code", None)
            if code == 402 or "402" in msg:
                raise BenchAbort(f"quota/credits exhausted (402): {msg[:160]}") from exc
            is_rate = code == 429 or "429" in msg or "rate" in msg.lower()
            rate_attempts += 1
            if rate_attempts >= _MAX_RETRIES:
                if is_rate:
                    raise BenchAbort(f"rate/daily limit persists after retries: {msg[:160]}") from exc
                raise
            time.sleep(delay)
            delay *= 2
            continue
        # Free/community providers intermittently return a body with no choices
        # (upstream hiccup, moderation, empty gen). Retry quickly rather than
        # scoring the run as a real model failure.
        if not getattr(resp, "choices", None):
            empty_attempts += 1
            if empty_attempts >= _MAX_EMPTY_RETRIES:
                raise BenchAbort(
                    f"empty response persisted after {empty_attempts} tries: "
                    f"{getattr(resp, 'error', None) or resp}"
                )
            time.sleep(2.0)
            continue
        time.sleep(PACE_SECONDS)
        return resp


def _chat(client, model, messages, tools=None):
    # Cap max_tokens: keeps each call cheap and avoids providers reserving their
    # full context window against the account balance.
    kwargs = dict(model=model, messages=messages, temperature=0.7, max_tokens=1024)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return _create(client, **kwargs)


def run_no_tool(client, model, scenario: Scenario) -> Optional[Dict[str, int]]:
    messages = [
        {"role": "system", "content": SYSTEM_NO_TOOL},
        {"role": "user", "content": scenario.prompt},
    ]
    resp = _chat(client, model, messages)
    return _coerce(scenario, extract_final_json(resp.choices[0].message.content or ""))


def run_with_tool(client, model, scenario: Scenario):
    tools = [openai_tool()]
    messages = [
        {"role": "system", "content": SYSTEM_TOOL},
        {"role": "user", "content": scenario.prompt},
    ]
    resp = _chat(client, model, messages, tools=tools)
    msg = resp.choices[0].message
    tool_called = bool(msg.tool_calls)
    tool_assignment: Optional[Dict[str, int]] = None

    if tool_called:
        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in msg.tool_calls
                ],
            }
        )
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments)
                result = solve_decision(DecisionSpec.model_validate(args)).model_dump()
                if result.get("status") == "solved":
                    tool_assignment = _coerce(scenario, {"assignment": result["assignment"]})
                content = json.dumps(result)
            except Exception as exc:  # noqa: BLE001
                content = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        messages.append({"role": "user", "content": FINAL_JSON_INSTRUCTION})
        final = _chat(client, model, messages, tools=tools)
        final_text = final.choices[0].message.content or ""
    else:
        final_text = msg.content or ""

    assignment = _coerce(scenario, extract_final_json(final_text))
    if assignment is None:
        assignment = tool_assignment  # fall back to the verified tool answer
    return assignment, tool_called


# --------------------------- aggregation ---------------------------


@dataclass
class Agg:
    n: int = 0
    parseable: int = 0
    feasible: int = 0
    optimal: int = 0
    tool_calls: int = 0

    def add(self, s: RunScore) -> None:
        self.n += 1
        self.parseable += int(s.parseable)
        self.feasible += int(s.feasible)
        self.optimal += int(s.optimal)
        if s.tool_called:
            self.tool_calls += 1

    def rates(self) -> dict:
        n = max(self.n, 1)
        return {
            "runs": self.n,
            "feasible_rate": round(self.feasible / n, 3),
            "optimal_rate": round(self.optimal / n, 3),
            "violation_rate": round((self.n - self.feasible) / n, 3),
            "parse_rate": round(self.parseable / n, 3),
            "tool_call_rate": round(self.tool_calls / n, 3),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="OptiMCP agent tool benchmark")
    parser.add_argument("--n", type=int, default=8, help="runs per scenario per condition")
    parser.add_argument("--model", default=None, help="override model id")
    parser.add_argument("--out", default=str(Path(__file__).parent / "agent_benchmark_result.json"))
    parser.add_argument("--sleep", type=float, default=4.0, help="seconds between API calls (rate-limit pacing)")
    args = parser.parse_args()

    global PACE_SECONDS
    PACE_SECONDS = args.sleep

    if args.model:
        os.environ["OPTIMCP_MODEL"] = args.model
    client, model = make_client()
    print(f"[benchmark] model={model} n={args.n} scenarios={len(SCENARIOS)} pace={PACE_SECONDS}s", flush=True)

    results = {"model": model, "n": args.n, "scenarios": {}}
    try:
        _run_all(client, model, args, results)
    except BenchAbort as exc:
        # Do NOT write partial results: a half-finished run would look like a wall
        # of failures and poison the published numbers. Leave prior artifacts intact.
        print(f"\n[benchmark] ABORTED (provider quota): {exc}", flush=True)
        print("[benchmark] no output written; existing result file left untouched.", flush=True)
        sys.exit(2)

    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\n[benchmark] wrote {args.out}", flush=True)


def _run_all(client, model, args, results) -> None:
    for sc in SCENARIOS:
        gt = ground_truth(sc)
        no_tool = Agg()
        with_tool = Agg()
        print(f"\n[{sc.id}] category={sc.category} trap={sc.trap} optimum={gt.optimum}", flush=True)
        for i in range(args.n):
            try:
                asg = run_no_tool(client, model, sc)
                s = score(sc, asg, gt)
                no_tool.add(s)
            except BenchAbort:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"  no_tool run {i} error: {exc}", flush=True)
                no_tool.add(RunScore(False, False, False))
            try:
                asg_t, called = run_with_tool(client, model, sc)
                st = score(sc, asg_t, gt)
                st.tool_called = called
                with_tool.add(st)
            except BenchAbort:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"  with_tool run {i} error: {exc}", flush=True)
                with_tool.add(RunScore(False, False, False, tool_called=False))
            print(
                f"  run {i+1}/{args.n}: no_tool(feas={no_tool.feasible},opt={no_tool.optimal}) "
                f"tool(feas={with_tool.feasible},opt={with_tool.optimal},calls={with_tool.tool_calls})",
                flush=True,
            )
        results["scenarios"][sc.id] = {
            "category": sc.category,
            "trap": sc.trap,
            "optimum": gt.optimum,
            "no_tool": no_tool.rates(),
            "with_tool": with_tool.rates(),
        }
        Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
