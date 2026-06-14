"""Workflow validation helpers used before writing to n8n."""

import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from n8n_registry import NodeRegistry

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
                "<field>, or build the workflow with create_workflow_from_graph using "
                "{ref: 'input.<field>'}."
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


def _ensure_connection_target(value: Any) -> Any:
    if not isinstance(value, Mapping) or "node" not in value:
        return value
    target = dict(value)
    target.setdefault("type", "main")
    target.setdefault("index", 0)
    return target


def _normalize_output_connection_groups(value: Any) -> Any:
    if isinstance(value, Mapping) and "node" in value:
        return [[_ensure_connection_target(value)]]

    if not isinstance(value, list):
        return value

    if all(isinstance(item, Mapping) and "node" in item for item in value):
        return [[_ensure_connection_target(item) for item in value]]

    groups: list[Any] = []
    for group in value:
        if isinstance(group, Mapping) and "node" in group:
            groups.append([_ensure_connection_target(group)])
        elif isinstance(group, list):
            groups.append([_ensure_connection_target(item) for item in group])
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
            output_type: _normalize_output_connection_groups(output_groups)
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
        parameters["emailType"] = "text" if "text" in body_type else "text"

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
        errors.extend(_validate_gmail_node(node, label))
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
