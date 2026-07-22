"""LangChain verification callback / runnable helper."""

from __future__ import annotations

from typing import Any, Optional

from optimcp.middleware.client import verify_local_or_remote
from optimcp.middleware.openai_wrap import extract_json_object
from optimcp.middleware.policy import VerificationRefused, apply_policy


def with_verification(
    runnable: Any,
    *,
    ruleset_id: str,
    raise_on_refuse: bool = True,
    prefer_remote: bool = True,
) -> Any:
    """Wrap a LangChain runnable so structured dict/JSON outputs are verified.

    Requires ``langchain-core``. The wrapper inspects the runnable output; if it
    is a ``dict`` (or a string containing a JSON object), it is checked against
    ``ruleset_id``.
    """
    try:
        from langchain_core.runnables import RunnableLambda
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "LangChain is required. Install with `pip install optimcp[langchain]`."
        ) from exc

    def _verify(output: Any) -> Any:
        doc = None
        if isinstance(output, dict):
            doc = output
        elif isinstance(output, str):
            doc = extract_json_object(output)
        elif hasattr(output, "content"):
            doc = extract_json_object(str(getattr(output, "content")))
        if doc is None:
            return output
        result = verify_local_or_remote(
            ruleset_id,
            doc,
            prefer_remote=prefer_remote,
            source="agent",
        )
        apply_policy(result, raise_on_refuse=raise_on_refuse)
        return output

    return runnable | RunnableLambda(_verify)


class VerificationCallbackHandler:
    """LangChain callback that verifies JSON-looking LLM text on end.

    Prefer :func:`with_verification` for structured-output runnables; this
    handler is a lighter hook for chat models that emit JSON in text.
    """

    def __init__(
        self,
        ruleset_id: str,
        *,
        raise_on_refuse: bool = True,
        prefer_remote: bool = True,
    ) -> None:
        self.ruleset_id = ruleset_id
        self.raise_on_refuse = raise_on_refuse
        self.prefer_remote = prefer_remote
        self.last_result = None

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        text = ""
        try:
            gens = getattr(response, "generations", None) or []
            if gens and gens[0]:
                text = getattr(gens[0][0], "text", "") or ""
        except Exception:
            return
        doc = extract_json_object(text)
        if doc is None:
            return
        result = verify_local_or_remote(
            self.ruleset_id,
            doc,
            prefer_remote=self.prefer_remote,
            source="agent",
        )
        self.last_result = result
        apply_policy(result, raise_on_refuse=self.raise_on_refuse)
