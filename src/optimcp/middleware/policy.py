"""Shared refuse/observe handling for agent middleware."""

from __future__ import annotations

from typing import Any, Optional

from optimcp.monitor.models import VerifyResult


class VerificationRefused(Exception):
    """Raised when a ruleset policy is ``refuse`` and the document is inconsistent."""

    def __init__(self, result: VerifyResult) -> None:
        self.result = result
        super().__init__(
            f"verification refused for ruleset {result.ruleset_id!r}: {result.report.summary}"
        )


def apply_policy(result: VerifyResult, *, raise_on_refuse: bool = True) -> VerifyResult:
    """If refused and ``raise_on_refuse``, raise :class:`VerificationRefused`."""
    if result.refused and raise_on_refuse:
        raise VerificationRefused(result)
    return result


def result_as_tool_error(result: VerifyResult) -> dict[str, Any]:
    """Structured error payload an agent loop can feed back to the model."""
    return {
        "ok": False,
        "refused": result.refused,
        "ruleset_id": result.ruleset_id,
        "policy": result.policy,
        "document_hash": result.document_hash,
        "report": result.report.model_dump(),
        "message": result.report.summary,
    }
