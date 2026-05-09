"""Pydantic AI model/provider construction for user-selected LLM settings."""

from typing import Any

from pydantic_ai import Agent, UsageLimits
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


class UnsupportedReasoningEffortError(ValueError):
    """Raised when the selected model does not support a reasoning effort."""


SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic", "google", "groq", "openrouter"})
ReasoningEffort = str

_GPT5_BASE_EFFORTS = ("minimal", "low", "medium", "high")
_GPT5_1_EFFORTS = ("none", "low", "medium", "high")
_GPT5_FRONTIER_EFFORTS = ("none", "low", "medium", "high", "xhigh")
_GPT5_CODEX_EFFORTS = ("low", "medium", "high", "xhigh")
_O_SERIES_EFFORTS = ("low", "medium", "high")

_VERIFY_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "google": "gemini-2.0-flash",
    "groq": "llama-3.1-8b-instant",
    "openrouter": "openai/gpt-4o-mini",
}


def normalize_model_name(provider: str, model: str) -> str:
    """Remove legacy LiteLLM-style provider prefixes from stored model names."""

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


def reasoning_efforts_for_model(provider: str, model: str) -> tuple[ReasoningEffort, ...]:
    """Return selectable reasoning efforts for models Conduut knows how to configure."""

    provider_key = normalize_provider(provider)
    model_name = normalize_model_name(provider_key, model).lower()
    if provider_key != "openai":
        return ()

    if model_name.startswith(("gpt-5.2-codex", "gpt-5.3-codex")):
        return _GPT5_CODEX_EFFORTS
    if model_name.startswith(("gpt-5.2", "gpt-5.3", "gpt-5.4", "gpt-5.5")):
        if model_name.startswith("gpt-5.3-chat"):
            return ()
        return _GPT5_FRONTIER_EFFORTS
    if model_name.startswith("gpt-5.1"):
        return _GPT5_1_EFFORTS
    if model_name.startswith("gpt-5"):
        return _GPT5_BASE_EFFORTS
    if model_name.startswith(("o1", "o3", "o4")):
        return _O_SERIES_EFFORTS
    return ()


def normalize_reasoning_effort(
    provider: str, model: str, effort: str | None
) -> ReasoningEffort | None:
    if effort is None or effort == "":
        return None

    normalized = effort.strip().lower()
    supported = reasoning_efforts_for_model(provider, model)
    if normalized not in supported:
        raise UnsupportedReasoningEffortError(
            f"Reasoning effort '{effort}' is not supported for {provider}/{model}"
        )
    return normalized


def build_model_settings(
    provider: str, model: str, reasoning_effort: str | None
) -> dict[str, Any] | None:
    """Build provider-specific model settings for Pydantic AI."""

    effort = normalize_reasoning_effort(provider, model, reasoning_effort)
    if effort is None:
        return None
    if normalize_provider(provider) == "openai":
        return {"openai_reasoning_effort": effort}
    return None


def build_model(provider: str, model: str, api_key: str) -> Any:
    """Build a Pydantic AI model instance for a user provider connection."""

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


def verification_model(provider: str) -> str:
    provider_key = provider.strip().lower()
    return _VERIFY_MODELS.get(provider_key, "gpt-4o-mini")


async def verify_provider_connection(provider: str, api_key: str) -> None:
    """Run a tiny Pydantic AI request to verify provider credentials."""

    model = build_model(provider, verification_model(provider), api_key)
    agent = Agent(model, instructions="Reply with exactly: ok")
    await agent.run("hi", usage_limits=UsageLimits(request_limit=1))


def classify_provider_error(exc: Exception) -> str:
    """Map provider SDK errors to stable user-facing messages."""

    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)

    name = exc.__class__.__name__.lower()
    message = str(exc) or "Provider verification failed"
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
