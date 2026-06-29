"""Tests that factory.py wires the static self-knowledge profile and the dynamic
per-conversation platform state into the agent's instructions."""

import asyncio

from src.agent.platform_state import UserPlatformState
from src.agent.schemas import AgentDeps
from src.agent.tools.factory import base_instructions


def test_base_instructions_merges_system_prompt_and_static_profile():
    text = base_instructions()
    assert "You are Conduut" in text  # SYSTEM_PROMPT anchor
    assert "=== Platform self-knowledge ===" in text  # static profile anchor
    assert "batch" in text and "dashboard" in text  # capability anchors


def test_agent_deps_accepts_platform_state():
    state = UserPlatformState()
    deps = AgentDeps(
        user_id="u",
        conversation_id="c",
        event_queue=asyncio.Queue(),
        platform_state=state,
    )
    assert deps.platform_state is state
    # default stays None when not provided
    deps2 = AgentDeps(user_id="u", conversation_id="c", event_queue=asyncio.Queue())
    assert deps2.platform_state is None
