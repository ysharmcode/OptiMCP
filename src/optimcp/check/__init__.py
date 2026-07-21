"""Deterministic consistency checking for LLM / agent structured output.

Give :func:`check_consistency` a JSON document and a set of declared rules; it
computes every rule independently (no LLM, exact :class:`~decimal.Decimal`
arithmetic) and tells you *provably which rule broke*, with the computed value,
the expected value and the delta. A rule it cannot even evaluate (a missing or
non-numeric field) is reported as not-passed, never silently skipped.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Union

from optimcp.check.eval import check_document, check_rule
from optimcp.check.result import ConsistencyReport, RuleCheck
from optimcp.check.rules import Expr, Rule, Ruleset

RulesArg = Union[Ruleset, Mapping[str, Any], Iterable[Any]]


def _as_ruleset(rules: RulesArg) -> Ruleset:
    if isinstance(rules, Ruleset):
        return rules
    if isinstance(rules, Mapping):
        # accept either a full {"rules": [...]} mapping or a single rule mapping
        if "rules" in rules:
            return Ruleset.model_validate(rules)
        return Ruleset(rules=[Rule.model_validate(rules)])
    return Ruleset(rules=[Rule.model_validate(r) for r in rules])


def check_consistency(document: Any, rules: RulesArg) -> ConsistencyReport:
    """Check ``document`` against ``rules`` and return a :class:`ConsistencyReport`.

    ``rules`` may be a :class:`Ruleset`, a ``{"rules": [...]}`` mapping, or a
    plain list of rule dicts / :class:`Rule` objects.
    """
    ruleset = _as_ruleset(rules)
    return check_document(document, ruleset)


__all__ = [
    "check_consistency",
    "check_document",
    "check_rule",
    "ConsistencyReport",
    "Expr",
    "Rule",
    "RuleCheck",
    "Ruleset",
]
