"""LangChain adapter.

Wraps ``solve_decision`` as a LangChain ``StructuredTool`` so a LangChain /
LangGraph agent can call it mid-reasoning. ``langchain-core`` is an optional
dependency; import this module only when you actually use LangChain.
"""

from __future__ import annotations

from typing import Any

from optimcp.schemas import TOOL_DESCRIPTION, TOOL_NAME
from optimcp.solve import solve_decision as _solve_decision
from optimcp.spec import DecisionSpec


def build_langchain_tool() -> Any:
    """Return a LangChain ``StructuredTool`` wrapping ``solve_decision``.

    Raises ``ImportError`` with an actionable message if LangChain is missing.
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - exercised only without langchain
        raise ImportError(
            "LangChain is required for build_langchain_tool(). Install it with "
            "`pip install optimcp[langchain]` (or `pip install langchain-core`)."
        ) from exc

    def _run(**kwargs: Any) -> dict:
        spec = DecisionSpec.model_validate(kwargs)
        return _solve_decision(spec).model_dump()

    return StructuredTool.from_function(
        func=_run,
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        args_schema=DecisionSpec,
    )
