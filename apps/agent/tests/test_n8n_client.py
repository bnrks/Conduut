"""Tests for n8n_client credential attachment wiring."""

from src import n8n_client


class _FakeResp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def json(self):
        return {}

    def raise_for_status(self):
        return None


def _patch(monkeypatch, node):
    captured: dict = {}

    async def fake_get_workflow(_wid):
        return {
            "name": "WF",
            "nodes": [node],
            "connections": {},
            "settings": {"executionOrder": "v1"},
        }

    async def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return _FakeResp()

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)
    return captured


async def test_attach_generic_auth_sets_authentication_params(monkeypatch):
    node = {
        "name": "HTTP Request",
        "type": "n8n-nodes-base.httpRequest",
        "parameters": {"url": "https://api.x.com"},
    }
    captured = _patch(monkeypatch, node)

    await n8n_client.attach_credential_to_workflow(
        "wf1",
        "HTTP Request",
        "httpHeaderAuth",
        "c1",
        "Cred",
        generic_auth_type="httpHeaderAuth",
    )

    put_node = captured["json"]["nodes"][0]
    assert put_node["parameters"]["authentication"] == "genericCredentialType"
    assert put_node["parameters"]["genericAuthType"] == "httpHeaderAuth"
    assert put_node["credentials"]["httpHeaderAuth"] == {"id": "c1", "name": "Cred"}


async def test_attach_without_generic_auth_keeps_parameters(monkeypatch):
    node = {
        "name": "Gmail",
        "type": "n8n-nodes-base.gmail",
        "parameters": {"resource": "message"},
    }
    captured = _patch(monkeypatch, node)

    await n8n_client.attach_credential_to_workflow("wf1", "Gmail", "gmailOAuth2", "c2", "Google")

    put_node = captured["json"]["nodes"][0]
    assert "authentication" not in put_node["parameters"]
    assert "genericAuthType" not in put_node["parameters"]
    assert put_node["credentials"]["gmailOAuth2"] == {"id": "c2", "name": "Google"}
