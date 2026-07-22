"""High-level verify-against-named-ruleset service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from optimcp.check import check_consistency
from optimcp.monitor.alerts import notify_violation_async
from optimcp.monitor.hashing import document_hash
from optimcp.monitor.models import (
    CheckEvent,
    CheckSource,
    RulesetRecord,
    VerifyResult,
    utc_now,
)
from optimcp.monitor.store import MonitorStore


class RulesetNotFound(KeyError):
    """Raised when a ruleset id is unknown."""


class MonitorService:
    """Register rulesets and verify documents with audit + optional alerts."""

    def __init__(self, store: Optional[MonitorStore] = None, home: Optional[Path] = None) -> None:
        self.store = store or MonitorStore(home=home)

    def register_ruleset(self, record: RulesetRecord) -> RulesetRecord:
        return self.store.register_ruleset(record)

    def get_ruleset(self, ruleset_id: str) -> RulesetRecord:
        rec = self.store.get_ruleset(ruleset_id)
        if rec is None:
            raise RulesetNotFound(ruleset_id)
        return rec

    def list_rulesets(self) -> List[RulesetRecord]:
        return self.store.list_rulesets()

    def verify(
        self,
        ruleset_id: str,
        document: Any,
        *,
        source: CheckSource = "http",
        correlation_id: Optional[str] = None,
        alert: bool = True,
    ) -> VerifyResult:
        record = self.get_ruleset(ruleset_id)
        report = check_consistency(document, record.rules)
        doc_hash = document_hash(document)
        refused = (not report.consistent) and record.policy == "refuse"
        event = CheckEvent(
            timestamp=utc_now(),
            ruleset_id=record.id,
            ruleset_version=record.version,
            document_hash=doc_hash,
            consistent=report.consistent,
            broken_rules=list(report.broken_rules),
            unevaluable=list(report.unevaluable),
            summary=report.summary,
            source=source,
            correlation_id=correlation_id,
            policy=record.policy,
            refused=refused,
        )
        event = self.store.append_check(event)
        if alert and not report.consistent:
            cfg = self.store.load_config()
            notify_violation_async(cfg.alert_webhook_url, event)
        return VerifyResult(
            ruleset_id=record.id,
            policy=record.policy,
            refused=refused,
            document_hash=doc_hash,
            report=report,
            check_id=event.id,
        )
