"""Bounded Google Sheets read-after-write verification for execution evidence."""

from __future__ import annotations

import re
from typing import Any, Mapping

import structlog

from src.agent.schemas import ActionEvidence, Postcondition, WorkflowRunResultData
from src.agent.tools.execution import _item_json_payload, _latest_run_output_items
from src.platforms.google_clients import PlatformActionError, SheetsClient

log = structlog.get_logger()

_SHEETS_TYPE = "n8n-nodes-base.googleSheets"
_WRITE_OPERATIONS = {"append", "appendorupdate", "update"}
_SIMPLE_JSON_EXPR = re.compile(
    r"^\s*=?\s*(?:\{\{\s*)?\$json(?:\.|\[['\"])(?P<field>[A-Za-z0-9_ -]+)"
)
_N8N_EXPRESSION = re.compile(
    r"^\s*(?:=\s*(?:\{\{.*\}\}|.+)|\{\{.*\}\})\s*$",
    re.DOTALL,
)


def _resource_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        raw = value.get("value")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _nodes_by_name(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node["name"]): node
        for node in workflow.get("nodes") or []
        if isinstance(node, dict) and node.get("name")
    }


def _literal_or_output(value: Any, *, target: str, output: Mapping[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    if _N8N_EXPRESSION.match(value):
        # n8n expressions may reference the current item or another node, for
        # example ``={{ $('IF').item.json.record_id }}``. The write node's
        # immutable execution output is the authoritative resolved value; do
        # not compare the remote row with the unevaluated expression text.
        if target in output:
            return output.get(target)
    match = _SIMPLE_JSON_EXPR.match(value)
    if match is None:
        return value
    source_field = match.group("field").strip()
    if target in output:
        return output.get(target)
    return output.get(source_field)


def _expected_rows(
    execution: dict[str, Any],
    *,
    node_name: str,
    parameters: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, Any]]] | None:
    columns = parameters.get("columns")
    if not isinstance(columns, Mapping):
        return None
    matching = columns.get("matchingColumns")
    values = columns.get("value")
    if not isinstance(matching, list) or not matching or not isinstance(values, Mapping):
        return None
    matching_columns = [str(item).strip() for item in matching if str(item).strip()]
    if not matching_columns:
        return None

    expected: list[dict[str, Any]] = []
    for item in _latest_run_output_items(execution, node_name):
        output = _item_json_payload(item)
        if not output:
            return None
        row: dict[str, Any] = {}
        for column in matching_columns:
            if output.get(column) in (None, ""):
                return None
            row[column] = output.get(column)
        for target, configured in values.items():
            resolved = _literal_or_output(configured, target=str(target), output=output)
            if resolved is None:
                return None
            row[str(target)] = resolved
        expected.append(row)
    return matching_columns, expected


def _rows_from_range(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = data.get("values")
    if not isinstance(values, list) or len(values) < 2 or not isinstance(values[0], list):
        return []
    headers = [str(value).strip() for value in values[0]]
    rows: list[dict[str, Any]] = []
    for raw_row in values[1:]:
        if not isinstance(raw_row, list):
            continue
        rows.append(
            {
                header: raw_row[index] if index < len(raw_row) else ""
                for index, header in enumerate(headers)
                if header
            }
        )
    return rows


def _expected_rows_verified(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    *,
    matching_columns: list[str],
) -> bool:
    for expected_row in expected:
        matched = next(
            (
                row
                for row in actual
                if all(
                    str(row.get(column, "")).strip() == str(expected_row.get(column, "")).strip()
                    for column in matching_columns
                )
            ),
            None,
        )
        if matched is None:
            return False
        if any(
            str(matched.get(column, "")).strip() != str(value).strip()
            for column, value in expected_row.items()
        ):
            return False
    return True


def _with_read_after_write_result(
    result: WorkflowRunResultData,
    *,
    passed: bool,
    details: str,
    verified_nodes: list[tuple[str, int]],
) -> WorkflowRunResultData:
    postconditions: list[Postcondition] = []
    for item in result.assessment.postconditions:
        if item.code == "writeback_effect_verified":
            postconditions.append(
                item.model_copy(
                    update={
                        "status": "verified" if passed else "failed",
                        "details": details,
                    }
                )
            )
        else:
            postconditions.append(item)

    warnings = [
        item for item in result.assessment.warnings if item.code != "writeback_effect_unverified"
    ]
    reasons = [
        reason
        for reason in result.assessment.reasons
        if "no deterministic remote-state verifier" not in reason
    ]
    evidence = list(result.assessment.evidence)
    if passed:
        evidence.extend(
            ActionEvidence(
                kind="effect_verified",
                nodeName=node_name,
                nodeType=_SHEETS_TYPE,
                mutation=True,
                outputItemCount=count,
                effectVerified=True,
                verifier="sheets_read_after_write",
            )
            for node_name, count in verified_nodes
        )
    all_verified = passed and all(
        item.status in {"verified", "not_applicable"} for item in postconditions
    )
    assessment = result.assessment.model_copy(
        update={
            "postconditions": postconditions,
            "postconditionsVerified": all_verified,
            "warnings": warnings,
            "reasons": reasons,
            "evidence": evidence,
            "coverage": "full" if all_verified else result.assessment.coverage,
        }
    )
    if all_verified and result.assessment.executionOk and result.assessment.exactContextVerified:
        return result.model_copy(
            update={
                "functionalStatus": "verified",
                "claimableOutcome": "run_verified",
                "assessment": assessment,
                "summary": "Workflow run and remote write-back were verified.",
            }
        )
    return result.model_copy(update={"assessment": assessment})


async def verify_sheets_read_after_write(
    user_id: str,
    *,
    workflow: dict[str, Any] | None,
    execution: dict[str, Any],
    result: WorkflowRunResultData,
) -> WorkflowRunResultData:
    oracle = result.assessment.oracle
    if (
        not workflow
        or oracle is None
        or not oracle.writebackNodes
        or int(result.assessment.writebackCount or 0) <= 0
    ):
        return result

    nodes = _nodes_by_name(workflow)
    verified_nodes: list[tuple[str, int]] = []
    try:
        for node_name in oracle.writebackNodes:
            node = nodes.get(node_name)
            parameters = node.get("parameters") if isinstance(node, dict) else None
            if (
                not isinstance(node, dict)
                or node.get("type") != _SHEETS_TYPE
                or not isinstance(parameters, dict)
                or str(parameters.get("operation") or "").casefold() not in _WRITE_OPERATIONS
            ):
                return result
            document_id = _resource_value(parameters.get("documentId"))
            sheet_name = _resource_value(parameters.get("sheetName"))
            expected = _expected_rows(
                execution,
                node_name=node_name,
                parameters=parameters,
            )
            if not document_id or not sheet_name or expected is None:
                return _with_read_after_write_result(
                    result,
                    passed=False,
                    details=(
                        "Expected identity/value rows could not be derived from execution data."
                    ),
                    verified_nodes=[],
                )
            matching_columns, expected_rows = expected
            if not expected_rows:
                return result
            data = await SheetsClient(user_id).read_range(
                spreadsheet_id=document_id,
                range=f"{sheet_name}!A1:ZZ500",
            )
            actual_rows = _rows_from_range(data)
            if not _expected_rows_verified(
                expected_rows,
                actual_rows,
                matching_columns=matching_columns,
            ):
                return _with_read_after_write_result(
                    result,
                    passed=False,
                    details="Remote Sheet rows did not match the expected identity/value set.",
                    verified_nodes=[],
                )
            verified_nodes.append((node_name, len(expected_rows)))
    except PlatformActionError as exc:
        log.info("sheets_read_after_write_unavailable", status=exc.status)
        return result
    except Exception as exc:  # pragma: no cover - defensive provider boundary
        log.warning(
            "sheets_read_after_write_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return result

    return _with_read_after_write_result(
        result,
        passed=True,
        details="Expected identities and values were observed in a bounded remote Sheet read.",
        verified_nodes=verified_nodes,
    )
