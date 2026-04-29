"""Workflow validation helpers used before writing to n8n."""

from collections.abc import Mapping, Sequence
from typing import Any

from n8n_registry import NodeRegistry

from src.agent.schemas import WorkflowNode
from src.registry import registry as default_registry

_N8N_TYPE_PREFIXES = ("n8n-nodes-base.", "@n8n/", "n8n-nodes-")


def _as_node_dict(node: WorkflowNode | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(node, WorkflowNode):
        return node.model_dump(exclude_none=True)
    return dict(node)


def _has_n8n_type_prefix(node_type: str) -> bool:
    return node_type.startswith(_N8N_TYPE_PREFIXES)


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


def _iter_connection_targets(value: Any):
    if isinstance(value, Mapping):
        if "node" in value:
            yield value
        for nested in value.values():
            yield from _iter_connection_targets(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_connection_targets(nested)


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

    return errors


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
        normalized.append(WorkflowNode.model_validate(data))
    return normalized


def normalize_workflow_connections(
    connections: Mapping[str, Any],
    nodes: Sequence[WorkflowNode | Mapping[str, Any]],
) -> dict[str, Any]:
    """Convert connection source/target aliases to n8n-required node names."""

    references = _node_reference_map(nodes)
    return {
        _resolve_node_reference(source_name, references): _normalize_connection_value(
            value,
            references,
        )
        for source_name, value in connections.items()
    }
