import pytest

from src.agent.provider_factory import (
    UnsupportedProviderError,
    UnsupportedReasoningEffortError,
    build_model,
    build_model_settings,
    classify_provider_error,
    normalize_model_name,
    normalize_provider,
    normalize_reasoning_effort,
    reasoning_efforts_for_model,
)


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("google", "gemini/gemini-2.0-flash", "gemini-2.0-flash"),
        ("google", "google/gemini-2.0-flash", "gemini-2.0-flash"),
        ("groq", "groq/llama-3.1-8b-instant", "llama-3.1-8b-instant"),
        ("openrouter", "openrouter/openai/gpt-4o-mini", "openai/gpt-4o-mini"),
        ("openai", "openai/gpt-4o-mini", "gpt-4o-mini"),
        ("anthropic", "anthropic/claude-haiku-4-5-20251001", "claude-haiku-4-5-20251001"),
    ],
)
def test_normalize_model_name(provider: str, model: str, expected: str):
    assert normalize_model_name(provider, model) == expected


@pytest.mark.parametrize(
    ("provider", "model", "class_name", "normalized"),
    [
        ("openai", "gpt-4o-mini", "OpenAIChatModel", "gpt-4o-mini"),
        ("anthropic", "claude-haiku-4-5-20251001", "AnthropicModel", "claude-haiku-4-5-20251001"),
        ("google", "gemini/gemini-2.0-flash", "GoogleModel", "gemini-2.0-flash"),
        ("groq", "groq/llama-3.1-8b-instant", "GroqModel", "llama-3.1-8b-instant"),
        ("openrouter", "openrouter/openai/gpt-4o-mini", "OpenRouterModel", "openai/gpt-4o-mini"),
    ],
)
def test_build_model_uses_expected_provider_classes(
    provider: str, model: str, class_name: str, normalized: str
):
    built = build_model(provider, model, "test-key")

    assert built.__class__.__name__ == class_name
    assert built.model_name == normalized


def test_build_model_rejects_unsupported_provider():
    with pytest.raises(UnsupportedProviderError):
        build_model("custom", "gpt-4o-mini", "test-key")


def test_normalize_provider_rejects_unsupported_provider():
    with pytest.raises(UnsupportedProviderError):
        normalize_provider("custom")


def test_normalize_provider_lowercases_supported_provider():
    assert normalize_provider("OpenAI") == "openai"


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o", ()),
        ("gpt-5", ("minimal", "low", "medium", "high")),
        ("gpt-5.1", ("none", "low", "medium", "high")),
        ("gpt-5.4-mini", ("none", "low", "medium", "high", "xhigh")),
        ("gpt-5.3-codex", ("low", "medium", "high", "xhigh")),
    ],
)
def test_reasoning_efforts_for_openai_models(model: str, expected: tuple[str, ...]):
    assert reasoning_efforts_for_model("openai", model) == expected


def test_normalize_reasoning_effort_rejects_unsupported_model():
    with pytest.raises(UnsupportedReasoningEffortError):
        normalize_reasoning_effort("openai", "gpt-4o", "medium")


def test_build_model_settings_uses_openai_reasoning_effort():
    assert build_model_settings("openai", "gpt-5", "medium") == {
        "openai_reasoning_effort": "medium"
    }


def test_classify_provider_error_reports_quota_separately_from_rate_limit():
    class QuotaError(Exception):
        status_code = 429

    error = QuotaError(
        "status_code: 429, body: {'code': 'insufficient_quota', "
        "'message': 'You exceeded your current quota, please check your plan and billing details.'}"
    )

    assert (
        classify_provider_error(error)
        == "Provider quota exceeded. Check billing or choose another provider/model."
    )
