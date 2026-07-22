"""Middleware refuse/observe policy."""

from pathlib import Path

import pytest

from optimcp.check.rules import Rule
from optimcp.middleware.policy import VerificationRefused, apply_policy
from optimcp.monitor.models import RulesetRecord
from optimcp.monitor.service import MonitorService
from optimcp.monitor.store import MonitorStore


def _svc(tmp_path: Path, policy: str):
    store = MonitorStore(home=tmp_path)
    svc = MonitorService(store=store)
    svc.register_ruleset(
        RulesetRecord(
            id="t",
            policy=policy,  # type: ignore[arg-type]
            rules=[
                Rule.model_validate(
                    {
                        "id": "eq",
                        "lhs": {"kind": "ref", "path": "a"},
                        "op": "==",
                        "rhs": {"kind": "lit", "value": 1},
                    }
                )
            ],
        )
    )
    return svc


def test_observe_logs_and_passes(tmp_path: Path):
    svc = _svc(tmp_path, "observe")
    r = svc.verify("t", {"a": 99}, source="test", alert=False)
    apply_policy(r, raise_on_refuse=True)  # must not raise
    assert not r.refused
    assert len(svc.store.list_violations()) == 1


def test_refuse_raises(tmp_path: Path):
    svc = _svc(tmp_path, "refuse")
    r = svc.verify("t", {"a": 99}, source="test", alert=False)
    assert r.refused
    with pytest.raises(VerificationRefused):
        apply_policy(r, raise_on_refuse=True)


def test_verifying_openai_extract_and_refuse(tmp_path: Path, monkeypatch):
    from optimcp.middleware.openai_wrap import VerifyingOpenAI, extract_json_object

    assert extract_json_object('hello {"a": 1} bye') == {"a": 1}

    svc = _svc(tmp_path, "refuse")
    monkeypatch.setenv("OPTIMCP_HOME", str(tmp_path))

    class _Msg:
        content = '{"a": 99}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _FakeCompletions:
        def create(self, **kwargs):
            return _Resp()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    wrap = VerifyingOpenAI(
        _FakeClient(), ruleset_id="t", raise_on_refuse=True, prefer_remote=False
    )
    with pytest.raises(VerificationRefused):
        wrap.chat.completions.create(model="x", messages=[])
