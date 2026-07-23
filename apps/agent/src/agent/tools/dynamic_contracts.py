"""Dynamic workflow-card and node-contract helpers for build-time enrichment."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping

import structlog
from pydantic_ai import ModelRetry

from src.platforms.google_clients import PlatformActionError, SheetsClient
from src.registry import get_node_contract

log = structlog.get_logger()

_GOOGLE_SHEETS_TYPE = "n8n-nodes-base.googleSheets"
_GOOGLE_SHEETS_WRITE_OPERATIONS = {"append", "appendorupdate", "update"}
_GMAIL_TYPE = "n8n-nodes-base.gmail"
_GMAIL_MUTATION_OPERATIONS = {
    "delete",
    "markasread",
    "markasunread",
    "reply",
    "send",
    "trash",
}


@dataclass
class DynamicContractResolution:
    contract_selections: list[dict[str, Any]] = field(default_factory=list)

    def as_resources_patch(self) -> dict[str, Any]:
        if not self.contract_selections:
            return {}
        return {
            "lookup": {
                "version": 1,
                "node_contracts": self.contract_selections,
            }
        }


def stable_lookup_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def summarize_workflow_card(card: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "card_id": str(card.get("id") or ""),
        "name": str(card.get("name") or ""),
        "hash": stable_lookup_hash(card),
    }
    return {key: value for key, value in summary.items() if value}


def summarize_node_contract_selection(
    *,
    node_name: str,
    node_type: str,
    type_version: int | float | None,
    resource: str | None,
    operation: str | None,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    summary = {
        "node_name": node_name,
        "node_type": node_type,
        "type_version": type_version,
        "resource": resource,
        "operation": operation,
        "contract_id": str(contract.get("id") or ""),
        "hash": stable_lookup_hash(contract),
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [])}


async def resolve_dynamic_node_contracts(
    user_id: str,
    node_dicts: list[dict[str, Any]],
) -> DynamicContractResolution:
    resolution = DynamicContractResolution()
    for node in node_dicts:
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            continue
        node_type = str(node.get("type") or "").strip()
        if not node_type:
            continue
        type_version = node.get("typeVersion")
        resource = _string_or_none(parameters.get("resource"))
        operation = _string_or_none(parameters.get("operation"))
        operation_key = operation.casefold() if operation else None
        contract = get_node_contract(
            node_type,
            type_version=type_version if isinstance(type_version, (int, float)) else None,
            resource=resource,
            operation=operation,
        )
        contract_problem = (
            not isinstance(contract, Mapping)
            or bool(contract.get("error"))
            or bool(contract.get("availableResources"))
            or bool(contract.get("availableOperations"))
        )
        if contract_problem and _requires_exact_side_effect_contract(node_type, operation_key):
            raise ModelRetry(
                f"Node '{node.get('name') or node_type}' requires an exact supported "
                f"node contract for typeVersion={type_version}, resource={resource!r}, "
                f"operation={operation!r}. Select a supported resource/operation and call "
                "get_node_contract before creating the workflow."
            )
        if isinstance(contract, Mapping) and not contract_problem:
            _apply_contract_defaults(parameters, contract)
            _validate_contract_parameters(node, parameters, contract)
            resolution.contract_selections.append(
                summarize_node_contract_selection(
                    node_name=str(node.get("name") or node_type),
                    node_type=node_type,
                    type_version=type_version if isinstance(type_version, (int, float)) else None,
                    resource=resource,
                    operation=operation,
                    contract=contract,
                )
            )
        if node_type == _GOOGLE_SHEETS_TYPE and operation_key in _GOOGLE_SHEETS_WRITE_OPERATIONS:
            await _resolve_google_sheets_headers(user_id, node)
    return resolution


def merge_lookup_resources(
    existing_resources: Mapping[str, Any] | None,
    patch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    resources = dict(existing_resources or {})
    lookup_patch = patch.get("lookup") if isinstance(patch, Mapping) else None
    if not isinstance(lookup_patch, Mapping):
        return resources

    lookup = dict(resources.get("lookup") or {})
    lookup["version"] = int(lookup_patch.get("version") or lookup.get("version") or 1)
    for key in ("workflow_cards", "node_contracts"):
        merged = _merge_lookup_entries(lookup.get(key), lookup_patch.get(key))
        if merged:
            lookup[key] = merged
    resources["lookup"] = lookup
    return resources


def _merge_lookup_entries(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    merged: list[dict[str, Any]] = []
    for bucket in (existing, incoming):
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if not isinstance(item, Mapping):
                continue
            identifier = str(
                item.get("card_id") or item.get("contract_id") or item.get("node_name") or ""
            )
            digest = str(item.get("hash") or "")
            key = (identifier, digest)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(item))
    return merged


def _apply_contract_defaults(parameters: dict[str, Any], contract: Mapping[str, Any]) -> None:
    candidate = contract.get("parameter_overrides")
    if not isinstance(candidate, Mapping):
        candidate = contract.get("parameters")
    if not isinstance(candidate, Mapping):
        candidate = contract.get("parameterDefaults")
    if not isinstance(candidate, Mapping):
        return
    _deep_merge_missing(parameters, dict(candidate))


def _nested_parameter_value(parameters: Mapping[str, Any], path: str) -> Any:
    current: Any = parameters
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current.get(part)
    return current


def _validate_contract_parameters(
    node: Mapping[str, Any],
    parameters: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    required = contract.get("requiredParameters")
    if not isinstance(required, list):
        return
    missing: list[str] = []
    for raw_path in required:
        path = str(raw_path)
        if " when " in path:
            continue
        value = _nested_parameter_value(parameters, path)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(path)
    if missing:
        raise ModelRetry(
            f"Node '{node.get('name') or node.get('type')}' does not satisfy its exact "
            f"operation contract. Missing required parameter(s): {', '.join(missing)}."
        )


def _deep_merge_missing(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if key not in target:
            target[key] = value
            continue
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _deep_merge_missing(existing, dict(value))


async def _resolve_google_sheets_headers(user_id: str, node: dict[str, Any]) -> None:
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        return
    document_id = _resource_locator_value(parameters.get("documentId"))
    sheet_name = _resource_locator_value(parameters.get("sheetName"))
    columns = parameters.get("columns")
    if not document_id or not sheet_name or not isinstance(columns, dict):
        raise ModelRetry(
            f"Google Sheets write node '{node.get('name')}' requires concrete documentId, "
            "sheetName, and parameters.columns before its live header contract can be resolved."
        )

    try:
        data = await SheetsClient(user_id).read_range(
            spreadsheet_id=document_id,
            range=f"{sheet_name}!1:1",
        )
    except PlatformActionError as exc:
        log.warning(
            "google_sheets_header_resolution_blocked",
            node_name=node.get("name"),
            reason=exc.status,
        )
        raise ModelRetry(
            f"Could not resolve live Google Sheets headers for node '{node.get('name')}' "
            f"({exc.status}). Connect the managed Google Sheets account or choose an "
            "accessible spreadsheet before creating this side-effect workflow."
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging path
        log.warning(
            "google_sheets_header_resolution_failed",
            node_name=node.get("name"),
            error=str(exc),
        )
        raise ModelRetry(
            f"Could not resolve live Google Sheets headers for node '{node.get('name')}'. "
            "The workflow was not created because its write contract is unverified."
        ) from exc

    headers = _extract_sheet_headers(data)
    if not headers:
        raise ModelRetry(
            f"Google Sheets node '{node.get('name')}' returned no header row. Add a header "
            "row or select the correct sheet before creating this write workflow."
        )
    columns["schema"] = [_sheets_schema_entry(header) for header in headers]
    header_lookup = {_normalize_header_key(header): header for header in headers}

    matching = columns.get("matchingColumns")
    if isinstance(matching, list):
        unknown_matching = [
            str(column)
            for column in matching
            if _normalize_header_key(str(column)) not in header_lookup
        ]
        if unknown_matching:
            raise ModelRetry(
                f"Google Sheets node '{node.get('name')}' has matchingColumns that do not "
                f"exist in the live sheet header: {unknown_matching}."
            )
        columns["matchingColumns"] = [
            header_lookup.get(_normalize_header_key(str(column)), str(column))
            for column in matching
            if str(column).strip()
        ]

    values = columns.get("value")
    if isinstance(values, dict):
        unknown_values = [
            str(key) for key in values if _normalize_header_key(str(key)) not in header_lookup
        ]
        if unknown_values:
            raise ModelRetry(
                f"Google Sheets node '{node.get('name')}' maps columns that do not exist "
                f"in the live sheet header: {unknown_values}."
            )
        remapped: dict[str, Any] = {}
        for key, value in values.items():
            normalized = _normalize_header_key(str(key))
            remapped[header_lookup.get(normalized, str(key))] = value
        columns["value"] = remapped


def _extract_sheet_headers(data: Mapping[str, Any]) -> list[str]:
    values = data.get("values")
    if not isinstance(values, list) or not values:
        return []
    first_row = values[0]
    if not isinstance(first_row, list):
        return []
    headers = [str(cell).strip() for cell in first_row if str(cell).strip()]
    return headers


def _resource_locator_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        raw = value.get("value")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _normalize_header_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    lowered = ascii_only.casefold()
    return re.sub(r"[^a-z0-9]+", "", lowered)


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _requires_exact_side_effect_contract(node_type: str, operation: str | None) -> bool:
    if node_type == _GOOGLE_SHEETS_TYPE:
        return operation in _GOOGLE_SHEETS_WRITE_OPERATIONS
    if node_type == _GMAIL_TYPE:
        return operation in _GMAIL_MUTATION_OPERATIONS
    return False


def _sheets_schema_entry(column: str) -> dict[str, Any]:
    return {
        "id": column,
        "displayName": column,
        "required": False,
        "defaultMatch": False,
        "display": True,
        "type": "string",
        "canBeUsedToMatch": True,
        "removed": False,
    }
