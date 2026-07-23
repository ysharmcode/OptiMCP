"""HTTP client helpers for talking to the OptiMCP daemon."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from optimcp.check.result import ConsistencyReport
from optimcp.monitor.models import CheckSource, VerifyResult
from optimcp.monitor.service import MonitorService, RulesetNotFound
from optimcp.monitor.store import MonitorStore


class DaemonClientError(RuntimeError):
    def __init__(self, message: str, *, status: Optional[int] = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def daemon_url() -> str:
    return os.getenv("OPTIMCP_DAEMON_URL", "http://127.0.0.1:8787").rstrip("/")


def daemon_token() -> Optional[str]:
    t = os.getenv("OPTIMCP_DAEMON_TOKEN")
    return t.strip() if t else None


def _headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    token = daemon_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def verify_remote(
    ruleset_id: str,
    document: Any,
    *,
    correlation_id: Optional[str] = None,
    base_url: Optional[str] = None,
) -> VerifyResult:
    url = (base_url or daemon_url()) + "/v1/check"
    payload = {
        "ruleset_id": ruleset_id,
        "document": document,
        "correlation_id": correlation_id,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            raw = json.loads(body)
        except json.JSONDecodeError:
            raise DaemonClientError(body or str(exc), status=exc.code) from exc
        if exc.code == 422 and "report" in raw:
            return _parse_verify_payload(raw)
        raise DaemonClientError(
            raw.get("detail", body) if isinstance(raw, dict) else body,
            status=exc.code,
            body=raw,
        ) from exc
    except urllib.error.URLError as exc:
        raise DaemonClientError(f"daemon unreachable at {url}: {exc}") from exc
    return _parse_verify_payload(raw)


def _parse_verify_payload(raw: Dict[str, Any]) -> VerifyResult:
    report = ConsistencyReport.model_validate(raw["report"])
    return VerifyResult(
        ruleset_id=raw["ruleset_id"],
        policy=raw["policy"],
        refused=bool(raw.get("refused")),
        document_hash=raw["document_hash"],
        report=report,
        check_id=raw.get("check_id"),
    )


def verify_local_or_remote(
    ruleset_id: str,
    document: Any,
    *,
    correlation_id: Optional[str] = None,
    prefer_remote: bool = True,
    source: CheckSource = "agent",
) -> VerifyResult:
    """Try the daemon first; fall back to in-process MonitorStore only if unreachable."""
    if prefer_remote:
        try:
            return verify_remote(
                ruleset_id, document, correlation_id=correlation_id
            )
        except DaemonClientError as exc:
            # HTTP errors (401/404/5xx) must surface; only soft-fail on no connection
            if exc.status is not None:
                raise
    try:
        return MonitorService(store=MonitorStore()).verify(
            ruleset_id,
            document,
            source=source,
            correlation_id=correlation_id,
        )
    except RulesetNotFound as exc:
        raise DaemonClientError(f"ruleset not found: {exc}") from exc
