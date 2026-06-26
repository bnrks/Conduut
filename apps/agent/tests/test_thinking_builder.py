"""Tests for provider-aware thinking model_settings (build_model_settings).

Exact dict shapes verified against the installed pydantic-ai 1.88.0:
- Anthropic: anthropic_thinking ({type: adaptive|disabled}) + anthropic_effort.
- Google:    google_thinking_config (thinking_level for gemini-3, thinking_budget otherwise).
- OpenAI:    openai_reasoning_effort.
"""

from src.agent.provider_factory import ThinkingSpec, build_model_settings


def test_none_thinking_returns_none():
    assert build_model_settings("anthropic", None) is None


def test_anthropic_adaptive_with_effort():
    spec = ThinkingSpec(enabled=True, effort="medium")
    assert build_model_settings("anthropic", spec) == {
        "anthropic_thinking": {"type": "adaptive"},
        "anthropic_effort": "medium",
    }


def test_anthropic_disabled():
    assert build_model_settings("anthropic", ThinkingSpec(enabled=False)) == {
        "anthropic_thinking": {"type": "disabled"},
    }


def test_google_thinking_level_high():
    spec = ThinkingSpec(enabled=True, effort="high")
    assert build_model_settings("google", spec) == {
        "google_thinking_config": {"include_thoughts": True, "thinking_level": "HIGH"},
    }


def test_google_disabled_zero_budget():
    assert build_model_settings("google", ThinkingSpec(enabled=False)) == {
        "google_thinking_config": {"thinking_budget": 0},
    }


def test_google_enabled_with_budget():
    spec = ThinkingSpec(enabled=True, budget=8192)
    assert build_model_settings("google", spec) == {
        "google_thinking_config": {"include_thoughts": True, "thinking_budget": 8192},
    }


def test_openai_effort_passed_through():
    assert build_model_settings("openai", ThinkingSpec(enabled=True, effort="medium")) == {
        "openai_reasoning_effort": "medium"
    }


def test_openai_off_uses_minimal_effort():
    assert build_model_settings("openai", ThinkingSpec(enabled=False, effort="minimal")) == {
        "openai_reasoning_effort": "minimal"
    }


def test_groq_has_no_thinking_settings():
    assert build_model_settings("groq", ThinkingSpec(enabled=True)) is None


def test_deepseek_disabled_sends_thinking_off_extra_body():
    # DeepSeek V4 needs thinking explicitly off, else forced tool_choice 400s.
    assert build_model_settings("deepseek", ThinkingSpec(enabled=False)) == {
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_deepseek_enabled_sends_no_settings():
    assert build_model_settings("deepseek", ThinkingSpec(enabled=True)) is None
