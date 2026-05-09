"""Runtime input schema helpers for reusable workflows."""

from typing import Any

from src import store
from src.agent.schemas import WorkflowInputField

_RUNTIME_INPUT_TYPE_VALUES = {"string", "email", "textarea"}
_GMAIL_RUNTIME_INPUT_FIELDS = [
    WorkflowInputField(
        name="to",
        label="Recipient email",
        type="email",
        required=True,
        placeholder="name@example.com",
    ),
    WorkflowInputField(
        name="subject",
        label="Subject",
        type="string",
        required=True,
        placeholder="Email subject",
    ),
    WorkflowInputField(
        name="message",
        label="Message",
        type="textarea",
        required=True,
        placeholder="Email body",
    ),
]


def _runtime_expression(field_name: str, *, from_webhook_body: bool = False) -> str:
    path = f"body.{field_name}" if from_webhook_body else field_name
    return "={{$json." + path + "}}"


def _is_gmail_send_node(node: dict[str, Any]) -> bool:
    if node.get("type") != "n8n-nodes-base.gmail":
        return False
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        return False
    resource = str(parameters.get("resource") or "message").lower()
    operation = str(parameters.get("operation") or "send").lower()
    return resource == "message" and operation in {"create", "send"}


def _field_by_name(fields: list[WorkflowInputField]) -> dict[str, WorkflowInputField]:
    return {field.name: field for field in fields}


def _normalized_input_schema(
    input_schema: list[WorkflowInputField | dict[str, Any]] | None,
) -> list[WorkflowInputField]:
    fields: list[WorkflowInputField] = []
    seen: set[str] = set()
    for raw in input_schema or []:
        try:
            field = (
                raw
                if isinstance(raw, WorkflowInputField)
                else WorkflowInputField.model_validate(raw)
            )
        except Exception:
            continue
        name = field.name.strip()
        if not name or name in seen:
            continue
        field_type = field.type if field.type in _RUNTIME_INPUT_TYPE_VALUES else "string"
        fields.append(
            WorkflowInputField(
                name=name,
                label=field.label.strip() or name.replace("_", " ").title(),
                type=field_type,
                required=field.required,
                placeholder=field.placeholder,
            )
        )
        seen.add(name)
    return fields


def _infer_runtime_input_schema(nodes: list[dict[str, Any]]) -> list[WorkflowInputField]:
    if any(_is_gmail_send_node(node) for node in nodes):
        return list(_GMAIL_RUNTIME_INPUT_FIELDS)
    return []


def _input_schema_payload(fields: list[WorkflowInputField]) -> list[dict[str, Any]]:
    return [field.model_dump(exclude_none=True) for field in fields]


def _workflow_input_schema_from_metadata(
    metadata: store.WorkflowMetadata | None,
) -> list[WorkflowInputField]:
    if not metadata:
        return []
    return _normalized_input_schema(metadata.input_schema)


def _apply_runtime_inputs_to_nodes(
    nodes: list[dict[str, Any]],
    input_schema: list[WorkflowInputField],
) -> None:
    fields = _field_by_name(input_schema)
    if not {"to", "subject", "message"}.issubset(fields):
        return

    from_webhook_body = any(node.get("type") == "n8n-nodes-base.webhook" for node in nodes)

    for node in nodes:
        if not _is_gmail_send_node(node):
            continue
        parameters = node.setdefault("parameters", {})
        parameters["resource"] = "message"
        parameters["operation"] = "send"
        parameters["sendTo"] = _runtime_expression("to", from_webhook_body=from_webhook_body)
        parameters["subject"] = _runtime_expression(
            "subject",
            from_webhook_body=from_webhook_body,
        )
        parameters["message"] = _runtime_expression(
            "message",
            from_webhook_body=from_webhook_body,
        )
        parameters["emailType"] = "text"


def _validated_workflow_input(
    input_schema: list[WorkflowInputField],
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    raw = payload if isinstance(payload, dict) else {}
    validated: dict[str, Any] = {}
    missing: list[str] = []

    for field in input_schema:
        value = raw.get(field.name)
        if isinstance(value, str):
            value = value.strip()
        if field.required and value in (None, ""):
            missing.append(field.name)
            continue
        if value not in (None, ""):
            validated[field.name] = value

    for key, value in raw.items():
        if key not in validated and key not in {field.name for field in input_schema}:
            validated[str(key)] = value

    return validated, missing
