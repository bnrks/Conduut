import httpx
import litellm
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.auth import get_user_id
from src import store

_HARDCODED_MODELS: dict[str, list[dict]] = {
    "anthropic": [
        {"id": "claude-opus-4-6", "name": "Claude Opus 4.6"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
        {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku"},
    ],
    "google": [
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
        {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite"},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro"},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash"},
        {"id": "gemini-1.5-flash-8b", "name": "Gemini 1.5 Flash 8B"},
    ],
}

_OPENAI_COMPAT_BASE: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
}

_VERIFY_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "google": "gemini/gemini-2.0-flash",
    "groq": "groq/llama-3.1-8b-instant",
    "openrouter": "openrouter/openai/gpt-4o-mini",
}

router = APIRouter()


class LLMSettingsIn(BaseModel):
    provider: str
    model: str
    api_key: str


class ProviderIn(BaseModel):
    provider: str
    api_key: str


def _providers_response(providers: list[store.ProviderConnection]) -> dict:
    return {
        "providers": [
            {"provider": p.provider, "masked_key": p.masked_key}
            for p in providers
        ]
    }


# --- Active LLM Settings ---

@router.get("/settings/llm")
async def get_settings(request: Request):
    user_id = get_user_id(request)
    s = await store.get_llm_settings(user_id)
    if not s:
        raise HTTPException(status_code=404, detail="No LLM settings configured")
    return {"provider": s.provider, "model": s.model, "api_key_set": True}


@router.put("/settings/llm")
async def save_settings(request: Request, body: LLMSettingsIn):
    user_id = get_user_id(request)
    await store.save_llm_settings(user_id, body.provider, body.model, body.api_key)
    return {"provider": body.provider, "model": body.model, "api_key_set": True}


@router.delete("/settings/llm", status_code=204)
async def delete_settings(request: Request):
    user_id = get_user_id(request)
    await store.delete_llm_settings(user_id)


# --- Provider Connections ---

@router.get("/settings/llm/providers")
async def get_providers(request: Request):
    user_id = get_user_id(request)
    return _providers_response(await store.list_providers(user_id))


@router.put("/settings/llm/providers")
async def add_provider(request: Request, body: ProviderIn):
    user_id = get_user_id(request)
    providers = await store.save_provider(user_id, body.provider, body.api_key)
    return _providers_response(providers)


@router.get("/settings/llm/providers/{provider}/models")
async def get_provider_models(provider: str, request: Request):
    user_id = get_user_id(request)
    conn = await store.get_provider(user_id, provider)
    if not conn:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider in _HARDCODED_MODELS:
        return {"models": _HARDCODED_MODELS[provider]}

    if provider in _OPENAI_COMPAT_BASE:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{_OPENAI_COMPAT_BASE[provider]}/models",
                    headers={"Authorization": f"Bearer {conn.api_key}"},
                )
                r.raise_for_status()
            models = r.json().get("data", [])
            result = []
            for m in models:
                mid = m.get("id", "")
                if provider == "openai" and not any(mid.startswith(p) for p in ("gpt-", "o1", "o3", "o4")):
                    continue
                result.append({"id": mid, "name": mid})
            return {"models": sorted(result, key=lambda x: x["id"])}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not fetch models: {e}")

    if provider == "openrouter":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {conn.api_key}"},
                )
                r.raise_for_status()
            models = r.json().get("data", [])
            result = [{"id": m["id"], "name": m.get("name") or m["id"]} for m in models if m.get("id")]
            return {"models": sorted(result, key=lambda x: x["name"])}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Could not fetch models: {e}")

    return {"models": []}


@router.post("/settings/llm/providers/{provider}/verify")
async def verify_provider(provider: str, request: Request):
    user_id = get_user_id(request)
    conn = await store.get_provider(user_id, provider)
    if not conn:
        raise HTTPException(status_code=404, detail="Provider not found")

    model = _VERIFY_MODELS.get(provider, f"{provider}/gpt-4o-mini")
    try:
        await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            api_key=conn.api_key,
            max_tokens=1,
        )
        return {"valid": True, "provider": provider}
    except litellm.AuthenticationError:
        return {"valid": False, "provider": provider, "error": "Invalid API key"}
    except litellm.NotFoundError:
        return {"valid": False, "provider": provider, "error": "Model not found — key may still be valid"}
    except Exception as e:
        return {"valid": False, "provider": provider, "error": str(e)}


@router.delete("/settings/llm/providers/{provider}")
async def remove_provider(provider: str, request: Request):
    user_id = get_user_id(request)
    providers = await store.delete_provider(user_id, provider)
    if providers is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _providers_response(providers)
