"""Workflow validation helpers used before writing to n8n."""

import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from n8n_registry import NodeRegistry

from src.agent.sandbox_nodes import is_side_effect_node
from src.agent.schemas import WorkflowNode
from src.registry import registry as default_registry

_N8N_TYPE_PREFIXES = ("n8n-nodes-base.", "@n8n/", "n8n-nodes-")
_LANGCHAIN_PREFIX = "@n8n/n8n-nodes-langchain."
# Local-name prefixes of langchain nodes that connect ONLY through ai_* ports
# and have no main input/output. Wired into the main flow they emit nothing and
# silently produce empty downstream data. Agents and chains (agent, chainLlm,
# chatTrigger) DO have main I/O and are intentionally excluded.
_LANGCHAIN_SUBNODE_LOCALS = (
    "lm",  # language / chat models: lmChatOpenAi, lmChatAnthropic, ...
    "memory",  # memoryBufferWindow, memoryRedisChat, ...
    "embeddings",  # embeddingsOpenAi, ...
    "outputParser",  # outputParserStructured, ...
    "textSplitter",  # textSplitterRecursiveCharacterTextSplitter, ...
    "retriever",  # retrieverVectorStore, ...
    "tool",  # toolWorkflow, toolHttpRequest, toolCode, ...
)
# Bare `input.` at the start of an n8n expression reference. The agent confuses
# the graph-compiler ref syntax {ref:'input.x'} with n8n syntax and emits
# {{input.x}} into raw JSON; `input` is not an n8n variable, so the value
# resolves to empty (lost AI prompt / email content). Matches {{input. and the
# whitespace variant {{ input. but not $json.input / nested .input. paths.
_BARE_INPUT_EXPR = re.compile(r"\{\{\s*input\.")
_PLACEHOLDER_EMAIL_DOMAINS = {"email.com", "example.com", "example.org", "example.net"}
_PLACEHOLDER_EMAILS = {
    "receiver@email.com",
    "recipient@email.com",
    "test@email.com",
    "test@example.com",
    "info@example.com",
}
_STATUS_CODE_EXPR = re.compile(
    r"\$json(?:\s*(?:\.|\?\.)\s*statusCode|\s*\[\s*['\"]statusCode['\"]\s*\])",
    re.IGNORECASE,
)


def _as_node_dict(node: WorkflowNode | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(node, WorkflowNode):
        return node.model_dump(exclude_none=True)
    return dict(node)


def _has_n8n_type_prefix(node_type: str) -> bool:
    return node_type.startswith(_N8N_TYPE_PREFIXES)


def _is_langchain_ai_subnode(node_type: str) -> bool:
    """True for langchain sub-nodes that only attach via ai_* ports.

    These nodes (chat models, memory, tools, parsers, ...) have no main I/O.
    Placing them in the main flow yields empty downstream data, so they must
    connect to an AI Agent / chain through an ai_* port instead.
    """

    if not node_type.startswith(_LANGCHAIN_PREFIX):
        return False
    return node_type[len(_LANGCHAIN_PREFIX) :].startswith(_LANGCHAIN_SUBNODE_LOCALS)


def _iter_param_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_param_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_param_strings(nested)


def _validate_input_expressions(node: Mapping[str, Any], label: str) -> list[str]:
    """Flag bare {{input.x}} expressions that n8n cannot resolve."""

    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        return []
    for text in _iter_param_strings(parameters):
        if _BARE_INPUT_EXPR.search(text):
            return [
                f"Node '{label}' uses an invalid expression with bare 'input.' (e.g. "
                "{{input.field}}). 'input' is not an n8n variable, so the value resolves to "
                "empty. Reference runtime input as $('<TriggerNodeName>').first().json.body."
                "<field>."
            ]
    return []


def _reference_key(value: Any) -> str:
    return str(value).strip().lower()


def _node_reference_map(nodes: Sequence[WorkflowNode | Mapping[str, Any]]) -> dict[str, str]:
    references: dict[str, str] = {}

    for index, node in enumerate(nodes):
        data = _as_node_dict(node)
        node_name = data.get("name")
        if not node_name:
            continue

        canonical_name = str(node_name)
        aliases = {
            canonical_name,
            data.get("id"),
            str(index + 1),
            f"node{index + 1}",
            f"node {index + 1}",
        }
        for alias in aliases:
            if alias is not None:
                references[_reference_key(alias)] = canonical_name

    return references


def _resolve_node_reference(value: Any, references: Mapping[str, str]) -> str:
    raw_value = str(value)
    return references.get(_reference_key(raw_value), raw_value)


def _normalize_connection_value(value: Any, references: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, nested in value.items():
            if key == "node":
                normalized[key] = _resolve_node_reference(nested, references)
            else:
                normalized[key] = _normalize_connection_value(nested, references)
        return normalized

    if isinstance(value, list):
        return [_normalize_connection_value(nested, references) for nested in value]

    return value


def _ensure_connection_target(value: Any, default_type: str = "main") -> Any:
    if not isinstance(value, Mapping) or "node" not in value:
        return value
    target = dict(value)
    # The connection type must match the output port: "main" for the main flow,
    # but "ai_languageModel" / "ai_tool" / "ai_memory" etc. for AI sub-node ports.
    # Defaulting AI ports to "main" makes n8n ignore the sub-node (empty agent).
    target.setdefault("type", default_type)
    target.setdefault("index", 0)
    return target


def _normalize_output_connection_groups(value: Any, default_type: str = "main") -> Any:
    if isinstance(value, Mapping) and "node" in value:
        return [[_ensure_connection_target(value, default_type)]]

    if not isinstance(value, list):
        return value

    if all(isinstance(item, Mapping) and "node" in item for item in value):
        return [[_ensure_connection_target(item, default_type) for item in value]]

    groups: list[Any] = []
    for group in value:
        if isinstance(group, Mapping) and "node" in group:
            groups.append([_ensure_connection_target(group, default_type)])
        elif isinstance(group, list):
            groups.append([_ensure_connection_target(item, default_type) for item in group])
        else:
            groups.append(group)
    return groups


def _normalize_connection_shape(value: Any) -> Any:
    if isinstance(value, Mapping) and "node" in value:
        return {"main": [[_ensure_connection_target(value)]]}

    if isinstance(value, list):
        return {"main": _normalize_output_connection_groups(value)}

    if isinstance(value, Mapping):
        return {
            output_type: _normalize_output_connection_groups(output_groups, output_type)
            for output_type, output_groups in value.items()
        }

    return value


def _iter_connection_targets(value: Any):
    if isinstance(value, Mapping):
        if "node" in value:
            yield value
        for nested in value.values():
            yield from _iter_connection_targets(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_connection_targets(nested)


def _main_connection_groups(connection: Any) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    if not isinstance(connection, Mapping):
        return ()

    groups = connection.get("main")
    if not isinstance(groups, list):
        return ()

    normalized: list[tuple[Mapping[str, Any], ...]] = []
    for group in groups:
        if isinstance(group, list):
            normalized.append(
                tuple(
                    target
                    for target in group
                    if isinstance(target, Mapping)
                    and target.get("node")
                    and str(target.get("type") or "main") == "main"
                )
            )
        elif (
            isinstance(group, Mapping)
            and group.get("node")
            and str(group.get("type") or "main") == "main"
        ):
            normalized.append((group,))
        else:
            normalized.append(())
    return tuple(normalized)


def _main_adjacency(connections: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    adjacency: dict[str, list[str]] = {}
    for source, value in connections.items():
        targets: list[str] = []
        for group in _main_connection_groups(value):
            targets.extend(str(target["node"]) for target in group)
        if targets:
            adjacency[str(source)] = targets
    return {source: tuple(targets) for source, targets in adjacency.items()}


def _descendants_from(
    start_nodes: Sequence[str],
    adjacency: Mapping[str, tuple[str, ...]],
    *,
    stop_at: str | None = None,
) -> set[str]:
    descendants: set[str] = set()
    pending = list(start_nodes)
    while pending:
        current = pending.pop()
        if current in descendants:
            continue
        descendants.add(current)
        if stop_at is not None and current == stop_at:
            continue
        pending.extend(adjacency.get(current, ()))
    return descendants


def _split_in_batches_ports(node: Mapping[str, Any]) -> tuple[int, int] | None:
    if node.get("type") != _SPLIT_IN_BATCHES_TYPE:
        return None

    type_version = node.get("typeVersion")
    if not isinstance(type_version, int | float) or isinstance(type_version, bool):
        return None
    if type_version >= 3:
        return (1, 0)
    if type_version >= 2:
        return (0, 1)
    return None


def _split_output_label(output_index: int, branch_name: str) -> str:
    return f"main output {output_index} ('{branch_name}')"


def _node_has_side_effect(node: Mapping[str, Any] | None) -> bool:
    if not isinstance(node, Mapping):
        return False
    return is_side_effect_node(dict(node))


def _validate_split_in_batches_connections(
    raw_nodes: Sequence[Mapping[str, Any]],
    connections: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    nodes_by_name = {
        str(node.get("name")): node for node in raw_nodes if str(node.get("name") or "").strip()
    }
    adjacency = _main_adjacency(connections)
    predecessors: dict[str, list[str]] = {}
    for source, targets in adjacency.items():
        for target in targets:
            predecessors.setdefault(target, []).append(source)

    for name, node in nodes_by_name.items():
        ports = _split_in_batches_ports(node)
        if ports is None:
            continue

        loop_output, done_output = ports
        groups = _main_connection_groups(connections.get(name, {}))
        loop_targets = (
            [str(target["node"]) for target in groups[loop_output]]
            if loop_output < len(groups)
            else []
        )
        done_targets = (
            [str(target["node"]) for target in groups[done_output]]
            if done_output < len(groups)
            else []
        )
        loop_descendants = _descendants_from(loop_targets, adjacency, stop_at=name)
        done_descendants = _descendants_from(done_targets, adjacency, stop_at=name)
        loopback_candidates = tuple(
            source
            for source in predecessors.get(name, [])
            if source != name and (source in loop_descendants or source in done_descendants)
        )
        sanctioned_return_sources = tuple(
            source
            for source in loopback_candidates
            if source in loop_descendants and source not in done_descendants
        )
        wrong_return_sources = tuple(
            source
            for source in loopback_candidates
            if source not in loop_descendants or source in done_descendants
        )
        done_side_effects = sorted(
            node_name
            for node_name in done_descendants
            if node_name != name and _node_has_side_effect(nodes_by_name.get(node_name))
        )
        loop_side_effects = sorted(
            node_name
            for node_name in loop_descendants
            if node_name != name and _node_has_side_effect(nodes_by_name.get(node_name))
        )

        if wrong_return_sources:
            wrong_label = (
                _split_output_label(done_output, "done")
                if any(source in done_descendants for source in wrong_return_sources)
                else f"a non-loop branch of '{name}'"
            )
            errors.append(
                f"Split In Batches node '{name}' loops back from {wrong_label} via "
                f"{', '.join(repr(source) for source in wrong_return_sources)}. For "
                f"typeVersion {node.get('typeVersion')}, the per-item body must leave "
                f"{_split_output_label(loop_output, 'loop')} and only that branch may return "
                f"to '{name}'."
            )

        if loop_descendants and not sanctioned_return_sources:
            errors.append(
                f"Split In Batches node '{name}' sends items into "
                f"{_split_output_label(loop_output, 'loop')} but nothing returns to '{name}'. "
                "Connect the last per-item node back to the Split In Batches node so the next "
                "batch can run."
            )

        if done_side_effects and not loop_side_effects and not sanctioned_return_sources:
            errors.append(
                f"Split In Batches node '{name}' routes side-effect node(s) "
                f"{', '.join(repr(node_name) for node_name in done_side_effects)} from "
                f"{_split_output_label(done_output, 'done')}. That branch runs only after the "
                "loop finishes. Move the per-item action/write-back body to "
                f"{_split_output_label(loop_output, 'loop')} instead."
            )

    return errors


def _main_predecessors(connections: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    predecessors: dict[str, list[str]] = {}
    for source, targets in _main_adjacency(connections).items():
        for target in targets:
            predecessors.setdefault(target, []).append(source)
    return {target: tuple(sources) for target, sources in predecessors.items()}


def _rule_references_status_code(rule: Mapping[str, Any]) -> bool:
    left_value = rule.get("leftValue")
    return isinstance(left_value, str) and bool(_STATUS_CODE_EXPR.search(left_value))


def _node_references_status_code(node: Mapping[str, Any]) -> bool:
    if node.get("type") not in {"n8n-nodes-base.if", "n8n-nodes-base.filter"}:
        return False
    parameters = node.get("parameters")
    conditions = parameters.get("conditions") if isinstance(parameters, Mapping) else None
    rules = conditions.get("conditions") if isinstance(conditions, Mapping) else None
    return isinstance(rules, list) and any(
        isinstance(rule, Mapping) and _rule_references_status_code(rule) for rule in rules
    )


def _bool_parameter(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def _nested_mapping(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _http_request_response_guards(node: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    parameters = node.get("parameters")
    params = parameters if isinstance(parameters, Mapping) else {}
    response_options = _nested_mapping(params, "options", "response", "response")
    full_response = _bool_parameter(response_options.get("fullResponse"))
    never_error = _bool_parameter(response_options.get("neverError"))
    continue_regular_output = str(node.get("onError") or "").strip()
    return full_response, never_error, continue_regular_output == "continueRegularOutput"


def _validate_http_status_condition_flow(
    raw_nodes: Sequence[Mapping[str, Any]],
    connections: Mapping[str, Any],
) -> list[str]:
    nodes_by_name = {
        str(node.get("name")): node for node in raw_nodes if str(node.get("name") or "").strip()
    }
    adjacency = _main_adjacency(connections)
    predecessors = _main_predecessors(connections)
    errors: list[str] = []
    seen: set[str] = set()

    for node_name, node in nodes_by_name.items():
        if not _node_references_status_code(node):
            continue

        pending = list(predecessors.get(node_name, ()))
        visited: set[str] = set()
        http_sources: set[str] = set()
        while pending:
            source = pending.pop()
            if source in visited:
                continue
            visited.add(source)
            source_node = nodes_by_name.get(source)
            if source_node is None:
                continue
            if source_node.get("type") == "n8n-nodes-base.httpRequest":
                http_sources.add(source)
                continue
            pending.extend(predecessors.get(source, ()))

        descendant_nodes = _descendants_from(
            adjacency.get(node_name, ()),
            adjacency,
            stop_at=node_name,
        )
        drives_side_effect = any(
            descendant != node_name and _node_has_side_effect(nodes_by_name.get(descendant))
            for descendant in descendant_nodes
        )

        for http_name in sorted(http_sources):
            full_response, never_error, continue_output = _http_request_response_guards(
                nodes_by_name[http_name]
            )

            if not full_response:
                error = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}' via "
                    "$json.statusCode, but parameters.options.response.response.fullResponse is "
                    "false. "
                    "Enable 'Include Response Headers and Status' so downstream status checks "
                    "receive the HTTP status code."
                )
                if error not in seen:
                    seen.add(error)
                    errors.append(error)
            if not never_error:
                error = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}' via "
                    "$json.statusCode, but parameters.options.response.response.neverError is "
                    "false. Enable 'Never Error' so non-2xx HTTP responses still emit items for "
                    "the downstream condition."
                )
                if error not in seen:
                    seen.add(error)
                    errors.append(error)
            if drives_side_effect and not continue_output:
                error = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}', whose "
                    "downstream path reaches a side-effect node, but node.onError is not "
                    "'continueRegularOutput'. Enable top-level onError=continueRegularOutput so "
                    "connection/DNS/timeout failures also reach the alert-handling branch instead "
                    "of aborting the workflow."
                )
                if error not in seen:
                    seen.add(error)
                    errors.append(error)

    return errors


def _is_trigger_node(node: Mapping[str, Any], schema: dict[str, Any] | None) -> bool:
    if schema and schema.get("isTrigger"):
        return True

    node_type = str(node.get("type", "")).lower()
    if "trigger" in node_type or node_type.endswith(".webhook"):
        return True

    return bool(node.get("webhookId"))


def _validate_set_node(node: Mapping[str, Any], label: str) -> list[str]:
    if node.get("type") != "n8n-nodes-base.set":
        return []

    errors: list[str] = []
    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        return [f"Set node '{label}' parameters must be an object"]

    mode = parameters.get("mode", "manual")
    if mode == "raw":
        json_output = parameters.get("jsonOutput")
        if not json_output:
            errors.append(f"Set node '{label}' raw mode requires parameters.jsonOutput")
        return errors

    assignments_root = parameters.get("assignments")
    assignments = None
    if isinstance(assignments_root, Mapping):
        assignments = assignments_root.get("assignments")

    if not isinstance(assignments, list) or not assignments:
        errors.append(
            f"Set node '{label}' must define parameters.assignments.assignments "
            "with at least one field"
        )
        return errors

    for index, assignment in enumerate(assignments):
        item_label = f"{label} assignment {index + 1}"
        if not isinstance(assignment, Mapping):
            errors.append(f"Set node '{item_label}' must be an object")
            continue
        for field in ("id", "name", "type", "value"):
            if field not in assignment:
                errors.append(f"Set node '{item_label}' missing required field: {field}")

    return errors


def _first_non_empty_mapping_value(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _looks_like_placeholder_email(value: Any) -> bool:
    email = str(value or "").strip().lower()
    if email.startswith("=") or "{{$json." in email:
        return False
    if not email or "@" not in email:
        return True
    if email in _PLACEHOLDER_EMAILS:
        return True
    domain = email.rsplit("@", 1)[-1]
    return domain in _PLACEHOLDER_EMAIL_DOMAINS


def _validate_gmail_node(node: Mapping[str, Any], label: str) -> list[str]:
    if node.get("type") != "n8n-nodes-base.gmail":
        return []
    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        return [f"Gmail node '{label}' parameters must be an object"]
    resource = str(parameters.get("resource") or "message").lower()
    operation = str(parameters.get("operation") or "").lower()
    if resource != "message" or operation != "send":
        return []

    errors: list[str] = []
    send_to = parameters.get("sendTo")
    if not send_to:
        errors.append(f"Gmail node '{label}' send operation requires parameters.sendTo")
    elif _looks_like_placeholder_email(send_to):
        errors.append(f"Gmail node '{label}' sendTo must be a real recipient email")
    if not parameters.get("subject"):
        errors.append(f"Gmail node '{label}' send operation requires parameters.subject")
    if not parameters.get("message"):
        errors.append(f"Gmail node '{label}' send operation requires parameters.message")
    return errors


# Google Sheets row-write ops that need the v4 "columns" mapping. update /
# appendOrUpdate additionally need a matching column to locate the row. The model
# often falls back to the pre-v4 shape (dataMode/values/range), which structurally
# validates but n8n v4 ignores -> the write silently does nothing (e.g. a
# "mark as sent" step that never marks, so the workflow re-sends every run).
_GOOGLE_SHEETS_COLUMN_MAP_OPS = {"update", "appendorupdate"}
_GOOGLE_SHEETS_SUPPORTED_MAPPING_MODES = {"definebelow", "automapinputdata"}
# Row-level ops that address a specific tab; all need a v4 sheetName resourceLocator.
_GOOGLE_SHEETS_ROW_OPS = {"read", "append", "update", "appendorupdate", "clear", "remove"}
_GOOGLE_SHEETS_LEGACY_KEYS = ("dataMode", "values", "range")
_GOOGLE_SHEETS_LEGACY_DOCUMENT_KEYS = ("spreadsheetId", "sheetId")
_AMBIGUOUS_SHEET_ID_RE = re.compile(r"^\d+$")
_SPLIT_IN_BATCHES_TYPE = "n8n-nodes-base.splitInBatches"


def _has_sheet_name(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(str(value.get("value") or "").strip())
    return False


def _resource_locator_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return str(value.get("value") or "").strip()
    return ""


def _validate_google_sheets_node(node: Mapping[str, Any], label: str) -> list[str]:
    if node.get("type") != "n8n-nodes-base.googleSheets":
        return []
    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        return [f"Google Sheets node '{label}' parameters must be an object"]
    operation = str(parameters.get("operation") or "").lower()

    if operation in _GOOGLE_SHEETS_ROW_OPS:
        row_op_errors: list[str] = []
        document_id = _resource_locator_value(parameters.get("documentId"))
        if not document_id:
            legacy_sheet_id = _resource_locator_value(parameters.get("sheetId"))
            legacy_note = ""
            if legacy_sheet_id and _AMBIGUOUS_SHEET_ID_RE.fullmatch(legacy_sheet_id):
                legacy_note = (
                    " Top-level sheetId looks numeric, which is ambiguous with a tab gid; "
                    "do not use it as documentId."
                )
            row_op_errors.append(
                f"Google Sheets node '{label}' operation '{operation}' is missing "
                "parameters.documentId. n8n v4 addresses the spreadsheet via a resourceLocator: "
                'set parameters.documentId = {"__rl": true, "mode": "id", "value": '
                '"<spreadsheet id>"}.' + legacy_note
            )

        # Keep only one spreadsheet identity source of truth. If both current and
        # legacy fields are present with different values, reject rather than guess.
        if document_id:
            for legacy_key in _GOOGLE_SHEETS_LEGACY_DOCUMENT_KEYS:
                legacy_value = _resource_locator_value(parameters.get(legacy_key))
                if legacy_value and legacy_value != document_id:
                    row_op_errors.append(
                        f"Google Sheets node '{label}' mixes parameters.documentId="
                        f"'{document_id}' with conflicting legacy {legacy_key}='{legacy_value}'. "
                        "Keep only documentId with the intended spreadsheet id."
                    )

        # v4 row ops address the tab via a sheetName resourceLocator; a top-level range
        # leaves n8n unable to find the sheet ("workflow has issues, cannot execute").
        if not _has_sheet_name(parameters.get("sheetName")):
            row_op_errors.append(
                f"Google Sheets node '{label}' operation '{operation}' is missing "
                "parameters.sheetName. n8n v4 addresses the tab via a resourceLocator, not a "
                'top-level range: set parameters.sheetName = {"__rl": true, "mode": "name", '
                '"value": "<tab name>"}.'
            )
        if row_op_errors:
            return row_op_errors

    if operation not in _GOOGLE_SHEETS_COLUMN_MAP_OPS | {"append"}:
        return []

    columns = parameters.get("columns")
    if not isinstance(columns, Mapping):
        if operation == "append":
            return [
                f"Google Sheets node '{label}' operation 'append' is missing "
                "parameters.columns. Use mappingMode 'defineBelow' with a value map and "
                "schema, or 'autoMapInputData' for same-named input fields."
            ]
        # The pre-v4 shape (dataMode/values/range, no columns object at all).
        legacy = [key for key in _GOOGLE_SHEETS_LEGACY_KEYS if key in parameters]
        legacy_note = (
            f" Drop the pre-v4 keys ({', '.join(legacy)}); n8n v4 ignores them." if legacy else ""
        )
        return [
            f"Google Sheets node '{label}' operation '{operation}' is missing "
            "parameters.columns. n8n v4 finds the row by a matching column and maps the "
            'fields to write. Set parameters.columns = {"mappingMode": "defineBelow", '
            '"matchingColumns": ["<column that identifies the row, e.g. the ID column>"], '
            '"value": {"<matchColumn>": "={{ $json.<matchColumn> }}", '
            '"<column>": "<value>"}}.' + legacy_note
        ]

    mapping_mode = str(
        columns.get("mappingMode") or ("defineBelow" if operation != "append" else "")
    ).lower()
    if operation == "append":
        if mapping_mode not in _GOOGLE_SHEETS_SUPPORTED_MAPPING_MODES:
            return [
                f"Google Sheets node '{label}' operation '{operation}' has unsupported "
                f"parameters.columns.mappingMode '{columns.get('mappingMode')}'. Use "
                "'defineBelow' for explicit field mappings or 'autoMapInputData' to map "
                "same-named input fields automatically."
            ]
        if mapping_mode == "definebelow":
            value = columns.get("value")
            if not isinstance(value, Mapping) or not value:
                return [
                    f"Google Sheets node '{label}' append with mappingMode "
                    "'defineBelow' requires a non-empty parameters.columns.value map."
                ]
            schema = columns.get("schema")
            if not isinstance(schema, list) or not schema:
                return [
                    f"Google Sheets node '{label}' append with mappingMode "
                    "'defineBelow' requires a non-empty parameters.columns.schema array. "
                    "Without it n8n throws 'Could not get parameter: columns.schema'."
                ]
        return []

    matching = columns.get("matchingColumns")
    match_cols = (
        [str(item).strip() for item in matching if str(item).strip()]
        if isinstance(matching, list)
        else []
    )
    if not match_cols:
        return [
            f"Google Sheets node '{label}' operation '{operation}' needs "
            "parameters.columns.matchingColumns set to the column(s) that identify which "
            "row to update (e.g. the order id). Without it n8n cannot locate the row."
        ]

    # defineBelow reads the match value from columns.value["<matchCol>"]; auto-map
    # takes it from the input item, so only defineBelow needs it spelled out.
    if mapping_mode == "definebelow":
        value = columns.get("value")
        value_map = value if isinstance(value, Mapping) else {}
        unmatched = [col for col in match_cols if not str(value_map.get(col, "")).strip()]
        if unmatched:
            example = unmatched[0]
            return [
                f"Google Sheets node '{label}' operation '{operation}' matches on "
                f"[{', '.join(unmatched)}] but columns.value has no value to match on for "
                "them. In defineBelow mode the matching column must appear in columns.value "
                f'with the value to look up, e.g. "{example}": "={{{{ $json.{example} }}}}". '
                "Without it n8n throws \"The 'Column to Match On' parameter is required\"."
            ]
    return []


def _node_type_version_at_least(node: Mapping[str, Any], minimum: float) -> bool:
    value = node.get("typeVersion")
    return isinstance(value, int | float) and not isinstance(value, bool) and value >= minimum


def _validate_if_node(node: Mapping[str, Any], label: str) -> list[str]:
    if node.get("type") != "n8n-nodes-base.if" or not _node_type_version_at_least(node, 2):
        return []
    return _validate_conditions_node(node, label, node_kind="IF")


def _validate_filter_node(node: Mapping[str, Any], label: str) -> list[str]:
    if node.get("type") != "n8n-nodes-base.filter" or not _node_type_version_at_least(node, 2):
        return []
    return _validate_conditions_node(node, label, node_kind="Filter")


_UNARY_CONDITION_OPERATIONS = {
    "empty",
    "exists",
    "false",
    "isempty",
    "isfalse",
    "isnotempty",
    "istrue",
    "notempty",
    "notexists",
    "true",
}


def _is_missing_condition_operand(rule: Mapping[str, Any], name: str) -> bool:
    if name not in rule or rule.get(name) is None:
        return True
    value = rule.get(name)
    return isinstance(value, str) and not value.strip() and name == "leftValue"


def _validate_conditions_node(node: Mapping[str, Any], label: str, *, node_kind: str) -> list[str]:
    prefix = f"{node_kind} node '{label}'"

    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        return [f"{prefix} parameters must be an object"]

    conditions = parameters.get("conditions")
    if conditions is None:
        return [
            f"{prefix} typeVersion 2+ must put at least one rule under "
            f"parameters.conditions.conditions. A conditionless {node_kind} cannot safely "
            "filter items."
        ]

    if not isinstance(conditions, Mapping):
        return [
            f"{prefix} typeVersion 2+ requires parameters.conditions to be an object with a "
            "conditions list."
        ]

    rules = conditions.get("conditions")
    if rules is None:
        return [
            f"{prefix} typeVersion 2+ must use parameters.conditions.conditions "
            "as a non-empty list of rule objects."
        ]

    if not isinstance(rules, list):
        return [f"{prefix} typeVersion 2+ requires parameters.conditions.conditions to be a list."]
    if not rules:
        return [
            f"{prefix} typeVersion 2+ requires at least one condition rule; an empty conditions "
            "list would not safely filter items."
        ]

    errors: list[str] = []
    for index, rule in enumerate(rules, start=1):
        item_label = f"{prefix} rule {index}"
        if not isinstance(rule, Mapping):
            errors.append(f"{item_label} must be an object.")
            continue
        operator = rule.get("operator")
        if isinstance(operator, str):
            errors.append(
                f"{item_label} uses operator={operator!r}. For {node_kind} typeVersion 2+, "
                'operator must be an object like {"type": "string", "operation": "equals"}, '
                "not a string."
            )
            continue
        if operator is None:
            errors.append(
                f"{item_label} is missing operator. For {node_kind} typeVersion 2+, each rule "
                'needs an operator object like {"type": "string", "operation": "equals"}.'
            )
            continue
        if not isinstance(operator, Mapping):
            errors.append(
                f"{item_label} operator must be an object with non-empty 'type' and "
                "'operation' fields."
            )
            continue
        operator_type = str(operator.get("type") or "").strip()
        operator_name = str(operator.get("operation") or "").strip()
        if not operator_type or not operator_name:
            errors.append(
                f"{item_label} operator must include non-empty 'type' and 'operation' values, "
                'for example {"type": "string", "operation": "equals"}.'
            )
            continue
        if _is_missing_condition_operand(rule, "leftValue"):
            errors.append(f"{item_label} must include a non-empty leftValue expression or literal.")
        if (
            operator_name.lower() not in _UNARY_CONDITION_OPERATIONS
            and _is_missing_condition_operand(rule, "rightValue")
        ):
            errors.append(
                f"{item_label} operation={operator_name!r} requires rightValue. "
                "Only unary operations such as isEmpty/isNotEmpty may omit it."
            )
    return errors


_CODE_LANGUAGES = {"javaScript", "python", "pythonNative"}


def _validate_code_node(node: Mapping[str, Any], label: str) -> list[str]:
    if node.get("type") != "n8n-nodes-base.code" or not _node_type_version_at_least(node, 2):
        return []

    parameters = node.get("parameters")
    if not isinstance(parameters, Mapping):
        return [f"Code node '{label}' parameters must be an object"]

    errors: list[str] = []
    raw_language = parameters.get("language")
    language = str(raw_language).strip() if isinstance(raw_language, str) else ""

    if raw_language is not None:
        if not language:
            errors.append(
                f"Code node '{label}' language must be one of "
                "'javaScript', 'python', or 'pythonNative' when provided."
            )
        elif language not in _CODE_LANGUAGES:
            errors.append(
                f"Code node '{label}' language={language!r} is invalid. Use the exact n8n "
                "value 'javaScript' for JavaScript, or 'python' / 'pythonNative' for Python."
            )

    uses_javascript = raw_language is None or language == "javaScript"
    js_code = parameters.get("jsCode")
    if uses_javascript and (not isinstance(js_code, str) or not js_code.strip()):
        errors.append(
            f"Code node '{label}' must provide non-empty parameters.jsCode when language is "
            "'javaScript' (or omitted, because n8n defaults to JavaScript)."
        )

    return errors


def _normalize_gmail_node(data: dict[str, Any]) -> None:
    if data.get("type") != "n8n-nodes-base.gmail":
        return
    parameters = data.get("parameters")
    if not isinstance(parameters, dict):
        return
    resource = str(parameters.get("resource") or "message").lower()
    operation = str(parameters.get("operation") or "").lower()
    if resource == "message" and operation == "create":
        parameters["operation"] = "send"
        operation = "send"
    if resource != "message" or operation != "send":
        return

    additional_fields = parameters.get("additionalFields")
    if not isinstance(additional_fields, Mapping):
        additional_fields = {}

    send_to = _first_non_empty_mapping_value(
        parameters,
        ("sendTo", "toEmail", "to", "recipient", "recipientEmail"),
    ) or _first_non_empty_mapping_value(
        additional_fields,
        ("sendTo", "toEmail", "to", "recipient", "recipientEmail"),
    )
    subject = _first_non_empty_mapping_value(
        parameters, ("subject",)
    ) or _first_non_empty_mapping_value(additional_fields, ("subject",))
    message = _first_non_empty_mapping_value(
        parameters,
        ("message", "body", "bodyContent", "bodyText", "content"),
    ) or _first_non_empty_mapping_value(
        additional_fields,
        ("message", "body", "bodyContent", "bodyText", "content"),
    )

    if send_to:
        parameters["sendTo"] = send_to
    if subject:
        parameters["subject"] = subject
    if message:
        parameters["message"] = message
    if "emailType" not in parameters:
        body_type = str(
            parameters.get("bodyContentType") or additional_fields.get("bodyContentType") or ""
        ).lower()
        parameters["emailType"] = "html" if "html" in body_type else "text"

    for alias in (
        "toEmail",
        "to",
        "recipient",
        "recipientEmail",
        "body",
        "bodyContent",
        "bodyText",
        "content",
        "bodyContentType",
    ):
        parameters.pop(alias, None)
    parameters.pop("additionalFields", None)


_LANGCHAIN_CHAT_PREFIX = "@n8n/n8n-nodes-langchain.lmChat"


def _normalize_chat_model_node(data: dict[str, Any]) -> None:
    """Wrap a langchain chat model's ``model`` string as a resourceLocator.

    n8n's lmChat* nodes expose ``model`` as a resourceLocator object; a plain
    string makes n8n raise "Could not get parameter" at run time. The graph
    compiler built this shape; on the compact JSON surface the model writes a
    bare string, so normalize it here.
    """

    if not str(data.get("type") or "").startswith(_LANGCHAIN_CHAT_PREFIX):
        return
    parameters = data.get("parameters")
    if not isinstance(parameters, dict):
        return
    model = parameters.get("model")
    if isinstance(model, str) and model.strip():
        parameters["model"] = {"__rl": True, "mode": "list", "value": model.strip()}


def _normalize_google_sheets_node(data: dict[str, Any]) -> None:
    if data.get("type") != "n8n-nodes-base.googleSheets":
        return
    parameters = data.get("parameters")
    if not isinstance(parameters, dict):
        return
    resource = str(parameters.get("resource") or "").lower()
    operation = str(parameters.get("operation") or "").lower()
    if resource == "spreadsheet" and operation == "append":
        parameters["resource"] = "sheet"


def _integer_in_range(value: Any, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _validate_schedule_trigger_node(node: Mapping[str, Any], label: str) -> list[str]:
    """Validate the Schedule Trigger shape before n8n activation.

    n8n accepts workflow PUTs containing malformed schedule rules and only
    reports ``Invalid interval`` during activation. Catching the exact rule
    here sends the model through ModelRetry before any external mutation.
    """

    if node.get("type") != "n8n-nodes-base.scheduleTrigger":
        return []

    errors: list[str] = []
    parameters = node.get("parameters")
    rule = parameters.get("rule") if isinstance(parameters, Mapping) else None
    intervals = rule.get("interval") if isinstance(rule, Mapping) else None
    if not isinstance(intervals, list) or not intervals:
        return [
            f"Schedule Trigger node '{label}' must define "
            "parameters.rule.interval with at least one trigger rule"
        ]

    allowed_fields = {"seconds", "minutes", "hours", "days", "weeks", "months", "cronExpression"}
    interval_ranges: dict[str, tuple[str, int, int | None]] = {
        "seconds": ("secondsInterval", 1, 59),
        "minutes": ("minutesInterval", 1, 59),
        "hours": ("hoursInterval", 1, 23),
        "days": ("daysInterval", 1, 31),
        # n8n's schema sets no upper bound for week/month intervals.
        "weeks": ("weeksInterval", 1, None),
        "months": ("monthsInterval", 1, None),
    }

    for index, interval in enumerate(intervals, start=1):
        item_label = f"{label} rule {index}"
        if not isinstance(interval, Mapping):
            errors.append(f"Schedule Trigger '{item_label}' must be an object")
            continue

        field = interval.get("field")
        if field not in allowed_fields:
            errors.append(
                f"Schedule Trigger '{item_label}' field must be one of "
                "seconds, minutes, hours, days, weeks, months, cronExpression; "
                f"got {field!r}"
            )
            continue

        if field == "cronExpression":
            expression = interval.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                errors.append(
                    f"Schedule Trigger '{item_label}' cronExpression requires "
                    "a non-empty expression"
                )
            else:
                cron_fields = expression.split()
                valid_tokens = all(
                    re.fullmatch(r"[A-Za-z0-9*/?,#LW-]+", token) for token in cron_fields
                )
                if len(cron_fields) != 6 or not valid_tokens:
                    errors.append(
                        f"Schedule Trigger '{item_label}' cronExpression must contain "
                        "six valid cron fields (second minute hour day month weekday)"
                    )
            continue

        interval_name, minimum, maximum = interval_ranges[str(field)]
        interval_value = interval.get(interval_name, 1)
        interval_is_valid = (
            isinstance(interval_value, int)
            and not isinstance(interval_value, bool)
            and interval_value >= minimum
            and (maximum is None or interval_value <= maximum)
        )
        if not interval_is_valid:
            range_text = f"from {minimum} to {maximum}" if maximum is not None else f">= {minimum}"
            errors.append(
                f"Schedule Trigger '{item_label}' {interval_name} must be an integer {range_text}"
            )

        if field in {"days", "weeks", "months"}:
            hour = interval.get("triggerAtHour", 0)
            if not _integer_in_range(hour, 0, 23):
                errors.append(
                    f"Schedule Trigger '{item_label}' triggerAtHour must be an integer from 0 to 23"
                )
        if field in {"hours", "days", "weeks", "months"}:
            minute = interval.get("triggerAtMinute", 0)
            if not _integer_in_range(minute, 0, 59):
                errors.append(
                    f"Schedule Trigger '{item_label}' triggerAtMinute must be an integer "
                    "from 0 to 59"
                )
        if field == "weeks":
            weekdays = interval.get("triggerAtDay", [0])
            if (
                not isinstance(weekdays, list)
                or not weekdays
                or any(not _integer_in_range(day, 0, 6) for day in weekdays)
            ):
                errors.append(
                    f"Schedule Trigger '{item_label}' triggerAtDay must contain weekday "
                    "integers from 0 to 6"
                )
        if field == "months":
            day_of_month = interval.get("triggerAtDayOfMonth", 1)
            if not _integer_in_range(day_of_month, 1, 31):
                errors.append(
                    f"Schedule Trigger '{item_label}' triggerAtDayOfMonth must be an integer "
                    "from 1 to 31"
                )

    return errors


def validate_workflow_payload(
    nodes: Sequence[WorkflowNode | Mapping[str, Any]],
    connections: Mapping[str, Any] | None,
    node_registry: NodeRegistry = default_registry,
) -> list[str]:
    """Return workflow validation errors. Empty list means the payload is usable."""

    errors: list[str] = []
    raw_nodes = [_as_node_dict(node) for node in nodes]

    if not raw_nodes:
        return ["nodes array is empty; every workflow needs at least one trigger node"]

    seen_ids: set[str] = set()
    node_names: set[str] = set()
    node_type_by_name: dict[str, str] = {}
    has_trigger = False

    for index, node in enumerate(raw_nodes):
        label = str(node.get("name") or index)
        for field in ("id", "name", "type", "typeVersion", "position", "parameters"):
            if field not in node:
                errors.append(f"Node '{label}' missing required field: {field}")

        node_id = node.get("id")
        if node_id:
            if node_id in seen_ids:
                errors.append(f"Duplicate node id: '{node_id}'")
            seen_ids.add(str(node_id))

        node_name = node.get("name")
        if node_name:
            node_names.add(str(node_name))

        node_type = str(node.get("type") or "")
        if node_name and node_type:
            node_type_by_name[str(node_name)] = node_type
        schema = node_registry.get_node_schema(node_type) if node_type else None

        if node_type:
            if schema:
                expected_type = schema.get("type")
                if expected_type and node_type != expected_type:
                    errors.append(
                        f"Node '{label}' type must use exact n8n type "
                        f"'{expected_type}', not '{node_type}'"
                    )
            elif not _has_n8n_type_prefix(node_type):
                errors.append(
                    f"Node '{label}' has suspicious type '{node_type}'; use search_n8n_nodes first"
                )

        type_version = node.get("typeVersion")
        if type_version is not None and (
            not isinstance(type_version, int | float) or isinstance(type_version, bool)
        ):
            errors.append(f"Node '{label}' typeVersion must be a number")
        elif schema and type_version != schema.get("typeVersion"):
            errors.append(
                f"Node '{label}' typeVersion must be "
                f"{schema.get('typeVersion')} for {schema.get('type')}"
            )

        position = node.get("position")
        if position is not None and (
            not isinstance(position, list)
            or len(position) != 2
            or not all(
                isinstance(item, int | float) and not isinstance(item, bool) for item in position
            )
        ):
            errors.append(f"Node '{label}' position must be [x, y]")

        parameters = node.get("parameters")
        if parameters is not None and not isinstance(parameters, dict):
            errors.append(f"Node '{label}' parameters must be an object")

        errors.extend(_validate_set_node(node, label))
        errors.extend(_validate_if_node(node, label))
        errors.extend(_validate_filter_node(node, label))
        errors.extend(_validate_code_node(node, label))
        errors.extend(_validate_schedule_trigger_node(node, label))
        errors.extend(_validate_gmail_node(node, label))
        errors.extend(_validate_google_sheets_node(node, label))
        errors.extend(_validate_input_expressions(node, label))

        if _is_trigger_node(node, schema):
            has_trigger = True

    if not has_trigger:
        errors.append("No trigger node found; workflow needs a trigger node")

    if connections is not None and not isinstance(connections, Mapping):
        errors.append("connections must be an object")
    elif connections:
        for source_name, value in connections.items():
            if str(source_name) not in node_names:
                errors.append(f"connections references unknown source node '{source_name}'")
            for target in _iter_connection_targets(value):
                target_name = target.get("node")
                if target_name and str(target_name) not in node_names:
                    errors.append(f"connections references unknown target node '{target_name}'")

        errors.extend(_langchain_subnode_wiring_errors(connections, node_type_by_name))
        errors.extend(_validate_split_in_batches_connections(raw_nodes, connections))
        errors.extend(_validate_http_status_condition_flow(raw_nodes, connections))

    return errors


def _langchain_subnode_wiring_errors(
    connections: Mapping[str, Any],
    node_type_by_name: Mapping[str, str],
) -> list[str]:
    """Flag langchain AI sub-nodes wired into the main flow.

    Chat models, memory, tools and parsers have no main I/O; a main connection
    in or out of them yields empty downstream data (the empty-email bug). They
    must attach to an AI Agent / chain via an ai_* port instead.
    """

    subnode_names = {
        name for name, node_type in node_type_by_name.items() if _is_langchain_ai_subnode(node_type)
    }
    if not subnode_names:
        return []

    flagged: set[str] = set()
    for source_name, value in connections.items():
        if not isinstance(value, Mapping):
            continue
        main_groups = value.get("main")
        if not main_groups:
            continue
        if str(source_name) in subnode_names:
            flagged.add(str(source_name))
        for target in _iter_connection_targets({"main": main_groups}):
            target_name = target.get("node")
            if target_name and str(target_name) in subnode_names:
                flagged.add(str(target_name))

    return [
        f"Node '{name}' is an AI sub-node (chat model / memory / tool) with no main input or "
        "output; attach it to an AI Agent via an ai_languageModel (or ai_tool / ai_memory) "
        "connection instead of wiring it into the main flow."
        for name in sorted(flagged)
    ]


def normalize_workflow_nodes(
    nodes: Sequence[WorkflowNode | Mapping[str, Any]],
    node_registry: NodeRegistry = default_registry,
) -> list[WorkflowNode]:
    """Canonicalize node type and typeVersion when registry can resolve the node."""

    normalized: list[WorkflowNode] = []
    for node in nodes:
        data = _as_node_dict(node)
        node_type = str(data.get("type") or "")
        schema = node_registry.get_node_schema(node_type) if node_type else None
        if schema:
            data["type"] = schema.get("type", data.get("type"))
            data["typeVersion"] = schema.get("typeVersion", data.get("typeVersion"))
        _normalize_gmail_node(data)
        _normalize_google_sheets_node(data)
        _normalize_chat_model_node(data)
        if data.get("type") == "n8n-nodes-base.webhook" and not data.get("webhookId"):
            data["webhookId"] = str(uuid4())
        normalized.append(WorkflowNode.model_validate(data))
    return normalized


def normalize_workflow_connections(
    connections: Mapping[str, Any],
    nodes: Sequence[WorkflowNode | Mapping[str, Any]],
) -> dict[str, Any]:
    """Convert connection source/target aliases to n8n-required node names."""

    references = _node_reference_map(nodes)
    return {
        _resolve_node_reference(source_name, references): _normalize_connection_shape(
            _normalize_connection_value(
                value,
                references,
            )
        )
        for source_name, value in connections.items()
    }
