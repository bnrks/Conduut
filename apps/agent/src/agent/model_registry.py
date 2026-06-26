"""Conduut-managed model registry: 3 tiers + a router, across named profiles.

The router classifies a request into a :class:`Tier`; each tier resolves to a
:class:`ModelChoice` (provider + model + thinking + usage limits). ``default`` is
the recommended profile; ``gpt`` is a one-switch all-OpenAI fallback. Every tier
keeps a GPT secondary for escalation/diversification — swapping a choice is a
one-line edit here. Selected via ``CONDUUT_MODEL_PROFILE``.
"""

from dataclasses import dataclass
from enum import Enum

from src.agent.provider_factory import SUPPORTED_PROVIDERS, ThinkingSpec
from src.config import settings


class Tier(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    thinking: ThinkingSpec
    # Generous defaults: a real build does search → schema → create → execute →
    # inspect (self-verify), which exhausted the old 12-round cap mid-verify.
    request_limit: int = 20
    tool_calls_limit: int = 48


@dataclass(frozen=True)
class TierConfig:
    primary: ModelChoice
    secondary: ModelChoice


@dataclass(frozen=True)
class ModelProfile:
    name: str
    router: ModelChoice
    tiers: dict[Tier, TierConfig]


# --- default profile (recommended) ---------------------------------------
# Router/Simple thinking OFF; Medium = Sonnet adaptive+medium; Hard = Gemini 3
# Pro thinking HIGH. Every secondary is a native-OpenAI GPT (no OpenRouter).
PROFILE_DEFAULT = ModelProfile(
    name="default",
    # Router on OpenAI: Google flash-lite proved flaky in this role (429 then 503),
    # and a router failure degrades every request to the MEDIUM fallback.
    router=ModelChoice(
        "openai", "gpt-5-mini", ThinkingSpec(enabled=False, effort="minimal"), request_limit=1
    ),
    tiers={
        Tier.SIMPLE: TierConfig(
            primary=ModelChoice(
                "anthropic", "claude-haiku-4-5-20251001", ThinkingSpec(enabled=False)
            ),
            secondary=ModelChoice(
                "openai", "gpt-5-mini", ThinkingSpec(enabled=False, effort="minimal")
            ),
        ),
        Tier.MEDIUM: TierConfig(
            primary=ModelChoice(
                "anthropic", "claude-sonnet-4-6", ThinkingSpec(enabled=True, effort="medium")
            ),
            secondary=ModelChoice("openai", "gpt-5.4", ThinkingSpec(enabled=True, effort="medium")),
        ),
        Tier.HARD: TierConfig(
            primary=ModelChoice(
                "google",
                "gemini-3.1-pro-preview",
                ThinkingSpec(enabled=True, effort="high"),
                request_limit=24,
                tool_calls_limit=56,
            ),
            secondary=ModelChoice(
                "openai",
                "gpt-5.4",
                ThinkingSpec(enabled=True, effort="high"),
                request_limit=24,
                tool_calls_limit=56,
            ),
        ),
    },
)

# --- gpt profile (one-switch all-OpenAI) ----------------------------------
# Primaries all OpenAI; secondaries mirror the default primaries for diversity.
PROFILE_GPT = ModelProfile(
    name="gpt",
    router=ModelChoice(
        "openai", "gpt-5-mini", ThinkingSpec(enabled=False, effort="minimal"), request_limit=1
    ),
    tiers={
        Tier.SIMPLE: TierConfig(
            primary=ModelChoice(
                "openai", "gpt-5-mini", ThinkingSpec(enabled=False, effort="minimal")
            ),
            secondary=ModelChoice(
                "anthropic", "claude-haiku-4-5-20251001", ThinkingSpec(enabled=False)
            ),
        ),
        Tier.MEDIUM: TierConfig(
            primary=ModelChoice("openai", "gpt-5.4", ThinkingSpec(enabled=True, effort="medium")),
            secondary=ModelChoice(
                "anthropic", "claude-sonnet-4-6", ThinkingSpec(enabled=True, effort="medium")
            ),
        ),
        Tier.HARD: TierConfig(
            primary=ModelChoice(
                "openai",
                "gpt-5.4",
                ThinkingSpec(enabled=True, effort="high"),
                request_limit=24,
                tool_calls_limit=56,
            ),
            secondary=ModelChoice(
                "google",
                "gemini-3.1-pro-preview",
                ThinkingSpec(enabled=True, effort="high"),
                request_limit=24,
                tool_calls_limit=56,
            ),
        ),
    },
)

# --- deepseek profile (cost bake-off) -------------------------------------
# All-DeepSeek via the first-party OpenAI-compatible API (provider "deepseek").
# Router + SIMPLE on V4 Flash (cheap/fast); MEDIUM + HARD on V4 Pro.
#
# Thinking rule: flash -> OFF, pro -> ON.
#  - flash OFF: the router uses structured output (forced tool_choice) which
#    DeepSeek thinking mode rejects (HTTP 400); SIMPLE stays fast/trivial.
#  - pro ON: with thinking OFF, DeepSeek narrates its reasoning as normal message
#    content (leaks into the chat bubble); with thinking ON that reasoning streams
#    as a ThinkingPart -> the frontend ThinkingPanel instead. The main agent uses
#    output_type=str (auto tool_choice), so thinking ON is safe there.
# Secondaries follow the same flash/pro rule (secondary is not yet used at
# runtime; escalation is Phase 2). See model-cost-research-2026-06 §7.
_DS_FLASH = "deepseek-v4-flash"
_DS_PRO = "deepseek-v4-pro"
_DS_OFF = ThinkingSpec(enabled=False)
_DS_ON = ThinkingSpec(enabled=True)

PROFILE_DEEPSEEK = ModelProfile(
    name="deepseek",
    router=ModelChoice("deepseek", _DS_FLASH, _DS_OFF, request_limit=1),
    tiers={
        Tier.SIMPLE: TierConfig(
            primary=ModelChoice("deepseek", _DS_FLASH, _DS_OFF),
            secondary=ModelChoice("deepseek", _DS_PRO, _DS_ON),
        ),
        Tier.MEDIUM: TierConfig(
            primary=ModelChoice("deepseek", _DS_PRO, _DS_ON),
            secondary=ModelChoice("deepseek", _DS_PRO, _DS_ON),
        ),
        Tier.HARD: TierConfig(
            primary=ModelChoice("deepseek", _DS_PRO, _DS_ON, request_limit=24, tool_calls_limit=56),
            secondary=ModelChoice(
                "deepseek", _DS_PRO, _DS_ON, request_limit=24, tool_calls_limit=56
            ),
        ),
    },
)

PROFILES: dict[str, ModelProfile] = {
    "default": PROFILE_DEFAULT,
    "gpt": PROFILE_GPT,
    "deepseek": PROFILE_DEEPSEEK,
}


def _validate_profiles() -> None:
    """Fail fast on a mis-authored profile (unknown provider / missing tier)."""

    for profile in PROFILES.values():
        choices = [profile.router]
        for tier in Tier:
            if tier not in profile.tiers:
                raise ValueError(f"profile '{profile.name}' missing tier {tier}")
            choices += [profile.tiers[tier].primary, profile.tiers[tier].secondary]
        for choice in choices:
            if choice.provider not in SUPPORTED_PROVIDERS:
                raise ValueError(
                    f"profile '{profile.name}' uses unsupported provider '{choice.provider}'"
                )


_validate_profiles()


def active_profile() -> ModelProfile:
    """Return the profile selected by CONDUUT_MODEL_PROFILE (default fallback)."""

    return PROFILES.get(settings.model_profile, PROFILE_DEFAULT)


def resolve(tier: Tier, *, secondary: bool = False) -> ModelChoice:
    """Resolve a tier to its primary (or secondary) model choice."""

    tier_config = active_profile().tiers[tier]
    return tier_config.secondary if secondary else tier_config.primary


def router_choice() -> ModelChoice:
    """Return the router/classifier model choice for the active profile."""

    return active_profile().router
