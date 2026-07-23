"""Monitor store + service."""

from pathlib import Path

from optimcp.check.rules import Rule
from optimcp.monitor.hashing import document_hash
from optimcp.monitor.models import RulesetRecord
from optimcp.monitor.service import MonitorService, RulesetNotFound
from optimcp.monitor.store import MonitorStore
import pytest


def _invoice_ruleset(policy="observe"):
    return RulesetRecord(
        id="invoices",
        policy=policy,
        rules=[
            Rule.model_validate(
                {
                    "id": "subtotal_foots",
                    "lhs": {"kind": "ref", "path": "subtotal"},
                    "op": "==",
                    "rhs": {"kind": "agg", "fn": "sum", "path": "line_items[*].amount"},
                }
            )
        ],
    )


def test_register_verify_and_violation_append(tmp_path: Path):
    store = MonitorStore(home=tmp_path)
    svc = MonitorService(store=store)
    svc.register_ruleset(_invoice_ruleset())

    good = {"subtotal": 30, "line_items": [{"amount": 10}, {"amount": 20}]}
    bad = {"subtotal": 20, "line_items": [{"amount": 10}, {"amount": 20}]}

    ok = svc.verify("invoices", good, source="test", alert=False)
    assert ok.report.consistent
    assert not ok.refused
    assert ok.document_hash == document_hash(good)

    bad_r = svc.verify("invoices", bad, source="test", alert=False)
    assert not bad_r.report.consistent
    assert not bad_r.refused  # observe

    viol = store.list_violations()
    assert len(viol) == 1
    assert viol[0].document_hash == document_hash(bad)

    # hash continuity: same semantic doc, different key order
    reordered = {"line_items": [{"amount": 10}, {"amount": 20}], "subtotal": 20}
    assert document_hash(reordered) == viol[0].document_hash


def test_refuse_policy(tmp_path: Path):
    store = MonitorStore(home=tmp_path)
    svc = MonitorService(store=store)
    svc.register_ruleset(_invoice_ruleset(policy="refuse"))
    bad = {"subtotal": 1, "line_items": [{"amount": 10}]}
    r = svc.verify("invoices", bad, source="test", alert=False)
    assert r.refused
    assert store.list_violations()[0].refused


def test_missing_ruleset(tmp_path: Path):
    svc = MonitorService(store=MonitorStore(home=tmp_path))
    with pytest.raises(RulesetNotFound):
        svc.verify("nope", {}, source="test", alert=False)


def test_version_bumps_on_reregister(tmp_path: Path):
    store = MonitorStore(home=tmp_path)
    svc = MonitorService(store=store)
    a = svc.register_ruleset(_invoice_ruleset())
    b = svc.register_ruleset(_invoice_ruleset())
    assert b.version == a.version + 1


def test_sqlite_wal_mode(tmp_path: Path):
    store = MonitorStore(home=tmp_path)
    with store._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_alert_webhook_does_not_block_verify(tmp_path: Path, monkeypatch):
    import time

    def slow_notify(*args, **kwargs):
        time.sleep(2.0)
        return False

    monkeypatch.setattr("optimcp.monitor.service.notify_violation", slow_notify)
    store = MonitorStore(home=tmp_path)
    cfg = store.load_config().model_copy(
        update={"alert_webhook_url": "http://example.invalid/hook"}
    )
    store.save_config(cfg)
    svc = MonitorService(store=store)
    svc.register_ruleset(_invoice_ruleset())
    bad = {"subtotal": 1, "line_items": [{"amount": 10}]}
    started = time.monotonic()
    svc.verify("invoices", bad, source="test", alert=True)
    assert time.monotonic() - started < 0.5
