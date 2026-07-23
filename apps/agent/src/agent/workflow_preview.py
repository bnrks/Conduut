"""Safe preview and approval service for manual side-effect workflow runs."""

from typing import Any

from src import store
from src.agent.assurance import workflow_fingerprint
from src.agent.sandbox import run_sandbox_test
from src.agent.sandbox_nodes import find_action_nodes
from src.agent.tools.runtime_inputs import (
    _validated_workflow_input,
    _workflow_input_schema_from_metadata,
)


def workflow_requires_preview(workflow: dict[str, Any]) -> bool:
    return bool(find_action_nodes(list(workflow.get("nodes") or [])))


async def preview_workflow_run(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_payload: dict[str, Any] | None,
    issue_token: bool = True,
) -> dict[str, Any]:
    workflow_id = str(workflow.get("id") or "")
    fingerprint = workflow_fingerprint(workflow)
    metadata = await store.get_workflow_metadata(user_id, workflow_id)
    input_schema = _workflow_input_schema_from_metadata(metadata)
    result = await run_sandbox_test(
        workflow,
        user_id=user_id,
        input_schema=input_schema,
        intent=str(workflow.get("name") or "Workflow"),
        input_payload=input_payload,
    )
    payload = {
        "workflow_id": workflow_id,
        "workflow_fingerprint": fingerprint,
        "ready": result.passed and not result.skipped,
        "status": result.status,
        "coverage": result.coverage,
        "oracle": result.oracle.model_dump(exclude_none=True) if result.oracle else None,
        "probe_evidence": [item.model_dump(exclude_none=True) for item in result.probe_evidence],
        "eligible_count": result.eligible_count,
        "action_count": result.action_count,
        "writeback_count": result.writeback_count,
        "projected_second_run": {
            "eligible_count": result.projected_second_run_eligible_count,
            "action_count": result.projected_second_run_action_count,
            "writeback_count": result.projected_second_run_writeback_count,
        },
        "actions": result.preview_actions,
        "findings": result.findings,
    }
    if not payload["ready"] or not issue_token:
        return payload
    preview = await store.save_workflow_run_preview(
        user_id,
        workflow_id,
        workflow_fingerprint=fingerprint,
        input_payload=input_payload,
        payload=payload,
    )
    payload["preview_token"] = preview.token
    payload["expires_at"] = preview.expires_at
    return payload


async def consume_workflow_preview(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_payload: dict[str, Any] | None,
    preview_token: str | None,
) -> bool:
    if not workflow_requires_preview(workflow):
        return True
    if not preview_token:
        return False
    metadata = await store.get_workflow_metadata(user_id, str(workflow.get("id") or ""))
    input_schema = _workflow_input_schema_from_metadata(metadata)
    rows = input_payload.get("rows") if isinstance(input_payload, dict) else None
    if isinstance(rows, list):
        if not input_schema:
            raise ValueError("Batch run requires a workflow input schema.")
        for index, row in enumerate(rows, start=1):
            raw_input = row.get("input") if isinstance(row, dict) else None
            _validated, missing = _validated_workflow_input(input_schema, raw_input)
            if missing:
                labels = [field.label for field in input_schema if field.name in missing]
                row_number = row.get("rowNumber", index) if isinstance(row, dict) else index
                raise ValueError(
                    f"Row {row_number} is missing required workflow input: "
                    f"{', '.join(labels or missing)}"
                )
    else:
        _validated, missing = _validated_workflow_input(input_schema, input_payload)
        if missing:
            labels = [field.label for field in input_schema if field.name in missing]
            raise ValueError(f"Missing required workflow input: {', '.join(labels or missing)}")
    preview = await store.consume_workflow_run_preview(
        user_id,
        preview_token,
        workflow_id=str(workflow.get("id") or ""),
        workflow_fingerprint=workflow_fingerprint(workflow),
        input_payload=input_payload,
    )
    return preview is not None


async def preview_workflow_batch(
    workflow: dict[str, Any],
    *,
    user_id: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Probe every batch row without side effects and issue one aggregate approval."""

    workflow_id = str(workflow.get("id") or "")
    fingerprint = workflow_fingerprint(workflow)
    metadata = await store.get_workflow_metadata(user_id, workflow_id)
    input_schema = _workflow_input_schema_from_metadata(metadata)
    findings: list[str] = []
    actions: list[dict[str, Any]] = []
    eligible_count = action_count = writeback_count = 0
    coverage = "full"
    statuses: list[str] = []
    for row in rows:
        result = await run_sandbox_test(
            workflow,
            user_id=user_id,
            input_schema=input_schema,
            intent=str(workflow.get("name") or "Workflow"),
            input_payload=dict(row.get("input") or {}),
        )
        statuses.append(result.status)
        eligible_count += int(result.eligible_count or 0)
        action_count += int(result.action_count or 0)
        writeback_count += int(result.writeback_count or 0)
        if result.coverage != "full":
            coverage = "partial"
        findings.extend(f"Row {row.get('rowNumber')}: {finding}" for finding in result.findings)
        if len(actions) < 5:
            actions.extend(result.preview_actions[: 5 - len(actions)])
        if not result.passed or result.skipped:
            return {
                "workflow_id": workflow_id,
                "workflow_fingerprint": fingerprint,
                "ready": False,
                "status": "needs_attention",
                "coverage": coverage,
                "oracle": result.oracle.model_dump(exclude_none=True) if result.oracle else None,
                "probe_evidence": [
                    item.model_dump(exclude_none=True) for item in result.probe_evidence
                ],
                "eligible_count": eligible_count,
                "action_count": action_count,
                "writeback_count": writeback_count,
                "actions": actions,
                "findings": findings,
            }
    status = "no_action" if statuses and all(item == "no_action" for item in statuses) else "passed"
    payload = {
        "workflow_id": workflow_id,
        "workflow_fingerprint": fingerprint,
        "ready": True,
        "status": status,
        "coverage": coverage,
        "oracle": None,
        "probe_evidence": [],
        "eligible_count": eligible_count,
        "action_count": action_count,
        "writeback_count": writeback_count,
        "actions": actions,
        "findings": findings,
    }
    preview = await store.save_workflow_run_preview(
        user_id,
        workflow_id,
        workflow_fingerprint=fingerprint,
        input_payload={"rows": rows},
        payload=payload,
    )
    payload["preview_token"] = preview.token
    payload["expires_at"] = preview.expires_at
    return payload
