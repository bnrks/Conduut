"""Safe preview and approval service for manual side-effect workflow runs."""

from typing import Any

from src import store
from src.agent.assurance import (
    analyze_workflow_semantics,
    build_oracle_contract,
    workflow_fingerprint,
)
from src.agent.runtime_policy import (
    ExecutionPolicy,
    normalize_execution_policy,
    preview_basis_for_policy,
    preview_requires_sandbox,
)
from src.agent.sandbox import run_sandbox_test
from src.agent.sandbox_nodes import find_action_nodes
from src.agent.tools.runtime_inputs import (
    _validated_workflow_input,
    _workflow_input_schema_from_metadata,
)


def workflow_requires_preview(workflow: dict[str, Any]) -> bool:
    return bool(find_action_nodes(list(workflow.get("nodes") or [])))


def _mask_target(value: Any) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return "***" if text else ""
    local, domain = text.rsplit("@", 1)
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


def _static_preview_actions(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for node in find_action_nodes(list(workflow.get("nodes") or []))[:5]:
        name = str(node.get("name") or "")
        node_type = str(node.get("type") or "")
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        operation = str(parameters.get("operation") or "").lower()
        if node_type == "n8n-nodes-base.gmail" and (operation or "send") == "send":
            preview.append(
                {
                    "kind": "gmail_send",
                    "node": name,
                    "target": _mask_target(parameters.get("sendTo")),
                    "subject": str(parameters.get("subject") or "")[:160],
                    "message": str(parameters.get("message") or "")[:500],
                }
            )
            continue
        if node_type == "n8n-nodes-base.googleSheets" and operation in {"update", "appendorupdate"}:
            columns = (
                parameters.get("columns") if isinstance(parameters.get("columns"), dict) else {}
            )
            matching = columns.get("matchingColumns")
            preview.append(
                {
                    "kind": "sheets_update",
                    "node": name,
                    "matching_columns": list(matching) if isinstance(matching, list) else [],
                }
            )
            continue
        if node_type == "n8n-nodes-base.googleSheets" and operation == "append":
            columns = (
                parameters.get("columns") if isinstance(parameters.get("columns"), dict) else {}
            )
            values = columns.get("value") if isinstance(columns.get("value"), dict) else {}
            preview.append(
                {
                    "kind": "sheets_append",
                    "node": name,
                    "columns": [str(key) for key in values if str(key).strip()],
                }
            )
            continue
        preview.append({"kind": "side_effect", "node": name})
    return preview


def _static_preview_payload(workflow: dict[str, Any]) -> dict[str, Any]:
    report = analyze_workflow_semantics(
        list(workflow.get("nodes") or []),
        workflow.get("connections") or {},
    )
    oracle = build_oracle_contract(workflow, context_source="current")
    actions = _static_preview_actions(workflow)
    action_count = len(oracle.actionNodes)
    writeback_count = len(oracle.writebackNodes)
    ready = not report.blocking_findings and oracle.contractCoverage == "full"
    return {
        "ready": ready,
        "status": "passed" if ready else "needs_attention",
        "coverage": oracle.contractCoverage,
        "oracle": oracle.model_dump(exclude_none=True),
        "probe_evidence": [],
        "eligible_count": max(action_count, writeback_count),
        "action_count": action_count,
        "writeback_count": writeback_count,
        "projected_second_run": {
            "eligible_count": None,
            "action_count": None,
            "writeback_count": None,
        },
        "actions": actions,
        "findings": [finding.message for finding in report.findings],
    }


async def preview_workflow_run(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_payload: dict[str, Any] | None,
    conversation_id: str | None = None,
    execution_policy: ExecutionPolicy = "safe",
    issue_token: bool = True,
) -> dict[str, Any]:
    workflow_id = str(workflow.get("id") or "")
    fingerprint = workflow_fingerprint(workflow)
    policy = normalize_execution_policy(execution_policy)
    payload = {
        "workflow_id": workflow_id,
        "workflow_fingerprint": fingerprint,
        "execution_policy": policy,
        "preview_basis": preview_basis_for_policy(policy),
    }
    if preview_requires_sandbox(policy):
        metadata = await store.get_workflow_metadata(user_id, workflow_id)
        input_schema = _workflow_input_schema_from_metadata(metadata)
        result = await run_sandbox_test(
            workflow,
            user_id=user_id,
            input_schema=input_schema,
            intent=str(workflow.get("name") or "Workflow"),
            input_payload=input_payload,
        )
        payload.update(
            {
                "ready": (
                    result.passed
                    and not result.skipped
                    and result.coverage == "full"
                    and result.status in {"passed", "no_action"}
                ),
                "status": result.status,
                "coverage": result.coverage,
                "oracle": result.oracle.model_dump(exclude_none=True) if result.oracle else None,
                "probe_evidence": [
                    item.model_dump(exclude_none=True) for item in result.probe_evidence
                ],
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
        )
    else:
        payload.update(_static_preview_payload(workflow))
    if not payload["ready"] or not issue_token:
        return payload
    preview = await store.save_workflow_run_preview(
        user_id,
        workflow_id,
        workflow_fingerprint=fingerprint,
        input_payload=input_payload,
        payload=payload,
        conversation_id=conversation_id,
        execution_policy=policy,
        preview_basis=preview_basis_for_policy(policy),
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
    conversation_id: str | None = None,
    execution_policy: ExecutionPolicy = "safe",
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
        conversation_id=conversation_id,
        execution_policy=normalize_execution_policy(execution_policy),
        preview_basis=preview_basis_for_policy(normalize_execution_policy(execution_policy)),
    )
    return preview is not None


async def preview_workflow_batch(
    workflow: dict[str, Any],
    *,
    user_id: str,
    rows: list[dict[str, Any]],
    conversation_id: str | None = None,
    execution_policy: ExecutionPolicy = "safe",
) -> dict[str, Any]:
    """Probe every batch row without side effects and issue one aggregate approval."""

    policy = normalize_execution_policy(execution_policy)
    if not preview_requires_sandbox(policy):
        raise ValueError("Fast execution policy is not supported for batch previews in V1.")
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
        "execution_policy": policy,
        "preview_basis": preview_basis_for_policy(policy),
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
        conversation_id=conversation_id,
        execution_policy=policy,
        preview_basis=preview_basis_for_policy(policy),
    )
    payload["preview_token"] = preview.token
    payload["expires_at"] = preview.expires_at
    return payload
