"""Shared API auth research cache — global, host-keyed, no secrets."""

# import src.store as _pkg_store  is used inside functions (not at top level)
# to avoid a circular-import AttributeError during module initialisation.
# Tests patch store._run / store.db / store._now_iso; the late binding means
# those patches are visible to the code paths here.
from dataclasses import dataclass

import src.store as _pkg_store


@dataclass
class ApiAuthCache:
    host: str
    scheme: str
    credential_type: str
    field_name: str
    value_prefix: str
    secret_fields: list[str]
    summary: str
    source_url: str
    confidence: str
    researched_at: str
    model: str


def _api_auth_cache_ref(host: str):
    return _pkg_store.db.collection("api_auth_cache").document(host)


async def save_api_auth_cache(
    host: str,
    *,
    scheme: str,
    credential_type: str,
    field_name: str,
    value_prefix: str,
    secret_fields: list[str],
    summary: str,
    source_url: str,
    confidence: str,
    model: str,
) -> ApiAuthCache:
    data = {
        "host": host,
        "scheme": scheme,
        "credential_type": credential_type,
        "field_name": field_name,
        "value_prefix": value_prefix,
        "secret_fields": list(secret_fields),
        "summary": summary,
        "source_url": source_url,
        "confidence": confidence,
        "researched_at": _pkg_store._now_iso(),
        "model": model,
    }
    await _pkg_store._run(lambda: _api_auth_cache_ref(host).set(data))
    return ApiAuthCache(**data)


async def get_api_auth_cache(host: str) -> ApiAuthCache | None:
    doc = await _pkg_store._run(lambda: _api_auth_cache_ref(host).get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return ApiAuthCache(
        host=data.get("host", host),
        scheme=data.get("scheme", ""),
        credential_type=data.get("credential_type", ""),
        field_name=data.get("field_name", ""),
        value_prefix=data.get("value_prefix", ""),
        secret_fields=list(data.get("secret_fields") or []),
        summary=data.get("summary", ""),
        source_url=data.get("source_url", ""),
        confidence=data.get("confidence", ""),
        researched_at=data.get("researched_at", ""),
        model=data.get("model", ""),
    )


async def delete_api_auth_cache(host: str) -> None:
    await _pkg_store._run(lambda: _api_auth_cache_ref(host).delete())
