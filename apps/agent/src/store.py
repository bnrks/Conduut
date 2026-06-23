"""Firestore tabanlı store. Tüm sync Firestore çağrıları asyncio.to_thread ile sarılır."""

# TODO : BURASI REFACTOR EDİLECEK ÇOK UZUN DOSYA.
import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.firebase import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Dataclass'lar (route'larda kullanılır)
# ---------------------------------------------------------------------------


@dataclass
class WorkflowCredential:
    id: str
    service: str
    credential_type: str
    credential_name: str
    n8n_credential_id: str
    node_name: str
    workflow_id: str
    created_at: str


@dataclass
class CustomCredential:
    """Reusable custom (HTTP) credential the user manages through Conduut.

    The secret lives only in n8n; this record is the non-secret pointer +
    host hint used for agent host-matching and dashboard listing.
    """

    id: str
    label: str
    credential_type: str
    host: str
    n8n_credential_id: str
    n8n_credential_name: str
    created_at: str
    updated_at: str
    # Draft support: an agent-prepared credential whose secret the user fills
    # later. status="draft" -> no n8n credential yet; "ready" -> finalized.
    status: str = "ready"
    auth_config: dict = field(default_factory=dict)
    secret_fields: list[str] = field(default_factory=list)
    source_url: str = ""
    confidence: str = ""
    pending_workflow_id: str = ""
    pending_node_name: str = ""


@dataclass
class WorkflowMetadata:
    workflow_id: str
    input_schema: list[dict]
    created_at: str
    updated_at: str
    resources: dict = field(default_factory=dict)


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
    capabilities: list[str] = field(default_factory=list)
    permission_packs: list[str] = field(default_factory=list)
    direct_api_enabled: bool = False
    encrypted_refresh_token: str = ""


@dataclass
class Message:
    id: str
    role: str
    content: str
    created_at: str
    provider: str | None = None
    model: str | None = None
    tier: str | None = None
    attachments: list[dict] | None = None


@dataclass
class Conversation:
    id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    messages: list[Message] | None = None


@dataclass
class ArtifactRecord:
    id: str
    service: str
    type: str
    title: str
    created_at: str
    origin: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    url: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    table: dict[str, Any] | None = None
    message: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_ref(user_id: str):
    return db.collection("users").document(user_id)


def _conv_ref(user_id: str, conv_id: str):
    return _user_ref(user_id).collection("conversations").document(conv_id)


def _msg_ref(user_id: str, conv_id: str, msg_id: str):
    return _conv_ref(user_id, conv_id).collection("messages").document(msg_id)


def _workflow_metadata_ref(user_id: str, workflow_id: str):
    return _user_ref(user_id).collection("workflow_metadata").document(workflow_id)


def _artifact_ref(user_id: str, artifact_id: str):
    return _user_ref(user_id).collection("artifacts").document(artifact_id)


async def _run(fn):
    return await asyncio.to_thread(fn)


# ---------------------------------------------------------------------------
# Workflow Credentials
# ---------------------------------------------------------------------------


async def save_workflow_credential(
    user_id: str,
    *,
    service: str,
    credential_type: str,
    credential_name: str,
    n8n_credential_id: str,
    node_name: str,
    workflow_id: str,
) -> WorkflowCredential:
    credential_id = str(uuid4())
    now = _now_iso()
    data = {
        "service": service,
        "credential_type": credential_type,
        "credential_name": credential_name,
        "n8n_credential_id": n8n_credential_id,
        "node_name": node_name,
        "workflow_id": workflow_id,
        "created_at": now,
    }
    await _run(
        lambda: (
            _user_ref(user_id).collection("workflow_credentials").document(credential_id).set(data)
        )
    )
    return WorkflowCredential(id=credential_id, **data)


async def list_workflow_credentials(user_id: str) -> list[WorkflowCredential]:
    docs = await _run(lambda: list(_user_ref(user_id).collection("workflow_credentials").stream()))
    credentials: list[WorkflowCredential] = []
    for doc in docs:
        data = doc.to_dict()
        credentials.append(
            WorkflowCredential(
                id=doc.id,
                service=data.get("service", ""),
                credential_type=data.get("credential_type", ""),
                credential_name=data.get("credential_name", ""),
                n8n_credential_id=data.get("n8n_credential_id", ""),
                node_name=data.get("node_name", ""),
                workflow_id=data.get("workflow_id", ""),
                created_at=data.get("created_at", ""),
            )
        )
    return credentials


# ---------------------------------------------------------------------------
# Custom Credentials (reusable per-user HTTP credential library)
# ---------------------------------------------------------------------------


def _custom_credentials_ref(user_id: str):
    return _user_ref(user_id).collection("credentials")


async def save_custom_credential(
    user_id: str,
    *,
    label: str,
    credential_type: str,
    host: str,
    n8n_credential_id: str,
    n8n_credential_name: str,
) -> CustomCredential:
    credential_id = str(uuid4())
    now = _now_iso()
    data = {
        "label": label,
        "credential_type": credential_type,
        "host": host,
        "n8n_credential_id": n8n_credential_id,
        "n8n_credential_name": n8n_credential_name,
        "status": "ready",
        "created_at": now,
        "updated_at": now,
    }
    await _run(lambda: _custom_credentials_ref(user_id).document(credential_id).set(data))
    return _custom_credential_from_data(credential_id, data)


def _custom_credential_from_data(credential_id: str, data: dict) -> CustomCredential:
    return CustomCredential(
        id=credential_id,
        label=data.get("label", ""),
        credential_type=data.get("credential_type", ""),
        host=data.get("host", ""),
        n8n_credential_id=data.get("n8n_credential_id", ""),
        n8n_credential_name=data.get("n8n_credential_name", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        status=data.get("status", "ready"),
        auth_config=dict(data.get("auth_config") or {}),
        secret_fields=list(data.get("secret_fields") or []),
        source_url=data.get("source_url", ""),
        confidence=data.get("confidence", ""),
        pending_workflow_id=data.get("pending_workflow_id", ""),
        pending_node_name=data.get("pending_node_name", ""),
    )


def _custom_credential_from_doc(doc) -> CustomCredential:
    return _custom_credential_from_data(doc.id, doc.to_dict() or {})


async def save_draft_credential(
    user_id: str,
    *,
    label: str,
    credential_type: str,
    host: str,
    auth_config: dict,
    secret_fields: list[str],
    source_url: str,
    confidence: str,
    pending_workflow_id: str = "",
    pending_node_name: str = "",
) -> CustomCredential:
    credential_id = str(uuid4())
    now = _now_iso()
    data = {
        "label": label,
        "credential_type": credential_type,
        "host": host,
        "n8n_credential_id": "",
        "n8n_credential_name": "",
        "status": "draft",
        "auth_config": dict(auth_config),
        "secret_fields": list(secret_fields),
        "source_url": source_url,
        "confidence": confidence,
        "pending_workflow_id": pending_workflow_id,
        "pending_node_name": pending_node_name,
        "created_at": now,
        "updated_at": now,
    }
    await _run(lambda: _custom_credentials_ref(user_id).document(credential_id).set(data))
    return _custom_credential_from_data(credential_id, data)


async def finalize_draft_credential(
    user_id: str,
    credential_id: str,
    *,
    n8n_credential_id: str,
    n8n_credential_name: str,
) -> CustomCredential | None:
    ref = _custom_credentials_ref(user_id).document(credential_id)
    doc = await _run(lambda: ref.get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    if data.get("status") != "draft":
        return None
    data["status"] = "ready"
    data["n8n_credential_id"] = n8n_credential_id
    data["n8n_credential_name"] = n8n_credential_name
    data["updated_at"] = _now_iso()
    await _run(lambda: ref.set(data))
    return _custom_credential_from_data(credential_id, data)


async def list_custom_credentials(user_id: str) -> list[CustomCredential]:
    docs = await _run(lambda: list(_custom_credentials_ref(user_id).stream()))
    return [_custom_credential_from_doc(doc) for doc in docs]


async def get_custom_credential(user_id: str, credential_id: str) -> CustomCredential | None:
    doc = await _run(lambda: _custom_credentials_ref(user_id).document(credential_id).get())
    if not doc.exists:
        return None
    return _custom_credential_from_doc(doc)


async def delete_custom_credential(user_id: str, credential_id: str) -> None:
    await _run(lambda: _custom_credentials_ref(user_id).document(credential_id).delete())


# ---------------------------------------------------------------------------
# Shared API auth research cache (global, host-keyed; no secrets)
# ---------------------------------------------------------------------------


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
    return db.collection("api_auth_cache").document(host)


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
        "researched_at": _now_iso(),
        "model": model,
    }
    await _run(lambda: _api_auth_cache_ref(host).set(data))
    return ApiAuthCache(**data)


async def get_api_auth_cache(host: str) -> ApiAuthCache | None:
    doc = await _run(lambda: _api_auth_cache_ref(host).get())
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
    await _run(lambda: _api_auth_cache_ref(host).delete())


# ---------------------------------------------------------------------------
# Workflow Metadata
# ---------------------------------------------------------------------------


async def save_workflow_metadata(
    user_id: str,
    workflow_id: str,
    *,
    input_schema: list[dict],
    resources: dict | None = None,
) -> WorkflowMetadata:
    existing = await get_workflow_metadata(user_id, workflow_id)
    now = _now_iso()
    stored_resources = (
        resources if resources is not None else (existing.resources if existing else {})
    )
    data = {
        "input_schema": input_schema,
        "resources": stored_resources,
        "created_at": existing.created_at if existing else now,
        "updated_at": now,
    }
    await _run(lambda: _workflow_metadata_ref(user_id, workflow_id).set(data))
    return WorkflowMetadata(workflow_id=workflow_id, **data)


async def get_workflow_metadata(user_id: str, workflow_id: str) -> WorkflowMetadata | None:
    doc = await _run(lambda: _workflow_metadata_ref(user_id, workflow_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return WorkflowMetadata(
        workflow_id=doc.id,
        input_schema=list(data.get("input_schema") or []),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        resources=dict(data.get("resources") or {}),
    )


async def get_all_workflow_metadata(user_id: str) -> dict[str, WorkflowMetadata]:
    """Kullanıcının tüm workflow metadata'sını TEK sorguda çek (listeleme N+1
    yerine). workflow_id -> WorkflowMetadata sözlüğü döner."""
    docs = await _run(
        lambda: list(_user_ref(user_id).collection("workflow_metadata").stream())
    )
    result: dict[str, WorkflowMetadata] = {}
    for doc in docs:
        data = doc.to_dict() or {}
        result[doc.id] = WorkflowMetadata(
            workflow_id=doc.id,
            input_schema=list(data.get("input_schema") or []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            resources=dict(data.get("resources") or {}),
        )
    return result


async def save_workflow_test_status(
    user_id: str,
    workflow_id: str,
    *,
    status: str,
    findings: list[str] | None = None,
) -> None:
    """Persist the sandbox test outcome inside the workflow metadata resources.

    Stored under ``resources.test_status`` / ``resources.test_findings`` so the
    dashboard can later surface a badge. Preserves input_schema and other
    resources.
    """

    existing = await get_workflow_metadata(user_id, workflow_id)
    input_schema = existing.input_schema if existing else []
    resources = dict(existing.resources) if existing else {}
    resources["test_status"] = status
    resources["test_findings"] = list(findings or [])
    await save_workflow_metadata(
        user_id, workflow_id, input_schema=input_schema, resources=resources
    )


async def delete_workflow_metadata(user_id: str, workflow_id: str) -> None:
    await _run(lambda: _workflow_metadata_ref(user_id, workflow_id).delete())


# ---------------------------------------------------------------------------
# App Connections / OAuth state
# ---------------------------------------------------------------------------


def _connection_ref(user_id: str, connection_id: str):
    return _user_ref(user_id).collection("connections").document(connection_id)


def _oauth_state_ref(state_id: str):
    return db.collection("oauth_states").document(state_id)


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
) -> OAuthState:
    data = {
        "user_id": user_id,
        "provider": provider,
        "service": service,
        "code_verifier": code_verifier,
        "return_to": return_to,
        "expires_at": expires_at,
        "used": False,
        "requested_capabilities": requested_capabilities or [],
        "permission_pack": permission_pack,
    }
    await _run(lambda: _oauth_state_ref(state_id).set(data))
    return OAuthState(id=state_id, **data)


async def get_oauth_state(state_id: str) -> OAuthState | None:
    doc = await _run(lambda: _oauth_state_ref(state_id).get())
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
        requested_capabilities=list(data.get("requested_capabilities") or []),
        permission_pack=data.get("permission_pack"),
    )


async def mark_oauth_state_used(state_id: str) -> None:
    await _run(lambda: _oauth_state_ref(state_id).update({"used": True, "used_at": _now_iso()}))


async def get_connection(user_id: str, connection_id: str) -> AppConnection | None:
    doc = await _run(lambda: _connection_ref(user_id, connection_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return AppConnection(
        id=doc.id,
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
        capabilities=list(data.get("capabilities") or []),
        permission_packs=list(data.get("permission_packs") or []),
        direct_api_enabled=bool(data.get("direct_api_enabled", False)),
        encrypted_refresh_token=str(data.get("encrypted_refresh_token") or ""),
    )


async def list_connections(user_id: str) -> list[AppConnection]:
    docs = await _run(lambda: list(_user_ref(user_id).collection("connections").stream()))
    connections: list[AppConnection] = []
    for doc in docs:
        data = doc.to_dict() or {}
        connections.append(
            AppConnection(
                id=doc.id,
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
                capabilities=list(data.get("capabilities") or []),
                permission_packs=list(data.get("permission_packs") or []),
                direct_api_enabled=bool(data.get("direct_api_enabled", False)),
                encrypted_refresh_token=str(data.get("encrypted_refresh_token") or ""),
            )
        )
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
) -> AppConnection:
    existing = await get_connection(user_id, connection_id)
    now = _now_iso()
    data = {
        "provider": provider,
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
        "created_at": existing.created_at if existing else now,
        "updated_at": now,
    }
    await _run(lambda: _connection_ref(user_id, connection_id).set(data))
    return AppConnection(id=connection_id, **data)


async def delete_connection(user_id: str, connection_id: str) -> AppConnection | None:
    existing = await get_connection(user_id, connection_id)
    if existing is None:
        return None
    await _run(lambda: _connection_ref(user_id, connection_id).delete())
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
        "created_at": _now_iso(),
    }
    await _run(lambda: _user_ref(user_id).collection("platform_action_audit").add(data))


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def _normalize_artifact_origin(origin: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"kind": str(origin.get("kind") or "chat")}
    for source_key, target_key in (
        ("conversation_id", "conversationId"),
        ("conversationId", "conversationId"),
        ("workflow_id", "workflowId"),
        ("workflowId", "workflowId"),
        ("execution_id", "executionId"),
        ("executionId", "executionId"),
    ):
        value = origin.get(source_key)
        if value:
            normalized[target_key] = str(value)
    return normalized


def _artifact_preview_type(artifact: dict[str, Any]) -> str:
    service = str(artifact.get("service") or "")
    if service == "gmail":
        return "message_preview"
    return "table_preview"


def _artifact_document_id(artifact: dict[str, Any], origin: dict[str, Any]) -> str:
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    identity = [
        artifact.get("service"),
        artifact.get("title"),
        artifact.get("url"),
        source.get("spreadsheetId"),
        source.get("range"),
        source.get("messageId"),
        source.get("threadId"),
        source.get("query"),
        source.get("action"),
        origin.get("kind"),
        origin.get("conversationId"),
        origin.get("workflowId"),
        origin.get("executionId"),
    ]
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return "art_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _artifact_from_doc(doc) -> ArtifactRecord:
    data = doc.to_dict() or {}
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    origin = data.get("origin") if isinstance(data.get("origin"), dict) else {}
    table = data.get("table") if isinstance(data.get("table"), dict) else None
    message = data.get("message") if isinstance(data.get("message"), dict) else None
    return ArtifactRecord(
        id=doc.id,
        service=str(data.get("service") or ""),
        type=str(data.get("type") or "table_preview"),
        title=str(data.get("title") or "Artifact"),
        description=data.get("description"),
        url=data.get("url"),
        source=source,
        table=table,
        message=message,
        origin=origin,
        created_at=str(data.get("created_at") or ""),
    )


async def save_artifact(
    user_id: str,
    artifact: dict[str, Any],
    *,
    origin: dict[str, Any],
) -> ArtifactRecord:
    origin_data = _normalize_artifact_origin(origin)
    artifact_id = _artifact_document_id(artifact, origin_data)
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    table = artifact.get("table") if isinstance(artifact.get("table"), dict) else None
    message = artifact.get("message") if isinstance(artifact.get("message"), dict) else None
    now = _now_iso()
    data: dict[str, Any] = {
        "service": str(artifact.get("service") or ""),
        "type": _artifact_preview_type(artifact),
        "title": str(artifact.get("title") or "Artifact"),
        "source": source,
        "origin": origin_data,
        "created_at": now,
    }
    if artifact.get("description"):
        data["description"] = str(artifact["description"])
    if artifact.get("url"):
        data["url"] = str(artifact["url"])
    if table is not None:
        data["table"] = table
    if message is not None:
        data["message"] = message

    await _run(lambda: _artifact_ref(user_id, artifact_id).set(data))
    return ArtifactRecord(id=artifact_id, **data)


async def list_artifacts(
    user_id: str,
    *,
    limit: int = 50,
    service: str | None = None,
) -> list[ArtifactRecord]:
    normalized_limit = max(1, min(limit, 100))
    fetch_limit = normalized_limit if service is None else min(max(normalized_limit * 4, 50), 200)
    docs = await _run(
        lambda: list(
            _user_ref(user_id)
            .collection("artifacts")
            .order_by("created_at", direction="DESCENDING")
            .limit(fetch_limit)
            .stream()
        )
    )
    artifacts = [_artifact_from_doc(doc) for doc in docs]
    if service:
        artifacts = [artifact for artifact in artifacts if artifact.service == service]
    return artifacts[:normalized_limit]


async def delete_artifact(user_id: str, artifact_id: str) -> bool:
    ref = _artifact_ref(user_id, artifact_id)
    doc = await _run(lambda: ref.get())
    if not doc.exists:
        return False
    await _run(lambda: ref.delete())
    return True


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


async def list_conversations(user_id: str) -> list[Conversation]:
    docs = await _run(
        lambda: list(
            _user_ref(user_id)
            .collection("conversations")
            .order_by("updated_at", direction="DESCENDING")
            .stream()
        )
    )
    result = []
    for d in docs:
        data = d.to_dict()
        result.append(
            Conversation(
                id=d.id,
                title=data.get("title", "New conversation"),
                message_count=data.get("message_count", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
        )
    return result


async def get_conversation(user_id: str, conv_id: str) -> Conversation | None:
    doc = await _run(lambda: _conv_ref(user_id, conv_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict()

    msg_docs = await _run(
        lambda: list(
            _conv_ref(user_id, conv_id).collection("messages").order_by("created_at").stream()
        )
    )
    messages = [
        Message(
            id=m.id,
            role=m.to_dict()["role"],
            content=m.to_dict()["content"],
            created_at=m.to_dict()["created_at"],
            provider=m.to_dict().get("provider"),
            model=m.to_dict().get("model"),
            tier=m.to_dict().get("tier"),
            attachments=m.to_dict().get("attachments"),
        )
        for m in msg_docs
    ]

    return Conversation(
        id=doc.id,
        title=data.get("title", "New conversation"),
        message_count=data.get("message_count", 0),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        provider=data.get("provider"),
        model=data.get("model"),
        reasoning_effort=data.get("reasoning_effort"),
        messages=messages,
    )


async def get_or_create_conversation(
    user_id: str,
    conv_id: str | None,
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> Conversation:
    if conv_id:
        doc = await _run(lambda: _conv_ref(user_id, conv_id).get())
        if doc.exists:
            data = doc.to_dict()
            return Conversation(
                id=conv_id,
                title=data.get("title", "New conversation"),
                message_count=data.get("message_count", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                provider=data.get("provider"),
                model=data.get("model"),
                reasoning_effort=data.get("reasoning_effort"),
            )

    new_id = str(uuid4())
    now = _now_iso()
    doc_data: dict = {
        "title": "New conversation",
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    if provider:
        doc_data["provider"] = provider
    if model:
        doc_data["model"] = model
    if reasoning_effort:
        doc_data["reasoning_effort"] = reasoning_effort

    await _run(lambda: _conv_ref(user_id, new_id).set(doc_data))
    return Conversation(
        id=new_id,
        title="New conversation",
        message_count=0,
        created_at=now,
        updated_at=now,
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
    )  # noqa: E501


async def add_message(
    user_id: str,
    conv_id: str,
    role: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    tier: str | None = None,
    attachments: list[dict] | None = None,
) -> Message:
    msg_id = str(uuid4())
    now = _now_iso()

    data: dict = {"role": role, "content": content, "created_at": now}
    if provider:
        data["provider"] = provider
    if model:
        data["model"] = model
    if tier:
        data["tier"] = tier
    if attachments:
        data["attachments"] = attachments

    await _run(lambda: _msg_ref(user_id, conv_id, msg_id).set(data))

    # Conversation'ı güncelle
    conv_ref = _conv_ref(user_id, conv_id)

    def _update():
        doc = conv_ref.get()
        data = doc.to_dict() if doc.exists else {}
        count = data.get("message_count", 0) + 1
        update = {"message_count": count, "updated_at": now}
        if role == "user" and data.get("title") == "New conversation":
            update["title"] = content[:60] + ("..." if len(content) > 60 else "")
        conv_ref.update(update)

    await _run(_update)
    return Message(
        id=msg_id,
        role=role,
        content=content,
        created_at=now,
        provider=provider,
        model=model,
        tier=tier,
        attachments=attachments or None,
    )


async def get_conversation_messages(user_id: str, conv_id: str) -> list[Message]:
    docs = await _run(
        lambda: list(
            _conv_ref(user_id, conv_id).collection("messages").order_by("created_at").stream()
        )
    )
    return [
        Message(
            id=d.id,
            role=d.to_dict()["role"],
            content=d.to_dict()["content"],
            created_at=d.to_dict()["created_at"],
            provider=d.to_dict().get("provider"),
            model=d.to_dict().get("model"),
            tier=d.to_dict().get("tier"),
            attachments=d.to_dict().get("attachments"),
        )
        for d in docs
    ]


async def delete_conversation(user_id: str, conv_id: str) -> bool:
    doc = await _run(lambda: _conv_ref(user_id, conv_id).get())
    if not doc.exists:
        return False

    # Mesajları sil
    msg_docs = await _run(lambda: list(_conv_ref(user_id, conv_id).collection("messages").stream()))
    for m in msg_docs:
        await _run(
            lambda mid=m.id: (
                _conv_ref(user_id, conv_id).collection("messages").document(mid).delete()
            )
        )  # noqa: E501

    await _run(lambda: _conv_ref(user_id, conv_id).delete())
    return True
