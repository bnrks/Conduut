"""Tests that factory.py wires the static self-knowledge profile and the dynamic
per-conversation platform state into the agent's instructions."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from src import store
from src.agent.platform_state import ConnectionSummary, UserPlatformState
from src.agent.setup_guide import resolve_setup_stage_request
from src.agent.tools import factory
from src.agent.tools.factory import base_instructions, create_setup_agent


def test_base_instructions_merges_system_prompt_and_static_profile():
    text = base_instructions()
    assert "You are Conduut" in text  # SYSTEM_PROMPT anchor
    assert "=== Platform self-knowledge ===" in text  # static profile anchor
    assert "batch" in text and "dashboard" in text  # capability anchors
    assert "get_automation_server_setup_step" in text
    assert "Configured workflow timezone: Europe/Istanbul" in text
    assert "Never speculate" in text


def test_base_instructions_uses_runtime_workflow_timezone(monkeypatch):
    monkeypatch.setattr(factory.settings, "workflow_timezone", "Asia/Tokyo")

    text = base_instructions()

    assert "Configured workflow timezone: Asia/Tokyo" in text
    assert "Configured workflow timezone: Europe/Istanbul" not in text


def test_workflow_result_exposes_effective_timezone():
    workflow = SimpleNamespace(id="wf1", name="Reminder", active=True)

    result = factory._workflow_result_with_readiness(
        workflow,
        {"missing_count": 0},
        timezone="Europe/Istanbul",
    )

    assert result["timezone"] == "Europe/Istanbul"


def test_existing_workflow_timezone_is_authoritative(monkeypatch):
    monkeypatch.setattr(factory.settings, "workflow_timezone", "Europe/Istanbul")

    assert factory._effective_workflow_timezone({"settings": {"timezone": "UTC"}}) == "UTC"
    assert factory._effective_workflow_timezone({"settings": None}) == "Europe/Istanbul"


def test_agent_deps_accepts_platform_state(make_agent_deps):
    state = UserPlatformState()
    deps = make_agent_deps(user_id="u", conversation_id="c", platform_state=state)
    assert deps.platform_state is state
    # default stays None when not provided
    deps2 = make_agent_deps(user_id="u", conversation_id="c")
    assert deps2.platform_state is None


@pytest.mark.asyncio
async def test_dynamic_instructions_reach_model_via_real_agent(make_agent_deps):
    """End-to-end seam: the @agent.instructions decorator on the REAL pydantic-ai Agent
    must forward the per-user platform state into the instructions the model receives.

    A rename/removal of the decorator, or a broken ctx.deps.platform_state read, would
    make this test fail while all other fakes-only tests stayed green.

    Mechanism: pydantic-ai appends @instructions return values to
    messages[0].instructions before passing the request to the model; we capture that
    field via FunctionModel to assert both layers (static profile + dynamic state) are
    present.
    """
    captured: dict = {}

    def _capture_model(messages: list, info: AgentInfo) -> ModelResponse:
        # messages[0] is the ModelRequest; .instructions holds the assembled prefix.
        captured["instructions"] = messages[0].instructions or ""
        return ModelResponse(parts=[TextPart("ok")])

    # The real create_agent registers n8n tools that touch registry/store/n8n_client
    # at *call time* (not at registration time), so patching the module-level registry
    # singleton is sufficient to keep the agent creation side-effect-free here.
    with patch("src.registry.registry", MagicMock()):
        from src.agent.tools.factory import create_agent  # import after patch

        agent = create_agent(FunctionModel(_capture_model))

    state = UserPlatformState(
        connections=[
            ConnectionSummary(service="gmail", account_email="u@x.com", status="connected")
        ]
    )
    deps = make_agent_deps(user_id="u", conversation_id="c", platform_state=state)

    await agent.run("hello", deps=deps)

    instructions = captured["instructions"]

    # Dynamic layer: the per-user state rendered by platform_state_instructions().
    assert "Current user state" in instructions, (
        "dynamic platform-state instructions missing from model input"
    )
    assert "gmail" in instructions, "connected gmail service missing from dynamic instructions"

    # Static layer: the system-prompt + static self-knowledge profile rendered by
    # base_instructions().  Both layers must survive to the model in the same run.
    assert "Platform self-knowledge" in instructions, (
        "static self-knowledge profile missing from model input"
    )
    assert "Automation server setup guardrails" in instructions
    assert "Configured workflow timezone: Europe/Istanbul" in instructions


@pytest.mark.asyncio
async def test_real_agent_registers_setup_tool(make_agent_deps):
    captured: dict = {}

    def _capture_model(messages: list, info: AgentInfo) -> ModelResponse:
        captured["tool_names"] = sorted(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    with patch("src.registry.registry", MagicMock()):
        from src.agent.tools.factory import create_agent

        agent = create_agent(FunctionModel(_capture_model))

    deps = make_agent_deps(user_id="u", conversation_id="c")
    await agent.run("hello", deps=deps)

    assert "get_automation_server_setup_step" in captured["tool_names"]


@pytest.mark.asyncio
async def test_setup_agent_registers_only_safe_setup_tools(make_agent_deps):
    captured: dict = {}

    def _capture_model(messages: list, info: AgentInfo) -> ModelResponse:
        captured["tool_names"] = sorted(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    agent = create_setup_agent(FunctionModel(_capture_model))
    deps = make_agent_deps(
        user_id="u",
        conversation_id="c",
        conversation_mode="automation-server-setup",
    )

    await agent.run("hello", deps=deps)

    assert captured["tool_names"] == [
        "get_automation_server_setup_step",
        "request_user_input",
    ]


def test_setup_stage_request_rejects_out_of_order_and_locked_progression():
    with pytest.raises(ValueError, match="next allowed stage is 'inspect_server'"):
        resolve_setup_stage_request(
            requested_stage="deploy_n8n",
            allowed_stage="inspect_server",
            stage_locked=False,
        )

    with pytest.raises(ValueError, match="Wait for the user's reply"):
        resolve_setup_stage_request(
            requested_stage="inspect_server",
            allowed_stage="inspect_server",
            stage_locked=True,
        )


@pytest.mark.asyncio
async def test_setup_stage_without_advance_repeats_current_locked_stage(
    monkeypatch, make_agent_deps
):
    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_setup",
            title="Setup",
            message_count=1,
            created_at="now",
            updated_at="now",
            conversation_mode="automation-server-setup",
            setup_next_stage="requirements",
            setup_stage_locked=True,
            setup_last_stage="requirements",
        )

    async def fail_save(*_args, **_kwargs):
        raise AssertionError("repeating the current locked stage should not rewrite state")

    monkeypatch.setattr(factory.store, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(factory.store, "save_setup_stage_state", fail_save)

    ctx = SimpleNamespace(
        deps=make_agent_deps(
            user_id="u",
            conversation_id="conv_setup",
            conversation_mode="automation-server-setup",
            setup_stage_reply_available=True,
        )
    )

    payload = await factory._setup_stage_payload_for_conversation(ctx, None, advance=False)
    assert payload["stage"] == "requirements"


@pytest.mark.asyncio
async def test_setup_stage_advance_denied_without_new_reply(monkeypatch, make_agent_deps):
    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_setup",
            title="Setup",
            message_count=1,
            created_at="now",
            updated_at="now",
            conversation_mode="automation-server-setup",
            setup_next_stage="requirements",
            setup_stage_locked=True,
            setup_last_stage="requirements",
        )

    monkeypatch.setattr(factory.store, "get_conversation", fake_get_conversation)

    ctx = SimpleNamespace(
        deps=make_agent_deps(
            user_id="u",
            conversation_id="conv_setup",
            conversation_mode="automation-server-setup",
            setup_stage_reply_available=False,
        )
    )

    with pytest.raises(ValueError, match="No new reply is available"):
        await factory._setup_stage_payload_for_conversation(ctx, None, advance=True)


@pytest.mark.asyncio
async def test_setup_stage_advance_moves_exactly_one_stage(monkeypatch, make_agent_deps):
    saved: dict = {}

    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_setup",
            title="Setup",
            message_count=2,
            created_at="now",
            updated_at="now",
            conversation_mode="automation-server-setup",
            setup_next_stage="requirements",
            setup_stage_locked=True,
            setup_last_stage="requirements",
        )

    async def fake_save(*_args, **kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(factory.store, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(factory.store, "save_setup_stage_state", fake_save)

    ctx = SimpleNamespace(
        deps=make_agent_deps(
            user_id="u",
            conversation_id="conv_setup",
            conversation_mode="automation-server-setup",
            setup_stage_reply_available=True,
        )
    )

    payload = await factory._setup_stage_payload_for_conversation(ctx, None, advance=True)
    assert payload["stage"] == "inspect_server"
    assert saved["next_stage"] == "inspect_server"
    assert saved["stage_locked"] is True
    assert saved["last_stage"] == "inspect_server"
