"""Tests for the single-tenant credential-reuse bridge in readiness."""

from dataclasses import dataclass

from src.agent.tools import readiness


@dataclass
class FakeSummary:
    id: str


def _patch_n8n(monkeypatch, *, workflows, full_by_id, attached):
    async def _list_workflows():
        return workflows

    async def _get_workflow(wid):
        return full_by_id[wid]

    async def _attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached.append(
            {
                "workflow_id": workflow_id,
                "node": node_name,
                "type": credential_type,
                "id": credential_id,
                "name": credential_name,
            }
        )
        return {}

    monkeypatch.setattr(readiness.n8n_client, "list_workflows", _list_workflows)
    monkeypatch.setattr(readiness.n8n_client, "get_workflow", _get_workflow)
    monkeypatch.setattr(readiness.n8n_client, "attach_credential_to_workflow", _attach)


async def test_reuses_openai_credential_from_another_workflow(monkeypatch):
    attached: list[dict] = []
    other = {
        "nodes": [
            {
                "name": "OpenAI Chat Model",
                "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                "credentials": {"openAiApi": {"id": "cred123", "name": "OpenAi account"}},
            }
        ]
    }
    _patch_n8n(
        monkeypatch,
        workflows=[FakeSummary("other"), FakeSummary("new")],
        full_by_id={"other": other},
        attached=attached,
    )

    node = {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"}
    ok = await readiness._attach_existing_credential_if_available("new", node, "openAiApi")

    assert ok is True
    assert node["credentials"]["openAiApi"] == {"id": "cred123", "name": "OpenAi account"}
    assert attached and attached[0]["id"] == "cred123"


async def test_returns_false_when_no_matching_credential(monkeypatch):
    attached: list[dict] = []
    other = {"nodes": [{"name": "Set", "type": "n8n-nodes-base.set", "credentials": {}}]}
    _patch_n8n(
        monkeypatch,
        workflows=[FakeSummary("other")],
        full_by_id={"other": other},
        attached=attached,
    )

    node = {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"}
    ok = await readiness._attach_existing_credential_if_available("new", node, "openAiApi")

    assert ok is False
    assert attached == []


async def test_managed_google_types_are_skipped(monkeypatch):
    attached: list[dict] = []
    _patch_n8n(monkeypatch, workflows=[], full_by_id={}, attached=attached)

    node = {"name": "Gmail", "type": "n8n-nodes-base.gmail"}
    ok = await readiness._attach_existing_credential_if_available("new", node, "gmailOAuth2")

    assert ok is False
    assert attached == []


async def test_skips_the_workflow_being_built(monkeypatch):
    # Only the new workflow exists and it has no credential yet -> nothing to reuse.
    attached: list[dict] = []
    new_full = {
        "nodes": [{"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"}]
    }
    _patch_n8n(
        monkeypatch,
        workflows=[FakeSummary("new")],
        full_by_id={"new": new_full},
        attached=attached,
    )

    node = {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"}
    ok = await readiness._attach_existing_credential_if_available("new", node, "openAiApi")

    assert ok is False


# ---------------------------------------------------------------------------
# Custom HTTP credential host-matching (confirm-first)
# ---------------------------------------------------------------------------

_HTTP_SCHEMA = {
    "credentials": ["httpHeaderAuth", "httpBasicAuth", "httpQueryAuth", "httpCustomAuth"],
    "keyParameters": [{"name": "authentication", "default": "none"}],
}


@dataclass
class _CustomCred:
    id: str
    label: str
    credential_type: str
    host: str
    n8n_credential_id: str = "n8n_x"
    n8n_credential_name: str = "X"


def _http_node(generic="httpHeaderAuth", url="https://api.stripe.com/v1", credentials=None):
    params = {"url": url, "authentication": "genericCredentialType"}
    if generic:
        params["genericAuthType"] = generic
    node = {"name": "HTTP Request", "type": "n8n-nodes-base.httpRequest", "parameters": params}
    if credentials:
        node["credentials"] = credentials
    return node


def test_required_types_generic_credential_type_reads_subtype():
    node = _http_node(generic="httpHeaderAuth")
    assert readiness._required_credential_types_for_node(node, _HTTP_SCHEMA) == ["httpHeaderAuth"]


def test_required_types_generic_no_subtype_returns_supported():
    node = _http_node(generic=None)
    result = readiness._required_credential_types_for_node(node, _HTTP_SCHEMA)
    assert set(result) == {"httpHeaderAuth", "httpBasicAuth", "httpQueryAuth", "httpCustomAuth"}


async def test_readiness_http_host_match_yields_reuse_candidate(monkeypatch):
    monkeypatch.setattr(readiness.registry, "get_node_schema", lambda _t: _HTTP_SCHEMA)

    async def fake_list(_uid):
        return [_CustomCred("c1", "Stripe API", "httpHeaderAuth", "api.stripe.com")]

    monkeypatch.setattr(readiness.store, "list_custom_credentials", fake_list)

    workflow = {"id": "wf1", "name": "WF", "nodes": [_http_node()]}
    res = await readiness.analyze_workflow_readiness_payload(workflow, user_id="u1")

    assert res["missing_credentials"] == []
    assert len(res["reuse_candidates"]) == 1
    assert res["reuse_candidates"][0]["credentialId"] == "c1"
    assert res["reuse_candidates"][0]["nodeName"] == "HTTP Request"
    assert res["ready"] is False


async def test_readiness_http_no_match_emits_type_picker_card(monkeypatch):
    monkeypatch.setattr(readiness.registry, "get_node_schema", lambda _t: _HTTP_SCHEMA)

    async def fake_list(_uid):
        return []

    monkeypatch.setattr(readiness.store, "list_custom_credentials", fake_list)

    workflow = {"id": "wf1", "name": "WF", "nodes": [_http_node(generic=None)]}
    res = await readiness.analyze_workflow_readiness_payload(workflow, user_id="u1")

    assert res["reuse_candidates"] == []
    assert len(res["missing_credentials"]) == 1
    card = res["missing_credentials"][0]
    assert card.type == "credential_request"
    assert card.data.host == "api.stripe.com"
    assert len(card.data.allowedTypes) == 4


async def test_readiness_http_already_attached_is_ready(monkeypatch):
    monkeypatch.setattr(readiness.registry, "get_node_schema", lambda _t: _HTTP_SCHEMA)

    async def fake_list(_uid):  # pragma: no cover - should not be needed
        return []

    monkeypatch.setattr(readiness.store, "list_custom_credentials", fake_list)

    node = _http_node(credentials={"httpHeaderAuth": {"id": "c1", "name": "Stripe"}})
    workflow = {"id": "wf1", "name": "WF", "nodes": [node]}
    res = await readiness.analyze_workflow_readiness_payload(workflow, user_id="u1")

    assert res["missing_credentials"] == []
    assert res["reuse_candidates"] == []
    assert res["ready"] is True
