from dataclasses import dataclass, field

import pytest

from src import store
from src.n8n_migration import (
    MigrationConfirmationRequiredError,
    N8nMigrationService,
)
from src.store.n8n_migrations import N8nMigrationItem, N8nMigrationRecord


@dataclass
class _FakeMigrationStore:
    manifest: object | None = None
    archived: list = field(default_factory=list)

    async def get_n8n_migration(self, _user_id: str, _migration_id: str):
        return self.manifest

    async def save_n8n_migration(self, record):
        self.manifest = record
        return record

    async def upsert_n8n_migration_execution_summaries(
        self,
        _user_id: str,
        _migration_id: str,
        summaries,
    ):
        seen = {summary.summary_id for summary in self.archived}
        for summary in summaries:
            if summary.summary_id not in seen:
                self.archived.append(summary)
                seen.add(summary.summary_id)


class _FakeLegacyStore:
    def __init__(self):
        self.saved_metadata: list[dict] = []
        self.instance = store.N8nInstanceRecord(
            id="inst_1",
            display_name="Primary",
            ownership="customer_owned",
            provider="manual",
            base_url="https://automation.example.com",
            webhook_base_url="https://automation.example.com",
            api_key_secret_ref="secret-ref",
            n8n_version="1.121.3",
            compatibility_status="supported",
            connection_status="connected",
            capabilities=["workflows", "executions", "credentials"],
            verified_at="2026-08-03T10:00:00+00:00",
            last_health_at="2026-08-03T10:00:00+00:00",
            last_error_code=None,
            created_at="2026-08-03T10:00:00+00:00",
            updated_at="2026-08-03T10:00:00+00:00",
            is_active=True,
        )

    async def get_active_n8n_instance(self, _user_id: str):
        return self.instance

    async def get_all_workflow_metadata(self, _user_id: str):
        return {
            "wf_legacy": store.WorkflowMetadata(
                workflow_id="wf_legacy",
                input_schema=[],
                created_at="2026-08-01T10:00:00+00:00",
                updated_at="2026-08-01T10:00:00+00:00",
                resources={},
            )
        }

    async def list_custom_credentials(self, _user_id: str):
        return [
            store.CustomCredential(
                id="cred_1",
                label="Stripe API",
                credential_type="httpHeaderAuth",
                host="api.stripe.com",
                n8n_credential_id="n8n_cred_1",
                n8n_credential_name="Stripe API",
                created_at="2026-08-01T10:00:00+00:00",
                updated_at="2026-08-01T10:00:00+00:00",
                pending_workflow_id="wf_legacy",
                pending_node_name="HTTP",
            )
        ]

    async def list_connections(self, _user_id: str):
        return [
            store.AppConnection(
                id="google_gmail",
                provider="google",
                service="gmail",
                account_email="user@example.com",
                google_sub="123",
                credential_type="gmailOAuth2",
                n8n_credential_id="n8n_conn_1",
                n8n_credential_name="Gmail",
                status="connected",
                scopes=["gmail.send"],
                created_at="2026-08-01T10:00:00+00:00",
                updated_at="2026-08-01T10:00:00+00:00",
            )
        ]

    async def save_workflow_metadata(
        self,
        user_id: str,
        workflow_id: str,
        *,
        input_schema: list[dict],
        resources: dict | None = None,
        instance_id: str | None = None,
    ):
        payload = {
            "user_id": user_id,
            "workflow_id": workflow_id,
            "input_schema": list(input_schema),
            "resources": dict(resources or {}),
            "instance_id": instance_id,
        }
        self.saved_metadata.append(payload)
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=list(input_schema),
            created_at="2026-08-03T10:00:00+00:00",
            updated_at="2026-08-03T10:00:00+00:00",
            instance_id=instance_id or "",
            resources=dict(resources or {}),
        )


class _FakeTransport:
    def __init__(self):
        self.created_payloads = []
        self.source_workflow = {
            "id": "wf_legacy",
            "name": "Legacy Workflow",
            "active": True,
            "nodes": [
                {
                    "id": "node-1",
                    "name": "HTTP",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "https://example.com"},
                    "credentials": {"httpHeaderAuth": {"id": "old", "name": "Old"}},
                }
            ],
            "connections": {},
            "settings": {"executionOrder": "v1"},
        }
        self.target_workflows = {}

    async def list_workflows(self):
        return list(self.target_workflows.values())

    async def get_workflow(self, workflow_id: str):
        if workflow_id == "wf_legacy":
            return dict(self.source_workflow)
        if workflow_id not in self.target_workflows:
            raise RuntimeError("missing workflow")
        return dict(self.target_workflows[workflow_id])

    async def create_workflow(self, payload: dict):
        self.created_payloads.append(payload)
        self.target_workflows["wf_target"] = {
            "id": "wf_target",
            "name": payload["name"],
            "active": False,
            "nodes": payload["nodes"],
            "connections": payload["connections"],
            "settings": payload["settings"],
        }
        return {"id": "wf_target", "name": payload["name"], "active": False}

    async def list_executions_page(self, workflow_id: str, *, cursor: str | None, limit: int):
        assert workflow_id == "wf_legacy"
        assert limit > 0
        if cursor:
            return {"data": [], "nextCursor": None}
        return {
            "data": [
                {
                    "id": "ex1",
                    "status": "error",
                    "startedAt": "2026-08-02T12:00:00+00:00",
                }
            ],
            "nextCursor": None,
        }

    async def get_execution_detail(self, execution_id: str):
        assert execution_id == "ex1"
        return {
            "id": "ex1",
            "status": "error",
            "mode": "manual",
            "startedAt": "2026-08-02T12:00:00+00:00",
            "stoppedAt": "2026-08-02T12:00:03+00:00",
            "data": {"resultData": {"error": {"message": "Authorization=Bearer secret-123"}}},
        }


@pytest.mark.asyncio
async def test_start_requires_explicit_confirmation():
    service = N8nMigrationService(
        legacy_store=_FakeLegacyStore(),
        migration_store=_FakeMigrationStore(),
        source_transport=_FakeTransport(),
    )

    with pytest.raises(MigrationConfirmationRequiredError):
        await service.start("u1", confirm=False)


@pytest.mark.asyncio
async def test_preview_keeps_target_bound_credentials_and_connections_customer_owned():
    legacy_store = _FakeLegacyStore()

    async def target_credentials(_user_id: str):
        credentials = await _FakeLegacyStore().list_custom_credentials(_user_id)
        credentials[0].instance_id = "inst_1"
        return credentials

    async def target_connections(_user_id: str):
        connections = await _FakeLegacyStore().list_connections(_user_id)
        connections[0].instance_id = "inst_1"
        return connections

    legacy_store.list_custom_credentials = target_credentials
    legacy_store.list_connections = target_connections
    service = N8nMigrationService(
        legacy_store=legacy_store,
        migration_store=_FakeMigrationStore(),
        source_transport=_FakeTransport(),
    )

    _target, items = await service.preview("u1")

    credential = next(item for item in items if item.kind == "credential")
    connection = next(item for item in items if item.kind == "connection")
    assert credential.status == "customer_owned"
    assert credential.reconnect_required is False
    assert connection.status == "customer_owned"
    assert connection.reconnect_required is False


@pytest.mark.asyncio
async def test_advance_migrates_workflow_and_marks_reconnect_requirements(monkeypatch):
    monkeypatch.setattr("src.n8n_migration.store._now_iso", lambda: "2026-08-03T10:00:00+00:00")
    migration_store = _FakeMigrationStore()
    transport = _FakeTransport()
    legacy_store = _FakeLegacyStore()
    service = N8nMigrationService(
        legacy_store=legacy_store,
        migration_store=migration_store,
        source_transport=transport,
    )

    async def fake_target_transport(_target):
        return transport

    monkeypatch.setattr(service, "_target_transport", fake_target_transport)

    await service.start("u1", confirm=True)
    after_workflow = await service.advance("u1", batch_size=1)
    after_archive = await service.advance("u1", batch_size=1)
    after_credential = await service.advance("u1", batch_size=1)
    after_connection = await service.advance("u1", batch_size=1)

    workflow_item = next(item for item in after_workflow.items if item.kind == "workflow")
    archive_item = next(item for item in after_archive.items if item.kind == "execution_archive")
    credential_item = next(item for item in after_credential.items if item.kind == "credential")
    connection_item = next(item for item in after_connection.items if item.kind == "connection")

    assert workflow_item.status == "customer_owned"
    assert workflow_item.target_id == "wf_target"
    assert "credentials" not in transport.created_payloads[0]["nodes"][0]
    assert archive_item.status == "archived"
    assert after_archive.archived_execution_count == 1
    assert migration_store.archived[0].error_message == "Authorization=Bearer [redacted]"
    assert legacy_store.saved_metadata[0]["workflow_id"] == "wf_target"
    assert legacy_store.saved_metadata[0]["instance_id"] == "inst_1"
    assert legacy_store.saved_metadata[0]["resources"]["instance_id"] == "inst_1"
    assert (
        legacy_store.saved_metadata[0]["resources"]["workflow_baseline"]["instance_id"] == "inst_1"
    )
    assert (
        legacy_store.saved_metadata[0]["resources"]["migration_provenance"]["source_workflow_id"]
        == "wf_legacy"
    )
    assert credential_item.status == "migration_required"
    assert credential_item.metadata["pending_target_workflow_id"] == "wf_target"
    assert connection_item.status == "migration_required"


@pytest.mark.asyncio
async def test_advance_is_idempotent_for_existing_target_workflow(monkeypatch):
    monkeypatch.setattr("src.n8n_migration.store._now_iso", lambda: "2026-08-03T10:00:00+00:00")
    migration_store = _FakeMigrationStore()
    transport = _FakeTransport()
    legacy_store = _FakeLegacyStore()
    transport.target_workflows["wf_target"] = {
        "id": "wf_target",
        "name": "Legacy Workflow",
        "active": False,
        "nodes": [
            {
                "id": "node-1",
                "name": "HTTP",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://example.com"},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }
    service = N8nMigrationService(
        legacy_store=legacy_store,
        migration_store=migration_store,
        source_transport=transport,
    )

    async def fake_target_transport(_target):
        return transport

    monkeypatch.setattr(service, "_target_transport", fake_target_transport)

    manifest = await service.start("u1", confirm=True)
    workflow_index = next(
        index for index, item in enumerate(manifest.items) if item.kind == "workflow"
    )
    manifest.items[workflow_index] = N8nMigrationItem(
        item_id=manifest.items[workflow_index].item_id,
        kind="workflow",
        legacy_id="wf_legacy",
        display_name="wf_legacy",
        status="legacy_shared",
        metadata={},
    )
    migration_store.manifest = manifest

    after = await service.advance("u1", batch_size=1)
    workflow_item = next(item for item in after.items if item.kind == "workflow")

    assert workflow_item.target_id == "wf_target"
    assert transport.created_payloads == []
    assert len(legacy_store.saved_metadata) == 1
    assert legacy_store.saved_metadata[0]["workflow_id"] == "wf_target"


@pytest.mark.asyncio
async def test_execution_archive_never_exceeds_global_ten_thousand_limit():
    migration_store = _FakeMigrationStore()
    service = N8nMigrationService(
        legacy_store=_FakeLegacyStore(),
        migration_store=migration_store,
        source_transport=_FakeTransport(),
    )
    manifest = N8nMigrationRecord(
        id="migration_1",
        user_id="u1",
        source_instance_id="shared_dev",
        target_instance_id="inst_1",
        status="in_progress",
        created_at="now",
        updated_at="now",
        confirmed_at="now",
        archived_execution_count=9999,
        items=[],
    )
    item = N8nMigrationItem(
        item_id="execution_archive:wf_legacy",
        kind="execution_archive",
        legacy_id="wf_legacy",
        display_name="Legacy executions",
        status="legacy_shared",
    )

    updated = await service._archive_execution_summaries(manifest, item, _FakeTransport())

    assert updated.status == "archived"
    assert manifest.archived_execution_count == 10000
    assert len(migration_store.archived) == 1
    assert "secret-123" not in (migration_store.archived[0].error_message or "")
