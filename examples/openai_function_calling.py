"""Real end-to-end: an LLM calls OptiMCP to avoid blowing a budget.

This is the actual product experience, not a mock: a live model is given a
budget-shaped decision in plain English, decides on its own to call the
``solve_decision`` tool, fills in the structured schema, and gets back an
answer that OptiMCP has *independently verified* to respect the budget.

Run it:

    # OpenAI:
    setx OPENAI_API_KEY sk-...        # then open a new shell
    python openai_function_calling.py

    # or OpenRouter (OpenAI-compatible):
    setx OPENROUTER_API_KEY sk-or-...
    python openai_function_calling.py

Optionally override the model with OPTIMCP_MODEL.
"""

import json
import os

from openai import OpenAI

from optimcp.schemas import openai_tool
from optimcp.solve import solve_decision
from optimcp.spec import DecisionSpec

# A budget-violation-shaped prompt: the projects together cost far more than the
# budget, so the model cannot just "fund everything" - it has to choose, and the
# tool guarantees the choice actually fits under $100k.
USER_PROMPT = """\
I have a budget of $100,000 to fund projects this quarter. Candidates:

- Atlas:   cost $60k, expected return $70k
- Beacon:  cost $40k, expected return $40k
- Cirrus:  cost $50k, expected return $55k
- Delta:   cost $30k, expected return $25k

Pick the set of projects that maximizes total expected return without spending
more than the $100k budget. Use the solve_decision tool to get a verified answer;
do not just estimate.
"""

SYSTEM_PROMPT = (
    "You are a careful budgeting assistant. When a decision has hard numeric "
    "constraints (budgets, capacities, headcounts), you MUST use the "
    "solve_decision tool instead of guessing, because your own arithmetic can "
    "silently violate the constraint. Map each option to a binary variable."
)


def make_client():
    """Return (client, model): OpenAI, Gemini (OpenAI-compat), or OpenRouter."""
    model = os.getenv("OPTIMCP_MODEL")
    if os.getenv("OPENAI_API_KEY"):
        return OpenAI(), model or "gpt-4o-mini"
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        return (
            OpenAI(
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            model or "gemini-2.0-flash",
        )
    if os.getenv("OPENROUTER_API_KEY"):
        return (
            OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1"),
            model or "openai/gpt-4o-mini",
        )
    raise SystemExit("Set OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY to run this example.")


def dispatch(tool_name: str, arguments: dict) -> dict:
    if tool_name == "solve_decision":
        spec = DecisionSpec.model_validate(arguments)
        return solve_decision(spec).model_dump()
    raise ValueError(f"unknown tool: {tool_name}")


def main() -> None:
    client, model = make_client()
    tools = [openai_tool()]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]

    print(f"[model] {model}\n")
    first = client.chat.completions.create(
        model=model, messages=messages, tools=tools, tool_choice="auto"
    )
    msg = first.choices[0].message

    if not msg.tool_calls:
        print("!! The model did NOT call the tool. It answered directly:")
        print(msg.content)
        return

    # Echo the assistant turn (with its tool call) back into the conversation.
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
        args = json.loads(call.function.arguments)
        print("[LLM -> tool] solve_decision arguments the model produced:")
        print(json.dumps(args, indent=2))
        result = dispatch(call.function.name, args)
        print("\n[tool -> LLM] verified result:")
        print(f"  status           : {result['status']}")
        print(f"  assignment       : {result['assignment']}")
        print(f"  objective_value  : {result['objective_value']}")
        for check in result["verification"]["constraint_checks"]:
            print(f"  constraint       : {check['detail']}")
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
        )

    final = client.chat.completions.create(model=model, messages=messages, tools=tools)
    print("\n[LLM final answer]")
    print(final.choices[0].message.content)


if __name__ == "__main__":
    main()
