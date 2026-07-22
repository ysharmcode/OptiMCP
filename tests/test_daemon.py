"""Daemon HTTP surface: auth, check, refuse, violations."""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from optimcp.check.rules import Rule
from optimcp.daemon.app import create_app
from optimcp.daemon.auth import AuthError, auth_required
from optimcp.monitor.models import DaemonConfig, RulesetRecord
from optimcp.monitor.service import MonitorService
from optimcp.monitor.store import MonitorStore


@pytest.fixture
def home(tmp_path: Path):
    return tmp_path


def _ruleset(policy="observe"):
    return RulesetRecord(
        id="inv",
        policy=policy,
        rules=[
            Rule.model_validate(
                {
                    "id": "eq",
                    "lhs": {"kind": "ref", "path": "a"},
                    "op": "==",
                    "rhs": {"kind": "ref", "path": "b"},
                }
            )
        ],
    )


def _app(home: Path, *, token="secret", allow_unauth=False, host="127.0.0.1", monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.delenv("OPTIMCP_DAEMON_TOKEN", raising=False)
        if token and not allow_unauth:
            monkeypatch.setenv("OPTIMCP_DAEMON_TOKEN", token)
    store = MonitorStore(home=home)
    cfg = DaemonConfig(
        daemon_token=None if allow_unauth else token,
        allow_unauthenticated_localhost=allow_unauth,
    )
    store.save_config(cfg)
    svc = MonitorService(store=store)
    svc.register_ruleset(_ruleset())
    return create_app(
        service=svc,
        config=cfg,
        host=host,
        allow_unauthenticated_localhost=allow_unauth,
    )


def test_health_unauthenticated(home: Path, monkeypatch):
    c = TestClient(_app(home, monkeypatch=monkeypatch))
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_v1_requires_token(home: Path, monkeypatch):
    c = TestClient(_app(home, monkeypatch=monkeypatch))
    assert c.get("/v1/rulesets").status_code == 401
    assert c.get("/v1/rulesets", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.get("/v1/rulesets", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    assert ok.json()["rulesets"][0]["id"] == "inv"


def test_check_and_violations(home: Path, monkeypatch):
    headers = {"Authorization": "Bearer secret"}
    c = TestClient(_app(home, monkeypatch=monkeypatch))
    good = c.post(
        "/v1/check",
        headers=headers,
        json={"ruleset_id": "inv", "document": {"a": 1, "b": 1}},
    )
    assert good.status_code == 200
    assert good.json()["report"]["consistent"] is True

    bad = c.post(
        "/v1/check",
        headers=headers,
        json={"ruleset_id": "inv", "document": {"a": 1, "b": 2}},
    )
    assert bad.status_code == 200
    assert bad.json()["report"]["consistent"] is False

    viol = c.get("/v1/violations", headers=headers)
    assert viol.status_code == 200
    assert len(viol.json()["violations"]) == 1


def test_refuse_returns_422(home: Path, monkeypatch):
    monkeypatch.delenv("OPTIMCP_DAEMON_TOKEN", raising=False)
    monkeypatch.setenv("OPTIMCP_DAEMON_TOKEN", "secret")
    store = MonitorStore(home=home)
    cfg = DaemonConfig(daemon_token="secret")
    store.save_config(cfg)
    svc = MonitorService(store=store)
    svc.register_ruleset(_ruleset(policy="refuse"))
    c = TestClient(create_app(service=svc, config=cfg, host="127.0.0.1"))
    headers = {"Authorization": "Bearer secret"}
    bad = c.post(
        "/v1/ingest",
        headers=headers,
        json={"ruleset_id": "inv", "document": {"a": 1, "b": 9}},
    )
    assert bad.status_code == 422
    assert bad.json()["refused"] is True


def test_put_ruleset_authenticated(home: Path, monkeypatch):
    headers = {"Authorization": "Bearer secret"}
    c = TestClient(_app(home, monkeypatch=monkeypatch))
    body = _ruleset().model_dump(mode="json")
    body["id"] = "other"
    r = c.put("/v1/rulesets/other", headers=headers, json=body)
    assert r.status_code == 200
    assert r.json()["id"] == "other"


def test_auth_required_non_loopback_without_token(monkeypatch):
    monkeypatch.delenv("OPTIMCP_DAEMON_TOKEN", raising=False)
    with pytest.raises(AuthError):
        auth_required("0.0.0.0", DaemonConfig(), allow_unauthenticated_localhost=True)


def test_auth_loopback_opt_out(monkeypatch):
    monkeypatch.delenv("OPTIMCP_DAEMON_TOKEN", raising=False)
    required, token = auth_required(
        "127.0.0.1",
        DaemonConfig(),
        allow_unauthenticated_localhost=True,
    )
    assert required is False
    assert token is None


def test_non_loopback_bind_requires_token_on_http(home: Path, monkeypatch):
    """HTTP auth path on non-loopback bind, not just startup auth_required()."""
    c = TestClient(_app(home, host="0.0.0.0", monkeypatch=monkeypatch))
    payload = {"ruleset_id": "inv", "document": {"a": 1, "b": 1}}
    assert c.post("/v1/check", json=payload).status_code == 401
    assert c.post("/v1/ingest", json=payload).status_code == 401
    headers = {"Authorization": "Bearer secret"}
    assert c.post("/v1/check", headers=headers, json=payload).status_code == 200


def test_rate_limit_check_and_ingest(home: Path, monkeypatch):
    monkeypatch.setenv("OPTIMCP_RATE_LIMIT_PER_MINUTE", "2")
    headers = {"Authorization": "Bearer secret"}
    c = TestClient(_app(home, monkeypatch=monkeypatch))
    payload = {"ruleset_id": "inv", "document": {"a": 1, "b": 1}}
    assert c.post("/v1/check", headers=headers, json=payload).status_code == 200
    assert c.post("/v1/ingest", headers=headers, json=payload).status_code == 200
    limited = c.post("/v1/check", headers=headers, json=payload)
    assert limited.status_code == 429
    assert limited.json()["detail"]["error"] == "rate_limit_exceeded"


def test_dashboard_requires_auth(home: Path, monkeypatch):
    c = TestClient(_app(home, monkeypatch=monkeypatch))
    assert c.get("/dashboard").status_code == 401
    ok = c.get("/dashboard", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    assert "OptiMCP" in ok.text
