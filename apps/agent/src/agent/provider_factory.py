"""Pydantic AI model construction for Conduut-managed models.

Conduut holds the provider API keys; the per-tier model + thinking config is
chosen by ``agent/model_registry.py`` and ``agent/router.py``. ``build_model``
builds the Pydantic AI model object from a Conduut key; ``build_model_settings``
turns a tier's :class:`ThinkingSpec` into provider-specific ``model_settings``.
"""

from dataclasses import dataclass
from typing import Any

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider


class UnsupportedProviderError(ValueError):
    """Raised when the selected provider is not supported by Conduut."""


SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic", "google", "groq", "openrouter"})


@dataclass(frozen=True)
class ThinkingSpec:
    """Per-tier reasoning/thinking configuration, resolved by the model registry.

    ``enabled`` governs thinking on/off for Anthropic and Google. ``effort`` is
    the universal depth knob: ``anthropic_effort`` / Google ``thinking_level`` /
    ``openai_reasoning_effort``. ``budget`` is a Google-only alternative to a
    level. For OpenAI, ``effort`` is passed through verbatim — the registry sets
    a valid value per model, including the "off" value (e.g. "minimal"/"none").
    """

    enabled: bool
    effort: str | None = None
    budget: int | None = None


def normalize_model_name(provider: str, model: str) -> str:
    """Remove legacy LiteLLM-style provider prefixes from model names."""

    provider_key = provider.strip().lower()
    model_name = model.strip()

    prefixes: dict[str, tuple[str, ...]] = {
        "google": ("gemini/", "google/"),
        "groq": ("groq/",),
        "openrouter": ("openrouter/",),
        "openai": ("openai/",),
        "anthropic": ("anthropic/",),
    }

    for prefix in prefixes.get(provider_key, ()):
        if model_name.startswith(prefix):
            return model_name[len(prefix) :]
    return model_name


def normalize_provider(provider: str) -> str:
    """Normalize and validate a Conduut-supported provider key."""

    provider_key = provider.strip().lower()
    if provider_key not in SUPPORTED_PROVIDERS:
        raise UnsupportedProviderError(f"Unsupported provider: {provider}")
    return provider_key


def build_model_settings(provider: str, thinking: ThinkingSpec | None) -> dict[str, Any] | None:
    """Build provider-specific Pydantic AI ``model_settings`` from a ThinkingSpec.

    Shapes are authored here (and asserted in test_thinking_builder) per the
    installed pydantic-ai; never derive them from the model name at runtime.
    """

    if thinking is None:
        return None

    provider_key = normalize_provider(provider)

    if provider_key == "anthropic":
        if not thinking.enabled:
            return {"anthropic_thinking": {"type": "disabled"}}
        result: dict[str, Any] = {"anthropic_thinking": {"type": "adaptive"}}
        if thinking.effort:
            result["anthropic_effort"] = thinking.effort
        return result

    if provider_key == "google":
        if not thinking.enabled:
            return {"google_thinking_config": {"thinking_budget": 0}}
        config: dict[str, Any] = {"include_thoughts": True}
        if thinking.effort:
            config["thinking_level"] = thinking.effort.upper()
        elif thinking.budget is not None:
            config["thinking_budget"] = thinking.budget
        return {"google_thinking_config": config}

    if provider_key == "openai":
        if thinking.effort:
            return {"openai_reasoning_effort": thinking.effort}
        return None

    # groq / openrouter: no thinking settings
    return None


def build_model(provider: str, model: str, api_key: str) -> Any:
    """Build a Pydantic AI model instance from a Conduut-managed API key."""

    provider_key = normalize_provider(provider)
    model_name = normalize_model_name(provider_key, model)

    match provider_key:
        case "openai":
            return OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key))
        case "anthropic":
            return AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))
        case "google":
            return GoogleModel(model_name, provider=GoogleProvider(api_key=api_key))
        case "groq":
            return GroqModel(model_name, provider=GroqProvider(api_key=api_key))
        case "openrouter":
            return OpenRouterModel(model_name, provider=OpenRouterProvider(api_key=api_key))
        case _:
            raise UnsupportedProviderError(f"Unsupported provider: {provider}")


def classify_provider_error(exc: Exception) -> str:
    """Map provider SDK errors to stable user-facing messages."""

    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)

    name = exc.__class__.__name__.lower()
    message = str(exc) or "Provider request failed"
    message_lower = message.lower()

    if status in (401, 403) or "auth" in name or "unauthorized" in message_lower:
        return "Invalid API key"
    if status == 404 or "notfound" in name or "not found" in message_lower:
        return "Model not found — key may still be valid"
    if (
        "insufficient_quota" in message_lower
        or "exceeded your current quota" in message_lower
        or "billing" in message_lower
        or "quota" in message_lower
    ):
        return "Provider quota exceeded. Check billing or choose another provider/model."
    if status == 429 or "rate" in name or "rate limit" in message_lower:
        return "Rate limit exceeded — key may still be valid"
    return message[:300]
