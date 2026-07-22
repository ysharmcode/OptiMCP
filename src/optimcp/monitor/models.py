"""Models for the always-on verification layer (named rulesets + audit events)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from optimcp.check.result import ConsistencyReport
from optimcp.check.rules import Rule

Policy = Literal["observe", "refuse"]
CheckSource = Literal["agent", "http", "mcp", "cli", "test"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RulesetRecord(BaseModel):
    """A named, versioned bag of rules bound to a refuse/observe policy."""

    id: str = Field(..., min_length=1, description="Stable ruleset identifier.")
    version: int = Field(1, ge=1)
    policy: Policy = Field("observe", description="'observe' logs; 'refuse' blocks.")
    rules: List[Rule] = Field(..., min_length=1)
    source: Optional[str] = Field(
        None, description="Optional label, e.g. 'erp.invoices'."
    )
    description: Optional[str] = None


class DaemonConfig(BaseModel):
    """Persisted daemon settings under OPTIMCP_HOME/config.yaml."""

    daemon_token: Optional[str] = None
    alert_webhook_url: Optional[str] = None
    default_policy: Policy = "observe"
    host: str = "127.0.0.1"
    port: int = 8787
    allow_unauthenticated_localhost: bool = False


class CheckEvent(BaseModel):
    """One verification against a named ruleset."""

    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=utc_now)
    ruleset_id: str
    ruleset_version: int
    document_hash: str
    consistent: bool
    broken_rules: List[str] = Field(default_factory=list)
    unevaluable: List[str] = Field(default_factory=list)
    summary: str = ""
    source: CheckSource = "http"
    correlation_id: Optional[str] = None
    policy: Policy = "observe"
    refused: bool = False


class ViolationRecord(CheckEvent):
    """A check that was not consistent (broken or unevaluable)."""

    pass


class VerifyResult(BaseModel):
    """Outcome of :meth:`~optimcp.monitor.service.MonitorService.verify`."""

    ruleset_id: str
    policy: Policy
    refused: bool
    document_hash: str
    report: ConsistencyReport
    check_id: Optional[int] = None

    def model_dump_report(self) -> Dict[str, Any]:
        data = self.model_dump()
        data["report"] = self.report.model_dump()
        return data
