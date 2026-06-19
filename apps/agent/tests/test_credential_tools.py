"""Tests for the credential agent tool payloads + readiness emit wiring."""

import asyncio
from dataclasses import dataclass

from src.agent.schemas import AgentDeps
from src.agent.tools import credentials as cred_tools
from src.agent.tools import readiness

_HTTP_SCHEMA = {
    "credentials": ["httpHeaderAuth", "httpBasicAuth", "httpQueryAuth", "httpCustomAuth"],
    "keyParameters": [{"name": "authentication", "default": "none"}],
}


@dataclass
class _Cred:
    id: str
    label: str
    credential_type: str
    host: str
    n8n_credential_id: str = "n8n_1"
    n8n_credential_name: str = "Cred"


def _deps():
    return AgentDeps(user_id="u1", conversation_id="c1", event_queue=asyncio.Queue())


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


async def test_list_credentials_payload_flags_host_match(monkeypatch):
    async def fake_list(_uid):
        return [
            _Cred("c1", "Stripe", "httpHeaderAuth", "api.stripe.com"),
            _Cred("c2", "Other", "httpHeaderAuth", "api.other.com"),
        ]

    monkeypatch.setattr(cred_tools.store, "list_custom_credentials", fake_list)
    res = await cred_tools.list_credentials_payload(_deps(), url="https://api.stripe.com/v1")
    by_id = {c["id"]: c for c in res["credentials"]}
    assert by_id["c1"]["matches_host"] is True
    assert by_id["c2"]["matches_host"] is False
    assert "n8n_credential_id" not in by_id["c1"]


async def test_attach_credential_payload_attaches_with_generic_auth(monkeypatch):
    calls: dict = {}

    async def fake_get(_uid, _cid):
        return _Cred("c1", "Stripe", "httpHeaderAuth", "api.stripe.com")

    async def fake_attach(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {}

    monkeypatch.setattr(cred_tools.store, "get_custom_credential", fake_get)
    monkeypatch.setattr(cred_tools.n8n_client, "attach_credential_to_workflow", fake_attach)

    res = await cred_tools.attach_credential_payload(_deps(), "wf1", "HTTP Request", "c1")
    assert res["success"] is True
    assert calls["kwargs"]["generic_auth_type"] == "httpHeaderAuth"


async def test_attach_credential_payload_unknown_id(monkeypatch):
    called = {"attach": False}

    async def fake_get(_uid, _cid):
        return None

    async def fake_attach(*args, **kwargs):
        called["attach"] = True

    monkeypatch.setattr(cred_tools.store, "get_custom_credential", fake_get)
    monkeypatch.setattr(cred_tools.n8n_client, "attach_credential_to_workflow", fake_attach)

    res = await cred_tools.attach_credential_payload(_deps(), "wf1", "n", "missing")
    assert "error" in res
    assert called["attach"] is False


async def test_emit_missing_credentials_returns_reuse_candidates(monkeypatch):
    monkeypatch.setattr(readiness.registry, "get_node_schema", lambda _t: _HTTP_SCHEMA)

    async def fake_list(_uid):
        return [_Cred("c1", "Stripe", "httpHeaderAuth", "api.stripe.com")]

    monkeypatch.setattr(readiness.store, "list_custom_credentials", fake_list)

    node = {
        "name": "HTTP Request",
        "type": "n8n-nodes-base.httpRequest",
        "parameters": {
            "url": "https://api.stripe.com/v1",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
        },
    }
    workflow = {"id": "wf1", "name": "WF", "nodes": [node]}
    deps = _deps()
    res = await readiness._emit_missing_credentials(_Ctx(deps), workflow)
    assert res["missing_count"] == 0
    assert len(res["reuse_candidates"]) == 1
    assert deps.awaiting_user_input is False  # suggestions never block on their own
