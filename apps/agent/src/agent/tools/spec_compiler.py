"""WorkflowSpec compiler for deterministic n8n workflow generation."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic_ai import ModelRetry

from src import n8n_client, store
from src.agent.schemas import (
    AgentDeps,
    WorkflowInputField,
    WorkflowNode,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
    WorkflowSpec,
    dump_workflow_nodes,
)
from src.agent.tools.common import _missing_credentials_instruction, _safe_error
from src.agent.tools.constants import _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.readiness import analyze_workflow_readiness_payload
from src.agent.tools.runtime_inputs import (
    _infer_runtime_input_schema,
    _input_schema_payload,
    _normalized_input_schema,
    _runtime_expression,
)
from src.agent.tools.validation import _validated_runtime_workflow
from src.registry import registry

_GMAIL_NODE_TYPE = "n8n-nodes-base.gmail"
_GOOGLE_SHEETS_NODE_TYPE = "n8n-nodes-base.googleSheets"
_FILTER_NODE_TYPE = "n8n-nodes-base.filter"
_SCHEDULE_TRIGGER_TYPE = "n8n-nodes-base.scheduleTrigger"


class WorkflowSpecCompileError(ValueError):
    """Raised when WorkflowSpec cannot be compiled without guessing."""


@dataclass
class CompiledWorkflowSpec:
    nodes: list[WorkflowNode]
    connections: dict[str, Any]
    input_schema: list[WorkflowInputField]


def _schema_type_version(node_type: str) -> int | float:
    schema = registry.get_node_schema(node_type)
    if not isinstance(schema, dict):
        raise WorkflowSpecCompileError(
            f"WorkflowSpec compiler needs registry schema for {node_type}."
        )
    type_version = schema.get("typeVersion")
    if not isinstance(type_version, int | float) or isinstance(type_version, bool):
        raise WorkflowSpecCompileError(
            f"WorkflowSpec compiler needs numeric typeVersion for {node_type}."
        )
    return type_version


def _webhook_path(name: str) -> str:
    safe_name = "".join(char if char.isalnum() else "-" for char in name.lower())
    safe_name = "-".join(part for part in safe_name.split("-") if part)
    return f"conduut-spec-{safe_name or 'workflow'}-{uuid4().hex[:8]}"


def _input_value(inputs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = inputs.get(key)
        if value not in (None, ""):
            return value
    return None


def _required_string(inputs: dict[str, Any], *keys: str) -> str:
    value = _input_value(inputs, *keys)
    if value is None:
        raise WorkflowSpecCompileError(f"Missing required input: {keys[0]}")
    return str(value).strip()


def _sheet_locator(value: str, *, mode: str) -> dict[str, Any]:
    return {"__rl": True, "mode": mode, "value": value}


def _json_field_expression(field_name: str) -> str:
    escaped = field_name.replace("\\", "\\\\").replace('"', '\\"')
    return '={{$json["' + escaped + '"]}}'


def _email_value_expression(inputs: dict[str, Any], value_key: str, field_key: str) -> str:
    field = _input_value(inputs, field_key)
    if field is not None:
        return _json_field_expression(str(field))
    value = _input_value(inputs, value_key)
    if value is None:
        raise WorkflowSpecCompileError(f"Missing required input: {value_key}")
    text = str(value)
    if text.startswith("="):
        return text
    if "{{" in text:
        return f"={text}"
    return text


def _filter_operation(raw_operator: Any, value: Any) -> tuple[str, str]:
    operator = str(raw_operator or "").strip().lower()
    mapping = {
        ">": ("number", "gt"),
        "gt": ("number", "gt"),
        "greater_than": ("number", "gt"),
        ">=": ("number", "gte"),
        "gte": ("number", "gte"),
        "greater_than_or_equal": ("number", "gte"),
        "<": ("number", "lt"),
        "lt": ("number", "lt"),
        "less_than": ("number", "lt"),
        "<=": ("number", "lte"),
        "lte": ("number", "lte"),
        "less_than_or_equal": ("number", "lte"),
        "=": ("string", "equals"),
        "==": ("string", "equals"),
        "equals": ("string", "equals"),
        "not_equals": ("string", "notEquals"),
        "!=": ("string", "notEquals"),
        "contains": ("string", "contains"),
        "not_contains": ("string", "notContains"),
    }
    if operator not in mapping:
        raise WorkflowSpecCompileError(f"Unsupported filter operator: {raw_operator}")
    value_type, operation = mapping[operator]
    if isinstance(value, int | float) and not isinstance(value, bool):
        value_type = "number"
    return value_type, operation


def _parse_daily_time(value: str | None) -> tuple[int, int]:
    if not value:
        return 9, 0
    parts = value.strip().split(":", 1)
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except ValueError as exc:
        raise WorkflowSpecCompileError("Schedule time must be HH:MM.") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise WorkflowSpecCompileError("Schedule time must be between 00:00 and 23:59.")
    return hour, minute


def _compile_trigger(name: str, spec: WorkflowSpec) -> WorkflowNode:
    if spec.trigger.kind == "on_demand":
        return WorkflowNode(
            id="trigger",
            name="Webhook",
            type=_WEBHOOK_TRIGGER_TYPE,
            typeVersion=_schema_type_version(_WEBHOOK_TRIGGER_TYPE),
            position=[250, 300],
            parameters={
                "httpMethod": "POST",
                "path": _webhook_path(name),
                "responseMode": "lastNode",
                "options": {},
            },
            webhookId=str(uuid4()),
        )
    if spec.trigger.kind == "schedule":
        if spec.trigger.frequency != "daily":
            raise WorkflowSpecCompileError("WorkflowSpec V2 only supports daily schedules.")
        hour, minute = _parse_daily_time(spec.trigger.time)
        return WorkflowNode(
            id="trigger",
            name="Schedule",
            type=_SCHEDULE_TRIGGER_TYPE,
            typeVersion=_schema_type_version(_SCHEDULE_TRIGGER_TYPE),
            position=[250, 300],
            parameters={
                "rule": {
                    "interval": [
                        {
                            "field": "days",
                            "daysInterval": 1,
                            "triggerAtHour": hour,
                            "triggerAtMinute": minute,
                        }
                    ]
                }
            },
        )
    raise WorkflowSpecCompileError(f"Unsupported trigger kind: {spec.trigger.kind}")


def _compile_gmail_on_demand(
    name: str,
    spec: WorkflowSpec,
    input_schema: list[WorkflowInputField] | None,
) -> CompiledWorkflowSpec:
    trigger = _compile_trigger(name, spec)
    if trigger.type != _WEBHOOK_TRIGGER_TYPE:
        raise WorkflowSpecCompileError("Single-step Gmail WorkflowSpec requires on_demand trigger.")
    step = spec.steps[0]
    nodes = [
        trigger,
        WorkflowNode(
            id=step.id or "send_email",
            name="Gmail",
            type=_GMAIL_NODE_TYPE,
            typeVersion=_schema_type_version(_GMAIL_NODE_TYPE),
            position=[500, 300],
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": _runtime_expression("to", from_webhook_body=True),
                "subject": _runtime_expression("subject", from_webhook_body=True),
                "message": _runtime_expression("message", from_webhook_body=True),
                "emailType": "text",
            },
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}}
    node_dicts = dump_workflow_nodes(nodes)
    runtime_schema = _normalized_input_schema(input_schema) or _infer_runtime_input_schema(
        node_dicts
    )
    return CompiledWorkflowSpec(nodes=nodes, connections=connections, input_schema=runtime_schema)


def _compile_sheet_filter_gmail(name: str, spec: WorkflowSpec) -> CompiledWorkflowSpec:
    read_step, filter_step, email_step = spec.steps
    if read_step.capability != "read_sheet_rows" or read_step.service != "google_sheets":
        raise WorkflowSpecCompileError("First step must be read_sheet_rows/google_sheets.")
    if filter_step.capability != "filter_items":
        raise WorkflowSpecCompileError("Second step must be filter_items.")
    if email_step.capability != "send_email" or email_step.service != "gmail":
        raise WorkflowSpecCompileError("Third step must be send_email/gmail.")

    document_id = _required_string(read_step.inputs, "document_id", "spreadsheet_id")
    sheet_value = _required_string(read_step.inputs, "sheet_name", "sheet_id", "sheet")
    sheet_mode = "id" if _input_value(read_step.inputs, "sheet_id") is not None else "name"

    filter_field = _required_string(filter_step.inputs, "field", "column")
    filter_value = _input_value(filter_step.inputs, "value")
    if filter_value is None:
        raise WorkflowSpecCompileError("Missing required input: value")
    operator_type, operation = _filter_operation(filter_step.inputs.get("operator"), filter_value)

    email_inputs = email_step.inputs
    send_to = _email_value_expression(email_inputs, "to", "to_field")
    subject = _email_value_expression(email_inputs, "subject", "subject_field")
    message = _email_value_expression(email_inputs, "message", "message_field")

    trigger = _compile_trigger(name, spec)
    trigger_target = "Google Sheets"
    trigger_source = trigger.name

    nodes = [
        trigger,
        WorkflowNode(
            id=read_step.id or "read_sheet_rows",
            name="Google Sheets",
            type=_GOOGLE_SHEETS_NODE_TYPE,
            typeVersion=_schema_type_version(_GOOGLE_SHEETS_NODE_TYPE),
            position=[500, 300],
            parameters={
                "authentication": "oAuth2",
                "resource": "sheet",
                "operation": "read",
                "documentId": _sheet_locator(document_id, mode="id"),
                "sheetName": _sheet_locator(sheet_value, mode=sheet_mode),
                "options": {},
            },
        ),
        WorkflowNode(
            id=filter_step.id or "filter_items",
            name="Filter",
            type=_FILTER_NODE_TYPE,
            typeVersion=_schema_type_version(_FILTER_NODE_TYPE),
            position=[750, 300],
            parameters={
                "options": {},
                "conditions": {
                    "options": {
                        "version": 2,
                        "leftValue": "",
                        "caseSensitive": True,
                        "typeValidation": "strict",
                    },
                    "combinator": "and",
                    "conditions": [
                        {
                            "id": "filter-condition",
                            "operator": {
                                "type": operator_type,
                                "operation": operation,
                            },
                            "leftValue": _json_field_expression(filter_field),
                            "rightValue": filter_value,
                        }
                    ],
                },
            },
        ),
        WorkflowNode(
            id=email_step.id or "send_email",
            name="Gmail",
            type=_GMAIL_NODE_TYPE,
            typeVersion=_schema_type_version(_GMAIL_NODE_TYPE),
            position=[1000, 300],
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": send_to,
                "subject": subject,
                "message": message,
                "emailType": "text",
            },
        ),
    ]
    connections = {
        trigger_source: {"main": [[{"node": trigger_target, "type": "main", "index": 0}]]},
        "Google Sheets": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
        "Filter": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
    }
    return CompiledWorkflowSpec(nodes=nodes, connections=connections, input_schema=[])


def compile_workflow_spec(
    name: str,
    spec: WorkflowSpec,
    input_schema: list[WorkflowInputField] | None = None,
) -> CompiledWorkflowSpec:
    """Compile supported WorkflowSpec shapes into validated n8n workflow pieces."""

    if len(spec.steps) == 1:
        step = spec.steps[0]
        if step.capability == "send_email" and step.service == "gmail":
            return _compile_gmail_on_demand(name, spec, input_schema)
    if len(spec.steps) == 3:
        return _compile_sheet_filter_gmail(name, spec)
    raise WorkflowSpecCompileError(
        "WorkflowSpec supports Gmail send or Google Sheets -> Filter -> Gmail workflows."
    )


async def create_workflow_from_spec_payload(
    deps: AgentDeps,
    name: str,
    spec: WorkflowSpec,
    input_schema: list[WorkflowInputField] | None = None,
) -> dict[str, Any]:
    """Compile WorkflowSpec and create the resulting n8n workflow."""

    try:
        compiled = compile_workflow_spec(name, spec, input_schema)
        validated_nodes, validated_connections, runtime_schema = _validated_runtime_workflow(
            compiled.nodes,
            compiled.connections,
            compiled.input_schema,
        )
    except (WorkflowSpecCompileError, ModelRetry) as exc:
        return {
            "error": str(exc),
            "fallback": (
                "Use create_workflow only if the requested workflow is outside the "
                "supported WorkflowSpec compiler."
            ),
        }

    node_dicts = dump_workflow_nodes(validated_nodes)
    try:
        workflow = await n8n_client.create_workflow(
            name=name,
            nodes=node_dicts,
            connections=validated_connections,
        )
    except Exception as exc:
        return {"error": _safe_error(exc)}

    await store.save_workflow_metadata(
        deps.user_id,
        workflow.id,
        input_schema=_input_schema_payload(runtime_schema),
    )

    await deps.emit_attachment(
        WorkflowPreviewAttachment(
            data=WorkflowPreviewData(
                id=workflow.id,
                name=workflow.name,
                nodeCount=len(node_dicts),
                status="active" if workflow.active else "inactive",
            )
        )
    )
    full_workflow = await n8n_client.get_workflow(workflow.id)
    readiness = await analyze_workflow_readiness_payload(
        full_workflow,
        user_id=deps.user_id,
    )
    for attachment in readiness["missing_credentials"]:
        await deps.emit_attachment(attachment)

    missing_count = len(readiness["missing_credentials"])
    if missing_count:
        deps.awaiting_user_input = True
        return {
            "id": workflow.id,
            "name": workflow.name,
            "active": workflow.active,
            "ready": False,
            "missing_credentials": missing_count,
            "instruction": _missing_credentials_instruction(),
        }
    return {"id": workflow.id, "name": workflow.name, "active": workflow.active}
