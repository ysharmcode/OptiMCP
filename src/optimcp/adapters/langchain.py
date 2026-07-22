"""LangChain adapters.

Wrap OptiMCP's tools as LangChain ``StructuredTool`` objects so a LangChain /
LangGraph agent can call them mid-reasoning. ``langchain-core`` is an optional
dependency; import this module only when you actually use LangChain.
"""

from __future__ import annotations

from typing import Any

from optimcp.check import check_consistency as _check_consistency
from optimcp.schemas import (
    SOLVE_TOOL_DESCRIPTION,
    SOLVE_TOOL_NAME,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    CheckConsistencyArgs,
)
from optimcp.solve import solve_decision as _solve_decision
from optimcp.spec import DecisionSpec


def _require_langchain():
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - exercised only without langchain
        raise ImportError(
            "LangChain is required for this adapter. Install it with "
            "`pip install optimcp[langchain]` (or `pip install langchain-core`)."
        ) from exc
    return StructuredTool


def build_check_consistency_tool() -> Any:
    """Return a LangChain ``StructuredTool`` wrapping ``check_consistency``."""
    StructuredTool = _require_langchain()

    def _run(**kwargs: Any) -> dict:
        args = CheckConsistencyArgs.model_validate(kwargs)
        return _check_consistency(args.document, args.rules).model_dump()

    return StructuredTool.from_function(
        func=_run,
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        args_schema=CheckConsistencyArgs,
    )


def build_langchain_tool() -> Any:
    """Return a LangChain ``StructuredTool`` wrapping ``solve_decision``."""
    StructuredTool = _require_langchain()

    def _run(**kwargs: Any) -> dict:
        spec = DecisionSpec.model_validate(kwargs)
        return _solve_decision(spec).model_dump()

    return StructuredTool.from_function(
        func=_run,
        name=SOLVE_TOOL_NAME,
        description=SOLVE_TOOL_DESCRIPTION,
        args_schema=DecisionSpec,
    )


def build_verification_callback(
    ruleset_id: str,
    *,
    raise_on_refuse: bool = True,
    prefer_remote: bool = True,
) -> Any:
    """Return a :class:`~optimcp.middleware.langchain.VerificationCallbackHandler`."""
    from optimcp.middleware.langchain import VerificationCallbackHandler

    return VerificationCallbackHandler(
        ruleset_id,
        raise_on_refuse=raise_on_refuse,
        prefer_remote=prefer_remote,
    )


def with_verification(
    runnable: Any,
    *,
    ruleset_id: str,
    raise_on_refuse: bool = True,
    prefer_remote: bool = True,
) -> Any:
    """Wrap a LangChain runnable so structured outputs are verified."""
    from optimcp.middleware.langchain import with_verification as _wrap

    return _wrap(
        runnable,
        ruleset_id=ruleset_id,
        raise_on_refuse=raise_on_refuse,
        prefer_remote=prefer_remote,
    )
