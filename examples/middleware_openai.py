"""Middleware demo: refuse a bad invoice against a named ruleset (no live LLM).

Registers an invoice ruleset under a temp OPTIMCP_HOME, verifies a bad document
in-process (prefer_remote=False), and shows VerificationRefused.

    python examples/middleware_openai.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from optimcp.check.rules import Rule
from optimcp.middleware.openai_wrap import VerifyingOpenAI
from optimcp.middleware.policy import VerificationRefused
from optimcp.monitor.models import RulesetRecord
from optimcp.monitor.service import MonitorService
from optimcp.monitor.store import MonitorStore


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="optimcp-mw-"))
    os.environ["OPTIMCP_HOME"] = str(home)
    store = MonitorStore(home=home)
    MonitorService(store=store).register_ruleset(
        RulesetRecord(
            id="invoices",
            policy="refuse",
            rules=[
                Rule.model_validate(
                    {
                        "id": "subtotal_foots",
                        "lhs": {"kind": "ref", "path": "subtotal"},
                        "op": "==",
                        "rhs": {
                            "kind": "agg",
                            "fn": "sum",
                            "path": "line_items[*].amount",
                        },
                    }
                )
            ],
        )
    )

    class _Msg:
        content = (
            '{"subtotal": 320, "line_items": '
            '[{"amount": 100}, {"amount": 120}, {"amount": 110}]}'
        )

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Fake:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return _Resp()

    client = VerifyingOpenAI(
        _Fake(), ruleset_id="invoices", raise_on_refuse=True, prefer_remote=False
    )
    try:
        client.chat.completions.create(model="demo", messages=[])
        print("unexpected: bad invoice was accepted")
    except VerificationRefused as exc:
        print("refused (as expected):", exc)
        print("broken:", exc.result.report.broken_rules)
        print("hash:", exc.result.document_hash[:16], "...")


if __name__ == "__main__":
    main()
