"""Agent middleware that binds named rulesets to structured emissions."""

from __future__ import annotations

from optimcp.middleware.client import (
    DaemonClientError,
    daemon_token,
    daemon_url,
    verify_local_or_remote,
    verify_remote,
)
from optimcp.middleware.langchain import build_check_consistency_tool
from optimcp.middleware.openai_wrap import VerifyingOpenAI, extract_json_object
from optimcp.middleware.policy import (
    VerificationRefused,
    apply_policy,
    result_as_tool_error,
    verify_then_policy,
)

__all__ = [
    "DaemonClientError",
    "VerificationRefused",
    "VerifyingOpenAI",
    "apply_policy",
    "build_check_consistency_tool",
    "daemon_token",
    "daemon_url",
    "extract_json_object",
    "result_as_tool_error",
    "verify_local_or_remote",
    "verify_remote",
    "verify_then_policy",
]
