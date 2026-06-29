from types import SimpleNamespace

import pytest

from src.agent import platform_state
from src.agent.platform_state import (
    ConnectionSummary,
    CredentialSummary,
    UserPlatformState,
    WorkflowSummary,
    gather_user_state,
    platform_state_instructions,
    render_user_state,
)


@pytest.mark.asyncio
async def test_gather_is_best_effort_one_source_failing(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("firestore down")

    async def conns(*_a, **_k):
        return [SimpleNamespace(service="gmail", account_email="u@x.com", status="connected")]

    async def creds(*_a, **_k):
        return [
            SimpleNamespace(label="My OpenAI", credential_type="openAiApi", host="", status="ready")
        ]

    async def metas(*_a, **_k):
        return {}

    # list_workflows (the n8n source) blows up; the other three still populate.
    monkeypatch.setattr(platform_state.store, "list_connections", conns)
    monkeypatch.setattr(platform_state.store, "list_custom_credentials", creds)
    monkeypatch.setattr(platform_state.n8n_client, "list_workflows", boom)
    monkeypatch.setattr(platform_state.store, "get_all_workflow_metadata", metas)

    state = await gather_user_state("u1")

    assert state.connections[0].service == "gmail"
    assert state.credentials[0].label == "My OpenAI"
    assert state.workflows == []  # failed source -> empty, no raise


@pytest.mark.asyncio
async def test_gather_flags_runtime_inputs(monkeypatch):
    async def conns(*_a, **_k):
        return []

    async def creds(*_a, **_k):
        return []

    async def wfs(*_a, **_k):
        return [
            SimpleNamespace(id="wf_a", name="Daily BTC", active=True),
            SimpleNamespace(id="wf_b", name="Proposals", active=False),
        ]

    async def metas(*_a, **_k):
        return {"wf_b": SimpleNamespace(input_schema=[{"name": "company"}])}

    monkeypatch.setattr(platform_state.store, "list_connections", conns)
    monkeypatch.setattr(platform_state.store, "list_custom_credentials", creds)
    monkeypatch.setattr(platform_state.n8n_client, "list_workflows", wfs)
    monkeypatch.setattr(platform_state.store, "get_all_workflow_metadata", metas)

    state = await gather_user_state("u1")
    by_name = {w.name: w for w in state.workflows}
    assert by_name["Daily BTC"].has_runtime_inputs is False
    assert by_name["Proposals"].has_runtime_inputs is True


def test_render_empty_state():
    assert "Connected services: none yet." in render_user_state(UserPlatformState())


def test_render_populated_state_flags_and_no_secrets():
    state = UserPlatformState(
        connections=[
            ConnectionSummary(service="gmail", account_email="u@x.com", status="connected"),
            ConnectionSummary(service="sheets", account_email="u@x.com", status="expired"),
        ],
        credentials=[
            CredentialSummary(
                label="My OpenAI", credential_type="openAiApi", host="", status="ready"
            ),
            CredentialSummary(
                label="Stripe",
                credential_type="httpHeaderAuth",
                host="api.stripe.com",
                status="draft",
            ),
        ],
        workflows=[WorkflowSummary(name="Proposals", active=False, has_runtime_inputs=True)],
    )
    out = render_user_state(state)
    assert "gmail (u@x.com)" in out
    assert "needs reconnect" in out  # expired connection flagged
    assert "(incomplete)" in out  # draft credential flagged
    assert "takes input" in out  # runtime-input workflow flagged
    assert "'Proposals' (inactive, takes input)" in out


def test_platform_state_instructions_none_and_some():
    assert platform_state_instructions(None) == ""
    assert platform_state_instructions(UserPlatformState()).startswith("Current user state")
