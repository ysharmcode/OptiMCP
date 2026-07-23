"""Shared refuse/observe handling for agent middleware."""

from __future__ import annotations

from typing import Any, Optional

from optimcp.middleware.client import verify_local_or_remote
from optimcp.monitor.models import CheckSource, VerifyResult


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


def verify_then_policy(
    ruleset_id: str,
    document: dict,
    *,
    correlation_id: Optional[str] = None,
    prefer_remote: bool = True,
    source: CheckSource = "agent",
    raise_on_refuse: bool = True,
) -> VerifyResult:
    """Verify locally or via daemon, then apply refuse/observe policy."""
    result = verify_local_or_remote(
        ruleset_id,
        document,
        correlation_id=correlation_id,
        prefer_remote=prefer_remote,
        source=source,
    )
    return apply_policy(result, raise_on_refuse=raise_on_refuse)


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
