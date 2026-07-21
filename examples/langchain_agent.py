"""Real end-to-end: a LangChain model calls OptiMCP on a decision that is
only correct under a strict equality (`==`) encoding.

This example is deliberately designed so that a *lenient* encoding of "each shift
must be staffed" (using `<=` / "at most one" instead of `==` / "exactly one")
produces a different, wrong answer: two unpopular weekend shifts that nobody
wants. If coverage is modeled as `<= 1`, the cost-minimizer simply leaves both
shifts empty (cost 0) - a confident, wrong-looking-right answer. Only the true
`== 1` coverage rule forces both shifts to be staffed, so the demo honestly shows
the tool solving the intended problem, not getting lucky.

  People: Ana, Ben. Shifts: Saturday, Sunday (both MUST be covered).
  Reluctance (higher = more unwilling):
      Ana-Sat 1, Ana-Sun 8, Ben-Sat 6, Ben-Sun 2
  Correct answer (== coverage): Ana->Saturday, Ben->Sunday, total reluctance 3.
  Lenient (<= coverage) answer: nobody works, total reluctance 0 (shifts empty!).

Run it:

    pip install optimcp[langchain] langchain-openai
    setx OPENAI_API_KEY sk-...            # or OPENROUTER_API_KEY sk-or-...
    python langchain_agent.py

Optionally override the model with OPTIMCP_MODEL.
"""

import os

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from optimcp.adapters.langchain import build_langchain_tool

SYSTEM = (
    "You are a scheduling assistant. When assignments have hard rules, you MUST "
    "use the solve_decision tool instead of reasoning it out yourself. Model each "
    "(person, shift) choice as a binary variable. Read coverage rules precisely: "
    "'each shift must be staffed by exactly one person' is an EQUALITY constraint "
    "(the shift's variables sum to == 1), NOT 'at most one' (<= 1) - a shift may "
    "not be left empty."
)

SCENARIO = """\
Two unpopular weekend shifts must each be staffed by exactly one person:
Saturday and Sunday. People available: Ana and Ben. (A person may take both
shifts if that minimizes total reluctance.)

Hard rule:
- Each shift MUST be staffed by exactly one person. A shift may NOT be left empty.

Reluctance scores (higher = the person is more unwilling to take that shift):
- Ana on Saturday: 1
- Ana on Sunday: 8
- Ben on Saturday: 6
- Ben on Sunday: 2

Assign people to shifts to MINIMIZE total reluctance. Use the solve_decision tool
for a verified answer. Use exactly these binary variable names, one per
(person, shift): ana_sat, ana_sun, ben_sat, ben_sun.
"""


def make_llm() -> ChatOpenAI:
    model = os.getenv("OPTIMCP_MODEL")
    if os.getenv("OPENAI_API_KEY"):
        return ChatOpenAI(model=model or "gpt-4o-mini", temperature=0)
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        return ChatOpenAI(
            model=model or "gemini-2.0-flash",
            temperature=0,
            api_key=gemini_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    if os.getenv("OPENROUTER_API_KEY"):
        return ChatOpenAI(
            model=model or "openai/gpt-4o-mini",
            temperature=0,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    raise SystemExit("Set OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY to run this example.")


def main() -> None:
    tool = build_langchain_tool()
    llm = make_llm().bind_tools([tool])

    messages = [SystemMessage(SYSTEM), HumanMessage(SCENARIO)]
    ai = llm.invoke(messages)
    messages.append(ai)

    if not ai.tool_calls:
        print("!! The model did NOT call the tool. It answered directly:")
        print(ai.content)
        return

    for call in ai.tool_calls:
        print("[LLM -> tool] solve_decision arguments the model produced:")
        print(call["args"])
        result = tool.invoke(call["args"])
        print("\n[tool -> LLM] verified result:")
        print(f"  status          : {result['status']}")
        print(f"  assignment      : {result['assignment']}")
        print(f"  objective_value : {result['objective_value']}  (lower is better)")
        for check in result["verification"]["constraint_checks"]:
            print(f"  constraint      : {check['detail']}")
        # The honest checkpoint: confirm both shifts were actually covered, which
        # only happens if coverage was modeled as == 1 (not <= 1).
        asg = result["assignment"]
        sat = asg.get("ana_sat", 0) + asg.get("ben_sat", 0)
        sun = asg.get("ana_sun", 0) + asg.get("ben_sun", 0)
        covered = sat == 1 and sun == 1
        print(f"  both shifts covered? {covered}  (Sat={sat}, Sun={sun})")
        messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    final = llm.invoke(messages)
    print("\n[LLM final answer]")
    print(final.content)


if __name__ == "__main__":
    main()
