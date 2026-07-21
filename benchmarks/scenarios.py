"""Benchmark scenarios: agent decisions across budget / scheduling / portfolio.

Each scenario is a natural-language decision plus the *ground-truth* structured
spec (with the CORRECT operators - e.g. exactly-one is ``==``). Some scenarios
are deliberate traps: a plausible-sounding wrong answer exists that an LLM
reasoning alone (or mis-modeling ``==`` as ``<=``) will tend to produce.

Ground truth is computed from ``true_spec`` by exact enumeration at run time, so
these numbers are not hand-entered and can't drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Scenario:
    id: str
    category: str
    trap: bool
    prompt: str
    variables: List[str]
    true_spec: Dict


SCENARIOS: List[Scenario] = [
    # ---------------- Budget allocation ----------------
    Scenario(
        id="budget_easy",
        category="budget",
        trap=False,
        prompt=(
            "You have a $90k budget to fund projects. Each project is either "
            "funded or not.\n"
            "- p_a: cost $50k, expected return $50k\n"
            "- p_b: cost $40k, expected return $40k\n"
            "- p_c: cost $30k, expected return $30k\n"
            "Pick the projects that maximize total expected return without "
            "exceeding the $90k budget."
        ),
        variables=["p_a", "p_b", "p_c"],
        true_spec={
            "variables": [{"name": "p_a"}, {"name": "p_b"}, {"name": "p_c"}],
            "objective": {
                "sense": "maximize",
                "terms": [
                    {"vars": ["p_a"], "coeff": 50},
                    {"vars": ["p_b"], "coeff": 40},
                    {"vars": ["p_c"], "coeff": 30},
                ],
            },
            "constraints": [
                {
                    "name": "budget",
                    "terms": [
                        {"vars": ["p_a"], "coeff": 50},
                        {"vars": ["p_b"], "coeff": 40},
                        {"vars": ["p_c"], "coeff": 30},
                    ],
                    "op": "<=",
                    "rhs": 90,
                }
            ],
        },
    ),
    Scenario(
        id="budget_trap",
        category="budget",
        trap=True,
        # Trap: the two highest-return projects (p_a, p_b) cost $120k together and
        # blow the $100k budget. The correct pick is p_a + p_c ($100k, return 160).
        prompt=(
            "You have a $100k budget to fund projects. Each project is either "
            "funded or not.\n"
            "- p_a: cost $60k, expected return $100k\n"
            "- p_b: cost $60k, expected return $95k\n"
            "- p_c: cost $40k, expected return $60k\n"
            "- p_d: cost $40k, expected return $55k\n"
            "Pick the projects that maximize total expected return without "
            "exceeding the $100k budget."
        ),
        variables=["p_a", "p_b", "p_c", "p_d"],
        true_spec={
            "variables": [
                {"name": "p_a"},
                {"name": "p_b"},
                {"name": "p_c"},
                {"name": "p_d"},
            ],
            "objective": {
                "sense": "maximize",
                "terms": [
                    {"vars": ["p_a"], "coeff": 100},
                    {"vars": ["p_b"], "coeff": 95},
                    {"vars": ["p_c"], "coeff": 60},
                    {"vars": ["p_d"], "coeff": 55},
                ],
            },
            "constraints": [
                {
                    "name": "budget",
                    "terms": [
                        {"vars": ["p_a"], "coeff": 60},
                        {"vars": ["p_b"], "coeff": 60},
                        {"vars": ["p_c"], "coeff": 40},
                        {"vars": ["p_d"], "coeff": 40},
                    ],
                    "op": "<=",
                    "rhs": 100,
                }
            ],
        },
    ),
    # ---------------- Scheduling ----------------
    Scenario(
        id="scheduling_easy",
        category="scheduling",
        trap=False,
        prompt=(
            "Assign staff to Monday shifts. People: Ana, Ben. Shifts: Morning, "
            "Evening.\n"
            "- Each shift must be staffed by exactly one person.\n"
            "- No person may work more than one shift.\n"
            "Preferences (higher = better): ana_m=5, ana_e=2, ben_m=3, ben_e=4.\n"
            "Maximize total preference. Variables (binary, one per person-shift): "
            "ana_m, ana_e, ben_m, ben_e."
        ),
        variables=["ana_m", "ana_e", "ben_m", "ben_e"],
        true_spec={
            "variables": [
                {"name": "ana_m"},
                {"name": "ana_e"},
                {"name": "ben_m"},
                {"name": "ben_e"},
            ],
            "objective": {
                "sense": "maximize",
                "terms": [
                    {"vars": ["ana_m"], "coeff": 5},
                    {"vars": ["ana_e"], "coeff": 2},
                    {"vars": ["ben_m"], "coeff": 3},
                    {"vars": ["ben_e"], "coeff": 4},
                ],
            },
            "constraints": [
                {"name": "morning_cover", "terms": [{"vars": ["ana_m"]}, {"vars": ["ben_m"]}], "op": "==", "rhs": 1},
                {"name": "evening_cover", "terms": [{"vars": ["ana_e"]}, {"vars": ["ben_e"]}], "op": "==", "rhs": 1},
                {"name": "ana_one", "terms": [{"vars": ["ana_m"]}, {"vars": ["ana_e"]}], "op": "<=", "rhs": 1},
                {"name": "ben_one", "terms": [{"vars": ["ben_m"]}, {"vars": ["ben_e"]}], "op": "<=", "rhs": 1},
            ],
        },
    ),
    Scenario(
        id="scheduling_trap",
        category="scheduling",
        trap=True,
        # Trap: minimizing reluctance with coverage as "<= 1" leaves both shifts
        # empty (cost 0). Only "== 1" forces coverage; true optimum is 3.
        prompt=(
            "Two unpopular weekend shifts must EACH be staffed by exactly one "
            "person (a shift may not be left empty): Saturday and Sunday. People: "
            "Ana, Ben (a person may take both shifts).\n"
            "Reluctance (higher = more unwilling): ana_sat=1, ana_sun=8, "
            "ben_sat=6, ben_sun=2.\n"
            "MINIMIZE total reluctance while covering both shifts. Variables "
            "(binary): ana_sat, ana_sun, ben_sat, ben_sun."
        ),
        variables=["ana_sat", "ana_sun", "ben_sat", "ben_sun"],
        true_spec={
            "variables": [
                {"name": "ana_sat"},
                {"name": "ana_sun"},
                {"name": "ben_sat"},
                {"name": "ben_sun"},
            ],
            "objective": {
                "sense": "minimize",
                "terms": [
                    {"vars": ["ana_sat"], "coeff": 1},
                    {"vars": ["ana_sun"], "coeff": 8},
                    {"vars": ["ben_sat"], "coeff": 6},
                    {"vars": ["ben_sun"], "coeff": 2},
                ],
            },
            "constraints": [
                {"name": "sat_cover", "terms": [{"vars": ["ana_sat"]}, {"vars": ["ben_sat"]}], "op": "==", "rhs": 1},
                {"name": "sun_cover", "terms": [{"vars": ["ana_sun"]}, {"vars": ["ben_sun"]}], "op": "==", "rhs": 1},
            ],
        },
    ),
    # ---------------- Portfolio ----------------
    Scenario(
        id="portfolio_easy",
        category="portfolio",
        trap=False,
        prompt=(
            "Choose which assets to include in a portfolio under a $90k budget. "
            "Each asset is included or not.\n"
            "- s1: cost $30k, expected return 40\n"
            "- s2: cost $30k, expected return 35\n"
            "- s3: cost $30k, expected return 30\n"
            "- s4: cost $30k, expected return 20\n"
            "Maximize total expected return without exceeding the $90k budget. "
            "Variables (binary): s1, s2, s3, s4."
        ),
        variables=["s1", "s2", "s3", "s4"],
        true_spec={
            "variables": [{"name": "s1"}, {"name": "s2"}, {"name": "s3"}, {"name": "s4"}],
            "objective": {
                "sense": "maximize",
                "terms": [
                    {"vars": ["s1"], "coeff": 40},
                    {"vars": ["s2"], "coeff": 35},
                    {"vars": ["s3"], "coeff": 30},
                    {"vars": ["s4"], "coeff": 20},
                ],
            },
            "constraints": [
                {
                    "name": "budget",
                    "terms": [
                        {"vars": ["s1"], "coeff": 30},
                        {"vars": ["s2"], "coeff": 30},
                        {"vars": ["s3"], "coeff": 30},
                        {"vars": ["s4"], "coeff": 30},
                    ],
                    "op": "<=",
                    "rhs": 90,
                }
            ],
        },
    ),
    Scenario(
        id="portfolio_trap",
        category="portfolio",
        trap=True,
        # Trap: a diversification rule requires EXACTLY 3 holdings (== 3). Ignoring
        # it, the best return is a+b (2 holdings, return 115) but that violates the
        # rule. True optimum under ==3 within budget is a+c+d (return 98).
        prompt=(
            "Choose assets for a portfolio under a $100k budget. Firm policy "
            "requires holding EXACTLY 3 assets for diversification (not 2, not 4).\n"
            "- a: cost $50k, expected return 60\n"
            "- b: cost $50k, expected return 55\n"
            "- c: cost $20k, expected return 20\n"
            "- d: cost $20k, expected return 18\n"
            "- e: cost $20k, expected return 15\n"
            "Maximize total expected return, hold exactly 3 assets, and stay "
            "within the $100k budget. Variables (binary): a, b, c, d, e."
        ),
        variables=["a", "b", "c", "d", "e"],
        true_spec={
            "variables": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}, {"name": "e"}],
            "objective": {
                "sense": "maximize",
                "terms": [
                    {"vars": ["a"], "coeff": 60},
                    {"vars": ["b"], "coeff": 55},
                    {"vars": ["c"], "coeff": 20},
                    {"vars": ["d"], "coeff": 18},
                    {"vars": ["e"], "coeff": 15},
                ],
            },
            "constraints": [
                {
                    "name": "budget",
                    "terms": [
                        {"vars": ["a"], "coeff": 50},
                        {"vars": ["b"], "coeff": 50},
                        {"vars": ["c"], "coeff": 20},
                        {"vars": ["d"], "coeff": 20},
                        {"vars": ["e"], "coeff": 20},
                    ],
                    "op": "<=",
                    "rhs": 100,
                },
                {
                    "name": "exactly_three",
                    "terms": [
                        {"vars": ["a"]},
                        {"vars": ["b"]},
                        {"vars": ["c"]},
                        {"vars": ["d"]},
                        {"vars": ["e"]},
                    ],
                    "op": "==",
                    "rhs": 3,
                },
            ],
        },
    ),
]
