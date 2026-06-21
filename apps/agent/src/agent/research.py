"""API auth research via a decoupled Gemini web-search (grounding) agent.

The research model is fixed and provider-independent of the conversational tier
(Anthropic/OpenAI/Gemini): a cheap Gemini model + grounding. Results are cached
in a shared, host-keyed Firestore collection (no secrets) so each API is
researched at most once. The actual grounding call lives behind
``_run_grounding_research`` so the cache/mapping logic is unit-testable.
"""

from datetime import datetime, timezone
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from src import store
from src.agent.credential_types import normalize_host
from src.config import settings

log = structlog.get_logger()

_SCHEME_TO_CREDENTIAL_TYPE = {
    "header": "httpHeaderAuth",
    "query": "httpQueryAuth",
    "basic": "httpBasicAuth",
    "custom": "httpCustomAuth",
}

_INSTRUCTIONS = (
    "You research how a third-party HTTP API authenticates. Use web search. Return: "
    "scheme (header | query | basic | custom | none | unknown); the exact header or "
    "query-parameter name (field_name); any value prefix such as 'Bearer ' (value_prefix); "
    "which secret fields the user must provide (secret_fields, e.g. ['key'] for an API key/"
    "token, ['user','password'] for basic auth, ['json'] for custom); a one-line summary; the "
    "source_url you used; and your confidence (high | medium | low). Use scheme='none' if the "
    "API needs no auth, and scheme='unknown' with confidence='low' if you cannot determine it. "
    "Never invent a key — only describe how auth works."
)


class AuthResearchResult(BaseModel):
    scheme: Literal["header", "query", "basic", "custom", "none", "unknown"] = "unknown"
    field_name: str = ""
    value_prefix: str = ""
    secret_fields: list[str] = Field(default_factory=list)
    summary: str = ""
    source_url: str = ""
    confidence: Literal["high", "medium", "low"] = "low"


def credential_type_for_scheme(scheme: str) -> str | None:
    """Map a research scheme to an n8n credential type (None for none/unknown)."""

    return _SCHEME_TO_CREDENTIAL_TYPE.get(scheme)


_agent = None


def _build_agent():
    from pydantic_ai import Agent
    from pydantic_ai.builtin_tools import WebSearchTool

    from src.agent.provider_factory import build_model
    from src.config import key_for_provider

    model = build_model("google", settings.research_model, key_for_provider("google"))
    return Agent(
        model,
        builtin_tools=[WebSearchTool()],
        output_type=AuthResearchResult,
        instructions=_INSTRUCTIONS,
    )


async def _run_grounding_research(query: str) -> AuthResearchResult:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    result = await _agent.run(query)
    return result.output


def _is_stale(researched_at: str, ttl_days: int) -> bool:
    try:
        when = datetime.fromisoformat(researched_at)
    except (ValueError, TypeError):
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - when).total_seconds() / 86400
    return age_days > ttl_days


def _result_from_cache(cached: store.ApiAuthCache) -> AuthResearchResult:
    return AuthResearchResult(
        scheme=cached.scheme or "unknown",
        field_name=cached.field_name,
        value_prefix=cached.value_prefix,
        secret_fields=list(cached.secret_fields),
        summary=cached.summary,
        source_url=cached.source_url,
        confidence=cached.confidence or "low",
    )


async def research_api_auth(host_or_api: str, *, ttl_days: int = 60) -> AuthResearchResult:
    """Research how an API authenticates, using the shared cache when fresh."""

    host = normalize_host(host_or_api) or str(host_or_api).strip().lower()
    cached = await store.get_api_auth_cache(host)
    if cached and not _is_stale(cached.researched_at, ttl_days):
        log.info("api_auth_cache_hit", host=host)
        return _result_from_cache(cached)

    result = await _run_grounding_research(
        f"How does the HTTP API at {host_or_api} authenticate requests?"
    )
    if result.confidence in ("high", "medium") and result.scheme != "unknown":
        await store.save_api_auth_cache(
            host,
            scheme=result.scheme,
            credential_type=credential_type_for_scheme(result.scheme) or "",
            field_name=result.field_name,
            value_prefix=result.value_prefix,
            secret_fields=result.secret_fields,
            summary=result.summary,
            source_url=result.source_url,
            confidence=result.confidence,
            model=settings.research_model,
        )
        log.info(
            "api_auth_researched",
            host=host,
            scheme=result.scheme,
            confidence=result.confidence,
        )
    return result
