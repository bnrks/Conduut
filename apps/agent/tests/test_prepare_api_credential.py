"""Tests for prepare_api_credential_payload (research -> draft -> secret card)."""

import asyncio
from dataclasses import dataclass, field

from src.agent import research
from src.agent.schemas import AgentDeps
from src.agent.tools import credentials as cred_tools


@dataclass
class _Cred:
    id: str
    label: str
    credential_type: str
    host: str
    status: str = "ready"
    source_url: str = ""
    secret_fields: list = field(default_factory=list)
    auth_config: dict = field(default_factory=dict)
    n8n_credential_id: str = "n8n_x"
    n8n_credential_name: str = "X"
    pending_workflow_id: str = ""
    pending_node_name: str = ""


def _deps():
    return AgentDeps(user_id="u1", conversation_id="c1", event_queue=asyncio.Queue())


def _patch_research(monkeypatch, result):
    async def fake_research(_api, **_k):
        return result

    monkeypatch.setattr(cred_tools, "research_api_auth", fake_research)


async def test_prepare_existing_ready_credential(monkeypatch):
    async def fake_list(_uid):
        return [_Cred("c1", "API Ninjas", "httpHeaderAuth", "api.api-ninjas.com", status="ready")]

    monkeypatch.setattr(cred_tools.store, "list_custom_credentials", fake_list)

    res = await cred_tools.prepare_api_credential_payload(
        _deps(), "https://api.api-ninjas.com/v1/quotes"
    )
    assert res["status"] == "exists"


async def test_prepare_researches_and_creates_draft(monkeypatch):
    saved: dict = {}

    async def fake_list(_uid):
        return []

    async def fake_save(_uid, **kwargs):
        saved.update(kwargs)
        return _Cred(
            "draft1",
            kwargs["label"],
            kwargs["credential_type"],
            kwargs["host"],
            status="draft",
            source_url=kwargs["source_url"],
            secret_fields=kwargs["secret_fields"],
            auth_config=kwargs["auth_config"],
        )

    monkeypatch.setattr(cred_tools.store, "list_custom_credentials", fake_list)
    monkeypatch.setattr(cred_tools.store, "save_draft_credential", fake_save)
    _patch_research(
        monkeypatch,
        research.AuthResearchResult(
            scheme="header",
            field_name="X-Api-Key",
            value_prefix="",
            secret_fields=["key"],
            summary="X-Api-Key header",
            source_url="https://api-ninjas.com",
            confidence="high",
        ),
    )

    res = await cred_tools.prepare_api_credential_payload(
        _deps(), "https://api.api-ninjas.com/v1/quotes", workflow_id="wf1", node_name="HTTP"
    )

    assert res["status"] == "draft_created"
    assert res["draftId"] == "draft1"
    assert saved["credential_type"] == "httpHeaderAuth"
    assert saved["auth_config"]["field_name"] == "X-Api-Key"
    assert saved["pending_workflow_id"] == "wf1"
    card = res["card"]
    assert card.type == "credential_request"
    assert card.data.draftId == "draft1"
    assert card.data.host == "api.api-ninjas.com"
    assert [f.name for f in card.data.fields] == ["key"]
    assert card.data.allowedTypes == []  # pre-determined, no picker


async def test_prepare_low_confidence_needs_manual(monkeypatch):
    called = {"save": False}

    async def fake_list(_uid):
        return []

    async def fake_save(*_a, **_k):  # pragma: no cover - must not be called
        called["save"] = True

    monkeypatch.setattr(cred_tools.store, "list_custom_credentials", fake_list)
    monkeypatch.setattr(cred_tools.store, "save_draft_credential", fake_save)
    _patch_research(monkeypatch, research.AuthResearchResult(scheme="header", confidence="low"))

    res = await cred_tools.prepare_api_credential_payload(_deps(), "https://api.weird.test/x")
    assert res["status"] == "needs_manual"
    assert called["save"] is False


async def test_prepare_no_auth(monkeypatch):
    async def fake_list(_uid):
        return []

    monkeypatch.setattr(cred_tools.store, "list_custom_credentials", fake_list)
    _patch_research(monkeypatch, research.AuthResearchResult(scheme="none", confidence="high"))

    res = await cred_tools.prepare_api_credential_payload(_deps(), "https://public.test/x")
    assert res["status"] == "no_auth"
