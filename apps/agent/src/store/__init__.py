"""Firestore tabanlı store paketi.

Tüm public isimler bu modülden re-export edilir; tüketiciler değişmeden
``from src import store; store.X`` veya ``from src.store import X``
şeklinde kullanmaya devam edebilir.

WorkflowCredential / save_workflow_credential / list_workflow_credentials
kaldırıldı — dead legacy cluster (workflow_credentials koleksiyonu hiçbir
tüketici tarafından kullanılmıyordu).

Tasarım notu — patchable private helpers:
  Sub-modüller private helper'ları ``_pkg_store._run`` gibi bu paket
  üzerinden çağırır (doğrudan import etmez). Böylece ``monkeypatch.setattr
  (store, "_run", fake)`` patchi sub-modüldeki çağrıyı etkiler.
  Bu nedenle ``_run``, ``_user_ref``, ``_now_iso``, ``db``, ``_conv_ref``,
  ``_msg_ref`` bu __init__'te açıkça tanımlıdır.
"""

from src.firebase import db

from ._base import _now, _now_iso, _run, _user_ref
from .api_auth_cache import (
    ApiAuthCache,
    delete_api_auth_cache,
    get_api_auth_cache,
    save_api_auth_cache,
)
from .artifacts import (
    ArtifactRecord,
    _artifact_document_id,
    delete_artifact,
    list_artifacts,
    save_artifact,
)
from .connections import (
    AppConnection,
    OAuthState,
    delete_connection,
    get_connection,
    get_oauth_state,
    list_connections,
    mark_oauth_state_used,
    save_connection,
    save_oauth_state,
    save_platform_action_audit,
)
from .conversations import (
    Conversation,
    Message,
    _conv_ref,
    _msg_ref,
    add_message,
    delete_conversation,
    get_conversation,
    get_conversation_messages,
    get_or_create_conversation,
    list_conversations,
)
from .credentials import (
    CustomCredential,
    _custom_credential_from_data,
    delete_custom_credential,
    finalize_draft_credential,
    get_custom_credential,
    list_custom_credentials,
    save_custom_credential,
    save_draft_credential,
)
from .execution_evidence import save_execution_evidence
from .n8n_instances import (
    N8nInstanceRecord,
    deactivate_other_n8n_instances,
    delete_n8n_instance,
    get_active_n8n_instance,
    get_latest_n8n_instance,
    get_n8n_instance,
    list_n8n_instances,
    save_n8n_instance,
)
from .n8n_migrations import (
    N8nMigrationExecutionSummary,
    N8nMigrationItem,
    N8nMigrationRecord,
    get_n8n_migration,
    list_n8n_migration_execution_summaries,
    save_n8n_migration,
    upsert_n8n_migration_execution_summaries,
)
from .usage import (
    AgentUsageEvent,
    _usage_event_document_id,
    list_agent_usage_events,
    save_agent_usage_event,
)
from .workflow_metadata import (
    WorkflowMetadata,
    delete_workflow_metadata,
    get_all_workflow_metadata,
    get_workflow_metadata,
    save_workflow_metadata,
    save_workflow_test_status,
)
from .workflow_previews import (
    WorkflowRunPreview,
    consume_workflow_run_preview,
    save_workflow_run_preview,
    workflow_input_hash,
)

__all__ = [
    # firebase re-export
    "db",
    # base private helpers (patchable by tests via monkeypatch.setattr(store, ...))
    "_now",
    "_now_iso",
    "_run",
    "_user_ref",
    # conversation private helpers (patchable)
    "_conv_ref",
    "_msg_ref",
    # dataclasses
    "ApiAuthCache",
    "AppConnection",
    "ArtifactRecord",
    "Conversation",
    "CustomCredential",
    "Message",
    "N8nInstanceRecord",
    "N8nMigrationExecutionSummary",
    "N8nMigrationItem",
    "N8nMigrationRecord",
    "OAuthState",
    "WorkflowMetadata",
    "WorkflowRunPreview",
    "AgentUsageEvent",
    # api_auth_cache
    "delete_api_auth_cache",
    "get_api_auth_cache",
    "save_api_auth_cache",
    # artifacts (includes private used by tests)
    "_artifact_document_id",
    "delete_artifact",
    "list_artifacts",
    "save_artifact",
    # connections
    "delete_connection",
    "get_connection",
    "get_oauth_state",
    "list_connections",
    "mark_oauth_state_used",
    "save_connection",
    "save_oauth_state",
    "save_platform_action_audit",
    # conversations
    "add_message",
    "delete_conversation",
    "get_conversation",
    "get_conversation_messages",
    "get_or_create_conversation",
    "list_conversations",
    # credentials (includes private used by tests)
    "_custom_credential_from_data",
    "delete_custom_credential",
    "finalize_draft_credential",
    "get_custom_credential",
    "list_custom_credentials",
    "save_custom_credential",
    "save_draft_credential",
    # execution evidence
    "save_execution_evidence",
    # n8n instances
    "deactivate_other_n8n_instances",
    "delete_n8n_instance",
    "get_active_n8n_instance",
    "get_latest_n8n_instance",
    "get_n8n_migration",
    "get_n8n_instance",
    "list_n8n_migration_execution_summaries",
    "list_n8n_instances",
    "save_n8n_instance",
    "save_n8n_migration",
    "upsert_n8n_migration_execution_summaries",
    # workflow_metadata
    "delete_workflow_metadata",
    "get_all_workflow_metadata",
    "get_workflow_metadata",
    "save_workflow_metadata",
    "save_workflow_test_status",
    # workflow previews
    "consume_workflow_run_preview",
    "save_workflow_run_preview",
    "workflow_input_hash",
    # usage
    "_usage_event_document_id",
    "list_agent_usage_events",
    "save_agent_usage_event",
]
