"""Outbound webhook alerts for new violations (Slack-compatible JSON)."""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Optional

from optimcp.monitor.models import CheckEvent

logger = logging.getLogger(__name__)


def notify_violation(
    webhook_url: Optional[str],
    event: CheckEvent,
    *,
    timeout: float = 5.0,
) -> bool:
    """POST a Slack-compatible payload. Returns True on HTTP success."""
    if not webhook_url:
        return False
    text = (
        f"OptiMCP violation on ruleset `{event.ruleset_id}` "
        f"(policy={event.policy}, refused={event.refused}): {event.summary}"
    )
    body = {
        "text": text,
        "optimcp": {
            "ruleset_id": event.ruleset_id,
            "document_hash": event.document_hash,
            "broken_rules": event.broken_rules,
            "unevaluable": event.unevaluable,
            "correlation_id": event.correlation_id,
            "source": event.source,
            "refused": event.refused,
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("alert webhook failed: %s", exc)
        return False


def notify_violation_async(
    webhook_url: Optional[str],
    event: CheckEvent,
    *,
    timeout: float = 5.0,
) -> None:
    """Fire-and-forget webhook; never blocks the verify path."""
    if not webhook_url:
        return
    threading.Thread(
        target=notify_violation,
        args=(webhook_url, event),
        kwargs={"timeout": timeout},
        daemon=True,
        name="optimcp-alert",
    ).start()
