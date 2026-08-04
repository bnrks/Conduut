"""App connections, OAuth states, and platform action audit."""

from dataclasses import dataclass, field

import src.store as _pkg_store


@dataclass
class OAuthState:
    id: str
    user_id: str
    provider: str
    service: str
    code_verifier: str
    return_to: str
    expires_at: str
    used: bool
    instance_id: str = ""
    ownership: str = ""
    requested_capabilities: list[str] = field(default_factory=list)
    permission_pack: str | None = None


@dataclass
class AppConnection:
    id: str
    provider: str
    service: str
    account_email: str
    google_sub: str
    credential_type: str
    n8n_credential_id: str
    n8n_credential_name: str
    status: str
    scopes: list[str]
    created_at: str
    updated_at: str
    instance_id: str = ""
    capabilities: list[str] = field(default_factory=list)
    permission_packs: list[str] = field(default_factory=list)
    direct_api_enabled: bool = False
    encrypted_refresh_token: str = ""


def _connection_ref(user_id: str, connection_id: str, instance_id: str = ""):
    document_id = f"{instance_id}--{connection_id}" if instance_id else connection_id
    return _pkg_store._user_ref(user_id).collection("connections").document(document_id)


def _oauth_state_ref(state_id: str):
    return _pkg_store.db.collection("oauth_states").document(state_id)


async def save_oauth_state(
    state_id: str,
    *,
    user_id: str,
    provider: str,
    service: str,
    code_verifier: str,
    return_to: str,
    expires_at: str,
    requested_capabilities: list[str] | None = None,
    permission_pack: str | None = None,
    instance_id: str = "",
    ownership: str = "",
) -> OAuthState:
    data = {
        "user_id": user_id,
        "provider": provider,
        "service": service,
        "code_verifier": code_verifier,
        "return_to": return_to,
        "expires_at": expires_at,
        "used": False,
        "instance_id": instance_id,
        "ownership": ownership,
        "requested_capabilities": requested_capabilities or [],
        "permission_pack": permission_pack,
    }
    await _pkg_store._run(lambda: _oauth_state_ref(state_id).set(data))
    return OAuthState(id=state_id, **data)


async def get_oauth_state(state_id: str) -> OAuthState | None:
    doc = await _pkg_store._run(lambda: _oauth_state_ref(state_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return OAuthState(
        id=doc.id,
        user_id=data.get("user_id", ""),
        provider=data.get("provider", ""),
        service=data.get("service", ""),
        code_verifier=data.get("code_verifier", ""),
        return_to=data.get("return_to", "/dashboard/connections"),
        expires_at=data.get("expires_at", ""),
        used=bool(data.get("used", False)),
        instance_id=str(data.get("instance_id") or ""),
        ownership=str(data.get("ownership") or ""),
        requested_capabilities=list(data.get("requested_capabilities") or []),
        permission_pack=data.get("permission_pack"),
    )


async def mark_oauth_state_used(state_id: str) -> None:
    await _pkg_store._run(
        lambda: _oauth_state_ref(state_id).update({"used": True, "used_at": _pkg_store._now_iso()})
    )


async def get_connection(
    user_id: str,
    connection_id: str,
    *,
    instance_id: str | None = None,
) -> AppConnection | None:
    resolved_instance_id = instance_id
    if resolved_instance_id is None:
        active = await _pkg_store.get_active_n8n_instance(user_id)
        resolved_instance_id = active.id if active is not None else ""
    storage_instance_id = "" if resolved_instance_id == "shared_dev" else resolved_instance_id
    doc = await _pkg_store._run(
        lambda: _connection_ref(user_id, connection_id, storage_instance_id or "").get()
    )
    if not doc.exists and resolved_instance_id == "shared_dev":
        doc = await _pkg_store._run(lambda: _connection_ref(user_id, connection_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    connection = AppConnection(
        id=str(data.get("connection_id") or connection_id),
        provider=data.get("provider", ""),
        service=data.get("service", ""),
        account_email=data.get("account_email", ""),
        google_sub=data.get("google_sub", ""),
        credential_type=data.get("credential_type", ""),
        n8n_credential_id=data.get("n8n_credential_id", ""),
        n8n_credential_name=data.get("n8n_credential_name", ""),
        status=data.get("status", "error"),
        scopes=list(data.get("scopes") or []),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        instance_id=str(data.get("instance_id") or ""),
        capabilities=list(data.get("capabilities") or []),
        permission_packs=list(data.get("permission_packs") or []),
        direct_api_enabled=bool(data.get("direct_api_enabled", False)),
        encrypted_refresh_token=str(data.get("encrypted_refresh_token") or ""),
    )
    if (
        resolved_instance_id is not None
        and connection.instance_id != resolved_instance_id
        and not (resolved_instance_id == "shared_dev" and not connection.instance_id)
    ):
        return None
    return connection


async def list_connections(
    user_id: str,
    *,
    instance_id: str | None = None,
) -> list[AppConnection]:
    docs = await _pkg_store._run(
        lambda: list(_pkg_store._user_ref(user_id).collection("connections").stream())
    )
    connections: list[AppConnection] = []
    for doc in docs:
        data = doc.to_dict() or {}
        connections.append(
            AppConnection(
                id=str(data.get("connection_id") or doc.id),
                provider=data.get("provider", ""),
                service=data.get("service", ""),
                account_email=data.get("account_email", ""),
                google_sub=data.get("google_sub", ""),
                credential_type=data.get("credential_type", ""),
                n8n_credential_id=data.get("n8n_credential_id", ""),
                n8n_credential_name=data.get("n8n_credential_name", ""),
                status=data.get("status", "error"),
                scopes=list(data.get("scopes") or []),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                instance_id=str(data.get("instance_id") or ""),
                capabilities=list(data.get("capabilities") or []),
                permission_packs=list(data.get("permission_packs") or []),
                direct_api_enabled=bool(data.get("direct_api_enabled", False)),
                encrypted_refresh_token=str(data.get("encrypted_refresh_token") or ""),
            )
        )
    if instance_id is not None:
        connections = [
            item
            for item in connections
            if item.instance_id == instance_id
            or (instance_id == "shared_dev" and not item.instance_id)
        ]
    return connections


async def save_connection(
    user_id: str,
    connection_id: str,
    *,
    provider: str,
    service: str,
    account_email: str,
    google_sub: str,
    credential_type: str,
    n8n_credential_id: str,
    n8n_credential_name: str,
    scopes: list[str],
    capabilities: list[str] | None = None,
    permission_packs: list[str] | None = None,
    direct_api_enabled: bool = False,
    encrypted_refresh_token: str = "",
    instance_id: str = "",
) -> AppConnection:
    lookup_instance_id = instance_id or "shared_dev"
    existing = await get_connection(
        user_id,
        connection_id,
        instance_id=lookup_instance_id,
    )
    now = _pkg_store._now_iso()
    data = {
        "provider": provider,
        "connection_id": connection_id,
        "service": service,
        "account_email": account_email,
        "google_sub": google_sub,
        "credential_type": credential_type,
        "n8n_credential_id": n8n_credential_id,
        "n8n_credential_name": n8n_credential_name,
        "status": "connected",
        "scopes": scopes,
        "capabilities": capabilities or [],
        "permission_packs": permission_packs or [],
        "direct_api_enabled": direct_api_enabled,
        "encrypted_refresh_token": encrypted_refresh_token,
        "instance_id": instance_id,
        "created_at": existing.created_at if existing else now,
        "updated_at": now,
    }
    storage_instance_id = "" if lookup_instance_id == "shared_dev" else lookup_instance_id
    await _pkg_store._run(
        lambda: _connection_ref(user_id, connection_id, storage_instance_id).set(data)
    )
    return AppConnection(
        id=connection_id,
        **{key: value for key, value in data.items() if key != "connection_id"},
    )


async def delete_connection(
    user_id: str,
    connection_id: str,
    *,
    instance_id: str | None = None,
) -> AppConnection | None:
    existing = await get_connection(user_id, connection_id, instance_id=instance_id)
    if existing is None:
        return None
    storage_instance_id = "" if instance_id in (None, "shared_dev") else instance_id
    await _pkg_store._run(
        lambda: _connection_ref(user_id, connection_id, storage_instance_id or "").delete()
    )
    return existing


async def save_platform_action_audit(
    user_id: str,
    *,
    conversation_id: str | None,
    service: str,
    action: str,
    capability: str,
    status: str,
    target_resource: str | None = None,
    error: str | None = None,
) -> None:
    data = {
        "conversation_id": conversation_id,
        "service": service,
        "action": action,
        "capability": capability,
        "status": status,
        "target_resource": target_resource,
        "error": error,
        "created_at": _pkg_store._now_iso(),
    }
    await _pkg_store._run(
        lambda: _pkg_store._user_ref(user_id).collection("platform_action_audit").add(data)
    )
