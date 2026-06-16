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
