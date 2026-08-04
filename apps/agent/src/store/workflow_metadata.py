"""Workflow metadata — input_schema, resources (test_status, output_schema)."""

from dataclasses import dataclass, field

import src.store as _pkg_store
from src.workflow_test_policy import WORKFLOW_TEST_POLICY_VERSION


@dataclass
class WorkflowMetadata:
    workflow_id: str
    input_schema: list[dict]
    created_at: str
    updated_at: str
    instance_id: str = ""
    resources: dict = field(default_factory=dict)


def _workflow_metadata_ref(user_id: str, workflow_id: str, instance_id: str | None = None):
    document_id = f"{instance_id}--{workflow_id}" if instance_id else workflow_id
    return _pkg_store._user_ref(user_id).collection("workflow_metadata").document(document_id)


async def save_workflow_metadata(
    user_id: str,
    workflow_id: str,
    *,
    input_schema: list[dict],
    resources: dict | None = None,
    instance_id: str | None = None,
) -> WorkflowMetadata:
    existing = await get_workflow_metadata(user_id, workflow_id, instance_id=instance_id)
    now = _pkg_store._now_iso()
    stored_resources = (
        resources if resources is not None else (existing.resources if existing else {})
    )
    data = {
        "workflow_id": workflow_id,
        "instance_id": instance_id or (existing.instance_id if existing else ""),
        "input_schema": input_schema,
        "resources": stored_resources,
        "created_at": existing.created_at if existing else now,
        "updated_at": now,
    }
    await _pkg_store._run(
        lambda: _workflow_metadata_ref(user_id, workflow_id, instance_id).set(data)
    )
    return WorkflowMetadata(
        workflow_id=workflow_id,
        input_schema=list(data["input_schema"]),
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
        instance_id=str(data["instance_id"]),
        resources=dict(data["resources"]),
    )


async def get_workflow_metadata(
    user_id: str,
    workflow_id: str,
    *,
    instance_id: str | None = None,
) -> WorkflowMetadata | None:
    doc = await _pkg_store._run(
        lambda: _workflow_metadata_ref(user_id, workflow_id, instance_id).get()
    )
    if not doc.exists and instance_id == "shared_dev":
        doc = await _pkg_store._run(lambda: _workflow_metadata_ref(user_id, workflow_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return WorkflowMetadata(
        workflow_id=str(data.get("workflow_id") or workflow_id),
        input_schema=list(data.get("input_schema") or []),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        instance_id=str(data.get("instance_id") or ""),
        resources=dict(data.get("resources") or {}),
    )


async def get_all_workflow_metadata(
    user_id: str,
    *,
    instance_id: str | None = None,
) -> dict[str, WorkflowMetadata]:
    """Kullanıcının tüm workflow metadata'sını TEK sorguda çek (listeleme N+1
    yerine). workflow_id -> WorkflowMetadata sözlüğü döner."""
    docs = await _pkg_store._run(
        lambda: list(_pkg_store._user_ref(user_id).collection("workflow_metadata").stream())
    )
    result: dict[str, WorkflowMetadata] = {}
    for doc in docs:
        data = doc.to_dict() or {}
        stored_instance_id = str(data.get("instance_id") or "")
        if (
            instance_id is not None
            and stored_instance_id != instance_id
            and not (instance_id == "shared_dev" and not stored_instance_id)
        ):
            continue
        workflow_id = str(data.get("workflow_id") or doc.id)
        result[workflow_id] = WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=list(data.get("input_schema") or []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            instance_id=stored_instance_id,
            resources=dict(data.get("resources") or {}),
        )
    return result


async def save_workflow_test_status(
    user_id: str,
    workflow_id: str,
    *,
    status: str,
    findings: list[str] | None = None,
    fingerprint: str | None = None,
    coverage: str | None = None,
    instance_id: str | None = None,
) -> None:
    """Persist the sandbox test outcome inside the workflow metadata resources.

    Stored under ``resources.test_status`` / ``resources.test_findings`` so the
    dashboard can later surface a badge. Preserves input_schema and other
    resources.
    """
    # Use package-level lookup so tests can monkeypatch store.get/save_workflow_metadata.
    existing = (
        await _pkg_store.get_workflow_metadata(user_id, workflow_id)
        if instance_id is None
        else await _pkg_store.get_workflow_metadata(user_id, workflow_id, instance_id=instance_id)
    )
    input_schema = existing.input_schema if existing else []
    resources = dict(existing.resources) if existing else {}
    resources["test_status"] = status
    resources["test_findings"] = list(findings or [])
    assurance = dict(resources.get("assurance") or {})
    assurance.update(
        {
            "version": WORKFLOW_TEST_POLICY_VERSION,
            "sandbox_status": status,
            "findings": list(findings or []),
        }
    )
    if fingerprint is not None:
        assurance["workflow_fingerprint"] = fingerprint
    if coverage is not None:
        assurance["coverage"] = coverage
    resources["assurance"] = assurance
    save_kwargs = {"input_schema": input_schema, "resources": resources}
    if instance_id is not None:
        save_kwargs["instance_id"] = instance_id
    await _pkg_store.save_workflow_metadata(user_id, workflow_id, **save_kwargs)


async def delete_workflow_metadata(
    user_id: str,
    workflow_id: str,
    *,
    instance_id: str | None = None,
) -> None:
    await _pkg_store._run(
        lambda: _workflow_metadata_ref(user_id, workflow_id, instance_id).delete()
    )
