"""Execution result summarization helpers."""

from typing import Any, Literal

import structlog

from src.agent.assurance import analyze_workflow_semantics, workflow_fingerprint
from src.agent.schemas import (
    ActionEvidence,
    ClaimableOutcome,
    FunctionalStatus,
    WorkflowAssessmentWarning,
    WorkflowOutputField,
    WorkflowResultPresentation,
    WorkflowResultPresentationField,
    WorkflowRunAssessment,
    WorkflowRunDataHint,
    WorkflowRunResultData,
)
from src.agent.tools.common import _preview_value

log = structlog.get_logger()

_MAX_OUTPUT_NODES = 4
_MAX_OUTPUT_ITEMS = 3
_TECHNICAL_OUTPUT_KEYS = {
    "headers",
    "params",
    "query",
    "webhookUrl",
    "executionMode",
}
_TECHNICAL_NODE_TYPES = {
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.respondToWebhook",
}
_SAFE_HTTP_METHODS = {"get", "head", "options"}
_READ_OPERATIONS = {
    "download",
    "get",
    "getall",
    "lookup",
    "read",
    "search",
}
_MUTATION_OPERATIONS = {
    "addlabel",
    "addlabels",
    "append",
    "archive",
    "clear",
    "copy",
    "create",
    "delete",
    "insert",
    "label",
    "markasread",
    "markasunread",
    "move",
    "remove",
    "removelabel",
    "removelabels",
    "reply",
    "send",
    "trash",
    "update",
    "upload",
}
_WRITEBACK_TYPE_MARKERS = (
    "airtable",
    "googlesheets",
    "mariadb",
    "mssql",
    "mysql",
    "notion",
    "postgres",
    "spreadsheet",
)


def _node_type_by_name(workflow: dict[str, Any] | None) -> dict[str, str]:
    if not workflow:
        return {}
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return {}
    return {
        str(node.get("name")): str(node.get("type"))
        for node in nodes
        if isinstance(node, dict) and node.get("name") and node.get("type")
    }


def _nodes_by_name(workflow: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not workflow or not isinstance(workflow.get("nodes"), list):
        return {}
    return {
        str(node["name"]): node
        for node in workflow["nodes"]
        if isinstance(node, dict) and node.get("name")
    }


def _is_mutation_node(node: dict[str, Any] | None) -> bool:
    """Conservatively identify external mutations from generic n8n configuration."""

    if not node:
        return False
    node_type = str(node.get("type") or "")
    if node_type in _TECHNICAL_NODE_TYPES or node_type.endswith("Trigger"):
        return False
    parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
    lowered_type = node_type.lower()
    if lowered_type.endswith(".httprequest"):
        method = str(parameters.get("method") or parameters.get("requestMethod") or "GET").lower()
        return method not in _SAFE_HTTP_METHODS

    operation = str(parameters.get("operation") or parameters.get("action") or "").lower()
    if operation in _READ_OPERATIONS:
        return False
    if operation in _MUTATION_OPERATIONS:
        return True
    return False


def _is_writeback_node(node: dict[str, Any] | None) -> bool:
    if not node or not _is_mutation_node(node):
        return False
    lowered_type = str(node.get("type") or "").lower()
    return any(marker in lowered_type for marker in _WRITEBACK_TYPE_MARKERS)


def _run_data_hints(
    execution: dict[str, Any],
    *,
    workflow: dict[str, Any] | None,
) -> list[WorkflowRunDataHint]:
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    run_data = result_data.get("runData") if isinstance(result_data, dict) else None
    if not isinstance(run_data, dict):
        return []

    nodes = _nodes_by_name(workflow)
    hints: list[WorkflowRunDataHint] = []
    for node_name, runs in run_data.items():
        if not isinstance(runs, list) or not runs:
            continue
        latest_run = runs[-1] if isinstance(runs[-1], dict) else {}
        node_data = latest_run.get("data") if isinstance(latest_run.get("data"), dict) else {}
        main_outputs = node_data.get("main") if isinstance(node_data.get("main"), list) else []
        branch_counts = [len(branch) if isinstance(branch, list) else 0 for branch in main_outputs]
        run_error = latest_run.get("error")
        hints.append(
            WorkflowRunDataHint(
                nodeName=str(node_name),
                nodeType=str(nodes.get(str(node_name), {}).get("type") or "") or None,
                mutation=_is_mutation_node(nodes.get(str(node_name))),
                runStatus=(
                    str(latest_run.get("executionStatus"))
                    if latest_run.get("executionStatus") is not None
                    else None
                ),
                branchItemCounts=branch_counts,
                outputItemCount=sum(branch_counts),
                hasError=bool(run_error),
            )
        )
    return hints


def _strip_technical_output(value: Any) -> Any | None:
    if isinstance(value, dict):
        cleaned = {
            str(key): _strip_technical_output(item)
            for key, item in value.items()
            if key not in _TECHNICAL_OUTPUT_KEYS
        }
        cleaned = {key: item for key, item in cleaned.items() if item not in ({}, [], None, "")}
        if cleaned == {"body": {"source": "conduut_test"}}:
            return None
        if cleaned == {"source": "conduut_test"}:
            return None
        return cleaned or None
    if isinstance(value, list):
        cleaned_list = [_strip_technical_output(item) for item in value]
        cleaned_list = [item for item in cleaned_list if item not in ({}, [], None, "")]
        return cleaned_list or None
    return value


def _visible_response_body(response: dict[str, Any] | None) -> Any | None:
    if not response:
        return None
    return _strip_technical_output(response.get("body"))


def _first_result_item(body: Any) -> Any:
    if isinstance(body, list):
        return body[0] if body else None
    return body


def _resolve_presentation(
    response: dict[str, Any] | None,
    output_schema: list[WorkflowOutputField],
    *,
    title: str | None = None,
) -> WorkflowResultPresentation | None:
    if not output_schema:
        return None
    item = _first_result_item(_visible_response_body(response))
    if not isinstance(item, dict):
        return None
    fields: list[WorkflowResultPresentationField] = []
    for field in output_schema:
        value = item.get(field.name)
        if value in (None, ""):
            continue
        fields.append(
            WorkflowResultPresentationField(
                label=field.label,
                format=field.format,
                value=value,
            )
        )
    if not fields:
        return None
    return WorkflowResultPresentation(title=title, fields=fields)


def _extract_execution_outputs(
    execution: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    run_data = result_data.get("runData") if isinstance(result_data, dict) else None
    if not isinstance(run_data, dict):
        return []

    node_types = _node_type_by_name(workflow)
    nodes = _nodes_by_name(workflow)
    outputs: list[dict[str, Any]] = []
    for node_name, runs in run_data.items():
        node_type = node_types.get(str(node_name))
        if node_type in _TECHNICAL_NODE_TYPES:
            continue
        if not isinstance(runs, list) or not runs:
            continue
        latest_run = runs[-1] if isinstance(runs[-1], dict) else {}
        node_data = latest_run.get("data") if isinstance(latest_run, dict) else None
        main_outputs = node_data.get("main") if isinstance(node_data, dict) else None
        mutation = _is_mutation_node(nodes.get(str(node_name)))
        if not isinstance(main_outputs, list) and not mutation:
            continue
        if not isinstance(main_outputs, list):
            main_outputs = []

        items: list[Any] = []
        visible_item_count = 0
        for output_index in main_outputs:
            if not isinstance(output_index, list):
                continue
            for item in output_index:
                if isinstance(item, dict) and "json" in item:
                    cleaned = _strip_technical_output(item.get("json"))
                else:
                    cleaned = _strip_technical_output(item)
                if cleaned not in ({}, [], None, ""):
                    visible_item_count += 1
                    if len(items) < _MAX_OUTPUT_ITEMS:
                        items.append(_preview_value(cleaned))
        if items or mutation:
            output = {
                "nodeName": str(node_name),
                "itemCount": visible_item_count,
                "items": items,
            }
            if mutation:
                output["mutation"] = True
            outputs.append(output)

    return outputs[-_MAX_OUTPUT_NODES:]


_MAX_ERROR_DETAIL = 300


def _combined_error_message(error: dict[str, Any]) -> str | None:
    """Combine n8n's generic `message` with the actionable `description`.

    HTTP node errors put the useful detail (e.g. the API's response text) in
    `description`; the bare `message` ("Bad request") is not enough to act on.
    """

    pieces: list[str] = []
    for key in ("message", "description"):
        value = error.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if len(text) > _MAX_ERROR_DETAIL:
            text = f"{text[:_MAX_ERROR_DETAIL]}..."
        if text not in pieces:
            pieces.append(text)
    parameter_name = _error_parameter_name(error)
    if parameter_name:
        pieces.append(f"Parameter: {parameter_name}")
    return " — ".join(pieces) or None


def _error_parameter_name(error: dict[str, Any]) -> str | None:
    """Extract n8n's actionable missing/invalid parameter identifier.

    Node execution errors commonly keep it under ``extra.parameterName``;
    older/newer node implementations may expose it directly or in ``context``.
    """

    for container in (error, error.get("extra"), error.get("context")):
        if not isinstance(container, dict):
            continue
        value = container.get("parameterName")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _transport_status_code(response: dict[str, Any] | None) -> int | None:
    if not response:
        return None
    value = response.get("statusCode")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _functional_assessment(
    *,
    raw_status: str,
    error_message: str | None,
    response: dict[str, Any] | None,
    workflow: dict[str, Any] | None,
    hints: list[WorkflowRunDataHint],
    has_visible_result: bool,
) -> tuple[FunctionalStatus, ClaimableOutcome, WorkflowRunAssessment]:
    nodes = _nodes_by_name(workflow)
    configured_mutations = [name for name, node in nodes.items() if _is_mutation_node(node)]
    configured_writebacks = [
        name for name in configured_mutations if _is_writeback_node(nodes.get(name))
    ]
    configured_actions = [
        name for name in configured_mutations if not _is_writeback_node(nodes.get(name))
    ]
    mutation_hints = [hint for hint in hints if hint.mutation]
    executed_mutations = [hint.nodeName for hint in mutation_hints]
    successful_mutations = [
        hint.nodeName
        for hint in mutation_hints
        if not hint.hasError
        and hint.runStatus not in {"error", "failed"}
        and hint.outputItemCount > 0
    ]
    zero_output_mutations = [
        hint.nodeName
        for hint in mutation_hints
        if not hint.hasError
        and hint.runStatus not in {"error", "failed"}
        and hint.outputItemCount == 0
    ]
    mutation_errors = [
        hint.nodeName
        for hint in mutation_hints
        if hint.hasError or hint.runStatus in {"error", "failed"}
    ]
    successful_action_hints = [
        hint
        for hint in mutation_hints
        if hint.nodeName in successful_mutations
        and not _is_writeback_node(nodes.get(hint.nodeName))
    ]
    successful_writeback_hints = [
        hint
        for hint in mutation_hints
        if hint.nodeName in successful_mutations and _is_writeback_node(nodes.get(hint.nodeName))
    ]
    action_count = sum(hint.outputItemCount for hint in successful_action_hints)
    writeback_count = sum(hint.outputItemCount for hint in successful_writeback_hints)
    transport_status = _transport_status_code(response)
    transport_failed = transport_status is not None and transport_status >= 400
    raw_failed = raw_status in {"error", "failed"} or bool(error_message)
    reasons: list[str] = []
    warnings: list[WorkflowAssessmentWarning] = []

    def add_warning(
        code: str,
        message: str,
        *,
        severity: Literal["error", "warning", "shadow"] = "warning",
        node_name: str | None = None,
    ) -> None:
        reasons.append(message)
        warnings.append(
            WorkflowAssessmentWarning(
                code=code,
                severity=severity,
                nodeName=node_name,
                message=message,
            )
        )

    if raw_failed:
        add_warning(
            "execution_failed",
            "The raw execution status or execution error reports failure.",
            severity="error",
        )
    if transport_failed:
        add_warning(
            "transport_error",
            f"The workflow transport returned HTTP {transport_status}.",
            severity="error",
        )
    if mutation_errors:
        add_warning(
            "mutation_failed",
            f"Mutation node(s) failed: {', '.join(mutation_errors)}.",
            severity="error",
        )
    if zero_output_mutations:
        add_warning(
            "zero_output_mutation",
            f"Mutation node(s) ran without observable output: {', '.join(zero_output_mutations)}.",
        )
    cardinality_mismatch = bool(
        configured_actions
        and configured_writebacks
        and (action_count or writeback_count)
        and action_count != writeback_count
    )
    if cardinality_mismatch:
        add_warning(
            "count_mismatch",
            "Action and required write-back counts do not match "
            f"({action_count} action, {writeback_count} write-back).",
            severity="error",
        )

    if raw_failed or transport_failed or mutation_errors:
        if successful_mutations:
            functional_status: FunctionalStatus = "partial"
        else:
            functional_status = "failed"
    elif zero_output_mutations:
        functional_status = "partial" if successful_mutations else "needs_attention"
    elif configured_mutations:
        if successful_mutations:
            functional_status = "verified"
        elif not executed_mutations and hints:
            functional_status = "no_action"
            reasons.append(
                "No mutation node ran; the workflow completed without an action to take."
            )
        elif not hints:
            functional_status = "unknown"
            add_warning(
                "execution_detail_missing",
                "No execution run data was available to verify the outcome.",
            )
        else:
            functional_status = "needs_attention"
            reasons.append("Mutation nodes ran without enough evidence to verify their effect.")
    elif has_visible_result:
        functional_status = "verified"
    elif hints:
        functional_status = "no_action"
        reasons.append("The workflow completed with no visible result or mutation.")
    else:
        functional_status = "unknown"
        add_warning(
            "execution_detail_missing",
            "No execution run data was available to verify the outcome.",
        )

    if cardinality_mismatch:
        functional_status = "partial" if action_count else "needs_attention"

    assurance_partial = False
    assurance_blocking = False
    if workflow:
        report = analyze_workflow_semantics(
            list(workflow.get("nodes") or []), workflow.get("connections") or {}
        )
        assurance_partial = any(
            finding.code == "contract_coverage_missing" for finding in report.findings
        )
        assurance_blocking = bool(report.blocking_findings)
        if assurance_partial or assurance_blocking:
            for finding in report.findings:
                add_warning(
                    finding.code,
                    finding.message,
                    severity="error" if finding.blocking else "shadow",
                    node_name=finding.node_name,
                )
        if functional_status in {"verified", "no_action"} and (
            assurance_partial or assurance_blocking
        ):
            functional_status = "needs_attention"

    claimable: ClaimableOutcome = "none"
    if functional_status == "verified":
        claimable = "run_verified"
    elif functional_status == "no_action":
        claimable = "no_action"

    duplicate_risk = bool(
        action_count > 0
        and (
            transport_failed
            or mutation_errors
            or cardinality_mismatch
            or any(_is_writeback_node(nodes.get(name)) for name in zero_output_mutations)
        )
    )
    coverage: Literal["full", "partial", "none"]
    if not hints:
        coverage = "none"
    elif assurance_partial or assurance_blocking:
        coverage = "partial"
    elif functional_status in {"verified", "no_action"}:
        coverage = "full"
    else:
        coverage = "partial"
    evidence = [
        ActionEvidence(
            kind="node_run",
            nodeName=hint.nodeName,
            nodeType=hint.nodeType,
            mutation=hint.mutation,
            runStatus=hint.runStatus,
            outputItemCount=hint.outputItemCount,
        )
        for hint in hints
    ]

    assessment = WorkflowRunAssessment(
        transportStatusCode=transport_status,
        configuredMutationNodes=configured_mutations,
        executedMutationNodes=executed_mutations,
        successfulMutationNodes=successful_mutations,
        zeroOutputMutationNodes=zero_output_mutations,
        runDataHints=hints,
        reasons=reasons,
        transportOk=(None if transport_status is None else not transport_failed),
        executionOk=not raw_failed,
        coverage=coverage,
        eligibleCount=(
            0
            if functional_status == "no_action" and bool(configured_mutations)
            else max(action_count, writeback_count) or None
        ),
        actionCount=action_count,
        writebackCount=writeback_count,
        postconditionsVerified=functional_status in {"verified", "no_action"},
        duplicateRisk=duplicate_risk,
        warnings=warnings,
        evidence=evidence,
    )
    return functional_status, claimable, assessment


def _summarize_execution(
    execution: dict[str, Any],
    *,
    response: dict[str, Any] | None = None,
    full_response: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    output_schema: list[WorkflowOutputField] | None = None,
) -> WorkflowRunResultData:
    status = execution.get("status") or ("success" if execution.get("finished") else "unknown")
    execution_id = str(execution.get("id", "")) or None
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    error = result_data.get("error") if isinstance(result_data, dict) else None
    outputs = _extract_execution_outputs(execution, workflow=workflow)
    run_data_hints = _run_data_hints(execution, workflow=workflow)
    visible_response = _visible_response_body(response)
    if visible_response not in ({}, [], None, "") and not outputs:
        outputs = [
            {
                "nodeName": "Output",
                "itemCount": 1,
                "items": [_preview_value(visible_response)],
            }
        ]
    failed_node = None
    error_message = None
    if isinstance(error, dict):
        failed_node = (
            error.get("node", {}).get("name") if isinstance(error.get("node"), dict) else None
        )
        error_message = _combined_error_message(error)
    output_count = sum(int(output.get("itemCount") or 0) for output in outputs)
    has_visible_result = output_count > 0 or visible_response not in ({}, [], None, "")
    functional_status, claimable_outcome, assessment = _functional_assessment(
        raw_status=str(status),
        error_message=error_message,
        response=response,
        workflow=workflow,
        hints=run_data_hints,
        has_visible_result=has_visible_result,
    )
    log.info(
        "workflow_execution_assessed",
        workflow_id=str(execution.get("workflowId", "")),
        execution_id=execution_id,
        fingerprint=workflow_fingerprint(workflow) if workflow else None,
        functional_status=functional_status,
        coverage=assessment.coverage,
        eligible_count=assessment.eligibleCount,
        action_count=assessment.actionCount,
        writeback_count=assessment.writebackCount,
        duplicate_risk=assessment.duplicateRisk,
        rule_codes=[warning.code for warning in assessment.warnings],
    )
    summary = "Workflow run completed."
    if output_count:
        summary = f"Workflow run completed with {output_count} output item(s)."
    if status in {"error", "failed"} or error_message:
        summary = f"Workflow execution failed: {error_message or 'Unknown error'}"
    elif functional_status == "partial":
        summary = "Workflow run completed only partially; review the execution assessment."
    elif functional_status == "failed":
        summary = "Workflow run could not be functionally verified because the transport failed."
    elif functional_status == "no_action":
        summary = "Workflow run completed with no action needed."
    elif functional_status in {"needs_attention", "unknown"}:
        summary = "Workflow run completed, but its functional outcome could not be verified."
    presentation = None
    if status not in {"error", "failed"} and not error_message:
        presentation_source = full_response if full_response is not None else response
        presentation = _resolve_presentation(presentation_source, output_schema or [])
    return WorkflowRunResultData(
        workflowId=str(execution.get("workflowId", "")),
        executionId=execution_id,
        status=str(status),
        summary=summary,
        functionalStatus=functional_status,
        assessment=assessment,
        claimableOutcome=claimable_outcome,
        failedNode=failed_node,
        error=error_message,
        response=(
            response
            if functional_status in {"partial", "needs_attention", "failed", "unknown"}
            or error_message
            else None
        ),
        outputs=outputs,
        presentation=presentation,
    )
