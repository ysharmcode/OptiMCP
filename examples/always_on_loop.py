"""Simulate continuous ingest against a named ruleset; print violation stats.

Uses an in-process MonitorService (no HTTP). For the real daemon loop see
examples/daemon_quickstart.md.

    python examples/always_on_loop.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from optimcp.check.rules import Rule
from optimcp.monitor.models import RulesetRecord
from optimcp.monitor.service import MonitorService
from optimcp.monitor.store import MonitorStore


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="optimcp-loop-"))
    svc = MonitorService(store=MonitorStore(home=home))
    svc.register_ruleset(
        RulesetRecord(
            id="budgets",
            policy="observe",
            rules=[
                Rule.model_validate(
                    {
                        "id": "sum100",
                        "lhs": {
                            "kind": "calc",
                            "fn": "add",
                            "args": [
                                {"kind": "ref", "path": "a"},
                                {"kind": "ref", "path": "b"},
                            ],
                        },
                        "op": "==",
                        "rhs": {"kind": "lit", "value": 100},
                    }
                )
            ],
        )
    )

    stream = [
        {"a": 40, "b": 60},
        {"a": 50, "b": 50},
        {"a": 70, "b": 40},  # breaks
        {"a": 10, "b": 90},
        {"a": 1, "b": 1},  # breaks
    ]
    for i, doc in enumerate(stream):
        r = svc.verify("budgets", doc, source="http", correlation_id=f"evt-{i}", alert=False)
        mark = "OK" if r.report.consistent else "XX"
        print(f"[{mark}] evt-{i}  {doc}  -> {r.report.summary}")

    stats = svc.store.stats()
    print("\nstats:", stats)
    print(f"violations logged: {stats['total_violations']} / {stats['total_checks']}")
    print(f"data dir: {home}")
    print("With the daemon running, open /dashboard (Bearer token required).")


if __name__ == "__main__":
    main()
