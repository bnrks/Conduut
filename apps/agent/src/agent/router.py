"""Tier router: a cheap classifier model picks SIMPLE / MEDIUM / HARD.

Runs the active profile's router model (thinking OFF, one request) with a tiny
structured output. On any error it falls back to MEDIUM (the workhorse), so a
router outage never blocks a chat.
"""

from typing import Literal

import structlog
from pydantic import BaseModel
from pydantic_ai import Agent, UsageLimits

from src.agent.model_registry import Tier, router_choice
from src.agent.provider_factory import build_model, build_model_settings
from src.config import key_for_provider

log = structlog.get_logger()


class TierDecision(BaseModel):
    tier: Literal["simple", "medium", "hard"]
    reason: str


ROUTER_PROMPT = """You route a user's message to the right model tier for an \
agent that builds n8n automation workflows by calling tools. Pick exactly one tier:

- "simple": greetings, small talk, a single factual question, listing/inspecting \
existing workflows, or a trivial one-field change. No real build reasoning.
- "medium": the normal case — build/update/run a workflow, multi-node linear \
flows, AI-agent workflows, clarifying questions, single platform actions. \
DEFAULT TO "medium" whenever you are unsure.
- "hard": complex multi-branch logic (IF/Switch/Merge), multi-step ambiguous \
requirements, debugging a failed execution, or large/multi-trigger workflows.

Return the tier and a one-line reason. When in doubt, choose "medium"."""


def _build_router_agent() -> Agent[None, TierDecision]:
    """Build the classifier agent (no n8n tools) from the active router model."""

    choice = router_choice()
    model = build_model(choice.provider, choice.model, key_for_provider(choice.provider))
    return Agent(model, output_type=TierDecision, instructions=ROUTER_PROMPT, retries=1)


async def classify_tier(user_prompt: str, message_history: list | None = None) -> Tier:
    """Classify a request into a Tier; fall back to MEDIUM on any failure."""

    try:
        agent = _build_router_agent()
        choice = router_choice()
        result = await agent.run(
            user_prompt,
            message_history=message_history,
            model_settings=build_model_settings(choice.provider, choice.thinking),
            usage_limits=UsageLimits(request_limit=1),
        )
        tier = Tier(result.output.tier)
        log.info("router_classified", tier=tier.value, reason=result.output.reason)
        return tier
    except Exception as exc:
        log.warning("router_fallback", error=str(exc), error_type=type(exc).__name__)
        return Tier.MEDIUM
