"""Tests that factory.py wires the static self-knowledge profile and the dynamic
per-conversation platform state into the agent's instructions."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from src.agent.platform_state import ConnectionSummary, UserPlatformState
from src.agent.tools.factory import base_instructions


def test_base_instructions_merges_system_prompt_and_static_profile():
    text = base_instructions()
    assert "You are Conduut" in text  # SYSTEM_PROMPT anchor
    assert "=== Platform self-knowledge ===" in text  # static profile anchor
    assert "batch" in text and "dashboard" in text  # capability anchors


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
