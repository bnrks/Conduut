"""WorkflowSpec compiler for deterministic n8n workflow generation."""

# todo: bu dosya çok büyük refactor edilecek.
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic_ai import ModelRetry

from src import n8n_client, store
from src.agent.schemas import (
    AgentDeps,
    WorkflowActionSpec,
    WorkflowInputField,
    WorkflowNode,
    WorkflowPlan,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
    WorkflowSpec,
    WorkflowTriggerSpec,
    dump_workflow_nodes,
)
from src.agent.tools.common import _missing_credentials_instruction, _safe_error
from src.agent.tools.constants import _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.readiness import analyze_workflow_readiness_payload
from src.agent.tools.runtime_inputs import (
    _GMAIL_RUNTIME_INPUT_FIELDS,
    _input_schema_payload,
    _normalized_input_schema,
    _runtime_expression,
)
from src.agent.tools.validation import _validated_runtime_workflow, _validated_workflow
from src.platforms.actions import PlatformActionError, provision_spreadsheet_for_workflow
from src.registry import registry

_GMAIL_NODE_TYPE = "n8n-nodes-base.gmail"
_GOOGLE_SHEETS_NODE_TYPE = "n8n-nodes-base.googleSheets"
_FILTER_NODE_TYPE = "n8n-nodes-base.filter"
_SET_NODE_TYPE = "n8n-nodes-base.set"
_SCHEDULE_TRIGGER_TYPE = "n8n-nodes-base.scheduleTrigger"


class WorkflowSpecCompileError(ValueError):
    """Raised when WorkflowSpec cannot be compiled without guessing."""


class WorkflowPlanCompileError(WorkflowSpecCompileError):
    """Raised when WorkflowPlan cannot be compiled without guessing."""


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


def _json_path_segment(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'["{escaped}"]'


def _json_path_expression(node_name: str, path: list[str]) -> str:
    safe_node = node_name.replace("\\", "\\\\").replace("'", "\\'")
    json_path = "".join(_json_path_segment(part) for part in path)
    return "={{$('" + safe_node + "').first().json" + json_path + "}}"


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


def _compile_trigger_spec(name: str, trigger: WorkflowTriggerSpec) -> WorkflowNode:
    if trigger.kind == "on_demand":
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
    if trigger.kind == "schedule":
        if trigger.frequency != "daily":
            raise WorkflowSpecCompileError("WorkflowSpec V2 only supports daily schedules.")
        hour, minute = _parse_daily_time(trigger.time)
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
    raise WorkflowSpecCompileError(f"Unsupported trigger kind: {trigger.kind}")


def _compile_trigger(name: str, spec: WorkflowSpec) -> WorkflowNode:
    return _compile_trigger_spec(name, spec.trigger)


def _required_plan_param(params: dict[str, Any], *keys: str) -> Any:
    value = _input_value(params, *keys)
    if value is None:
        raise WorkflowPlanCompileError(f"Missing required param: {keys[0]}")
    return value


def _ref_value(value: Any) -> str | None:
    if isinstance(value, dict):
        ref = value.get("ref")
        return str(ref).strip() if isinstance(ref, str) and ref.strip() else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("input.", "item.", "json.")):
            return stripped
    return None


def _plan_value_expression(value: Any, *, trigger_name: str) -> Any:
    ref = _ref_value(value)
    if ref:
        if ref.startswith("input."):
            field = ref.removeprefix("input.").strip()
            if not field:
                raise WorkflowPlanCompileError(f"Invalid input ref: {ref}")
            return _json_path_expression(trigger_name, ["body", field])
        if ref.startswith(("item.", "json.")):
            field = ref.split(".", 1)[1].strip()
            if not field:
                raise WorkflowPlanCompileError(f"Invalid item ref: {ref}")
            return _json_field_expression(field)
        raise WorkflowPlanCompileError(f"Unsupported ref: {ref}")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.upper() in {"NOW()", "=NOW()"}:
            return "={{$now.toISO()}}"
        if value.startswith("="):
            return value
        if "{{" in value:
            return f"={value}"
    return value


def _iter_input_refs(value: Any):
    ref = _ref_value(value)
    if ref and ref.startswith("input."):
        field = ref.removeprefix("input.").strip()
        if field:
            yield field
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_input_refs(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_input_refs(nested)


def _default_input_field(name: str) -> WorkflowInputField:
    if name == "to":
        return WorkflowInputField(
            name="to",
            label="Recipient email",
            type="email",
            placeholder="name@example.com",
        )
    if name == "subject":
        return WorkflowInputField(
            name="subject",
            label="Subject",
            type="string",
            placeholder="Email subject",
        )
    if name == "message":
        return WorkflowInputField(
            name="message",
            label="Message",
            type="textarea",
            placeholder="Email body",
        )
    return WorkflowInputField(name=name, label=name.replace("_", " ").title())


def _plan_input_schema(plan: WorkflowPlan) -> list[WorkflowInputField]:
    fields = _normalized_input_schema(plan.inputs)
    seen = {field.name for field in fields}
    for action in plan.actions:
        for field_name in _iter_input_refs(action.params):
            if field_name in seen:
                continue
            fields.append(_default_input_field(field_name))
            seen.add(field_name)
    return fields


def _sheet_schema(column_names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": column,
            "type": "string",
            "display": True,
            "removed": False,
            "required": False,
            "displayName": column,
            "defaultMatch": False,
            "canBeUsedToMatch": True,
        }
        for column in column_names
    ]


def _plan_sheets_append_values(params: dict[str, Any], *, trigger_name: str) -> dict[str, Any]:
    columns = params.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise WorkflowPlanCompileError("Missing required param: columns")
    values = {
        column_name: _plan_value_expression(value, trigger_name=trigger_name)
        for column, value in columns.items()
        if (column_name := str(column).strip())
    }
    if not values:
        raise WorkflowPlanCompileError("Sheets append columns must not be empty.")
    return values


def _unique_node_name(base: str, used: set[str]) -> str:
    if base not in used:
        used.add(base)
        return base
    index = 2
    while f"{base} {index}" in used:
        index += 1
    name = f"{base} {index}"
    used.add(name)
    return name


def _unique_node_id(base: str, used: set[str], reserved: set[str] | None = None) -> str:
    reserved = reserved or set()
    candidate = base
    index = 2
    while candidate in used or candidate in reserved:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _add_connection(connections: dict[str, Any], source: str, target: str) -> None:
    source_connections = connections.setdefault(source, {})
    outputs = source_connections.setdefault("main", [[]])
    if not outputs:
        outputs.append([])
    outputs[0].append({"node": target, "type": "main", "index": 0})


def _compile_plan_gmail_send(
    action: WorkflowActionSpec,
    *,
    node_name: str,
    position: list[int],
    trigger_name: str,
) -> WorkflowNode:
    params = action.params
    return WorkflowNode(
        id=action.id,
        name=node_name,
        type=_GMAIL_NODE_TYPE,
        typeVersion=_schema_type_version(_GMAIL_NODE_TYPE),
        position=position,
        parameters={
            "resource": "message",
            "operation": "send",
            "sendTo": _plan_value_expression(
                _required_plan_param(params, "to"),
                trigger_name=trigger_name,
            ),
            "subject": _plan_value_expression(
                _required_plan_param(params, "subject"),
                trigger_name=trigger_name,
            ),
            "message": _plan_value_expression(
                _required_plan_param(params, "message"),
                trigger_name=trigger_name,
            ),
            "emailType": "text",
        },
    )


def _compile_plan_set_row(
    *,
    node_id: str,
    node_name: str,
    position: list[int],
    values: dict[str, Any],
) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        name=node_name,
        type=_SET_NODE_TYPE,
        typeVersion=_schema_type_version(_SET_NODE_TYPE),
        position=position,
        parameters={
            "mode": "manual",
            "assignments": {
                "assignments": [
                    {
                        "id": column,
                        "name": column,
                        "type": "string",
                        "value": value,
                    }
                    for column, value in values.items()
                ]
            },
            "includeOtherFields": False,
            "options": {},
        },
    )


def _compile_plan_sheets_read_rows(
    action: WorkflowActionSpec,
    *,
    node_name: str,
    position: list[int],
) -> WorkflowNode:
    params = action.params
    document_id = str(_required_plan_param(params, "document_id", "spreadsheet_id")).strip()
    sheet_value = str(_required_plan_param(params, "sheet_name", "sheet_id", "sheet")).strip()
    sheet_mode = "id" if _input_value(params, "sheet_id") is not None else "name"
    return WorkflowNode(
        id=action.id,
        name=node_name,
        type=_GOOGLE_SHEETS_NODE_TYPE,
        typeVersion=_schema_type_version(_GOOGLE_SHEETS_NODE_TYPE),
        position=position,
        parameters={
            "authentication": "oAuth2",
            "resource": "sheet",
            "operation": "read",
            "documentId": _sheet_locator(document_id, mode="id"),
            "sheetName": _sheet_locator(sheet_value, mode=sheet_mode),
            "options": {},
        },
    )


def _compile_plan_sheets_append(
    action: WorkflowActionSpec,
    *,
    node_name: str,
    position: list[int],
    trigger_name: str,
    values: dict[str, Any] | None = None,
) -> WorkflowNode:
    params = action.params
    document_id = str(_required_plan_param(params, "document_id", "spreadsheet_id")).strip()
    sheet_value = str(_required_plan_param(params, "sheet_name", "sheet_id", "sheet")).strip()
    sheet_mode = "id" if _input_value(params, "sheet_id") is not None else "name"
    if values is None:
        _plan_sheets_append_values(params, trigger_name=trigger_name)
    return WorkflowNode(
        id=action.id,
        name=node_name,
        type=_GOOGLE_SHEETS_NODE_TYPE,
        typeVersion=_schema_type_version(_GOOGLE_SHEETS_NODE_TYPE),
        position=position,
        parameters={
            "authentication": "oAuth2",
            "resource": "sheet",
            "operation": "append",
            "documentId": _sheet_locator(document_id, mode="id"),
            "sheetName": _sheet_locator(sheet_value, mode=sheet_mode),
            "columns": {
                "mappingMode": "autoMapInputData",
                "value": {},
            },
            "options": {"handlingExtraData": "insertInNewColumn"},
        },
    )


def _compile_plan_filter(
    action: WorkflowActionSpec,
    *,
    node_name: str,
    position: list[int],
    trigger_name: str,
) -> WorkflowNode:
    params = action.params
    filter_field = _required_plan_param(params, "field", "column")
    filter_value = _required_plan_param(params, "value")
    operator_type, operation = _filter_operation(params.get("operator"), filter_value)
    left_value = (
        _plan_value_expression(filter_field, trigger_name=trigger_name)
        if _ref_value(filter_field)
        else _json_field_expression(str(filter_field))
    )
    return WorkflowNode(
        id=action.id,
        name=node_name,
        type=_FILTER_NODE_TYPE,
        typeVersion=_schema_type_version(_FILTER_NODE_TYPE),
        position=position,
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
                        "leftValue": left_value,
                        "rightValue": _plan_value_expression(
                            filter_value,
                            trigger_name=trigger_name,
                        ),
                    }
                ],
            },
        },
    )


def _compile_plan_action(
    action: WorkflowActionSpec,
    *,
    node_name: str,
    position: list[int],
    trigger_name: str,
) -> WorkflowNode:
    if action.action == "gmail.send":
        return _compile_plan_gmail_send(
            action,
            node_name=node_name,
            position=position,
            trigger_name=trigger_name,
        )
    if action.action == "sheets.read_rows":
        return _compile_plan_sheets_read_rows(action, node_name=node_name, position=position)
    if action.action == "sheets.row.append":
        return _compile_plan_sheets_append(
            action,
            node_name=node_name,
            position=position,
            trigger_name=trigger_name,
        )
    if action.action == "core.filter":
        return _compile_plan_filter(
            action,
            node_name=node_name,
            position=position,
            trigger_name=trigger_name,
        )
    raise WorkflowPlanCompileError(f"Unsupported action: {action.action}")


_ACTION_NODE_BASE = {
    "gmail.send": "Gmail",
    "sheets.read_rows": "Google Sheets",
    "sheets.row.append": "Google Sheets Append",
    "core.filter": "Filter",
}


def compile_workflow_plan(name: str, plan: WorkflowPlan) -> CompiledWorkflowSpec:
    """Compile a semantic action graph into n8n workflow pieces."""

    trigger = _compile_trigger_spec(name, plan.trigger)
    nodes = [trigger]
    connections: dict[str, Any] = {}
    action_nodes: dict[str, str] = {}
    used_names = {trigger.name}
    used_node_ids = {trigger.id}
    reserved_action_ids = {action.id for action in plan.actions}
    previous_action_id: str | None = None
    x_position = 500

    for action in plan.actions:
        if action.id in action_nodes:
            raise WorkflowPlanCompileError(f"Duplicate action id: {action.id}")
        if action.id in used_node_ids:
            raise WorkflowPlanCompileError(f"Duplicate node id: {action.id}")
        used_node_ids.add(action.id)
        source_ref = action.after or previous_action_id or "trigger"
        if source_ref in {"trigger", trigger.name}:
            source_name = trigger.name
        else:
            source_name = action_nodes.get(source_ref)
            if not source_name:
                raise WorkflowPlanCompileError(f"Unknown action dependency: {source_ref}")

        base_name = _ACTION_NODE_BASE.get(action.action, action.action)
        node_name = _unique_node_name(base_name, used_names)
        if action.action == "sheets.row.append":
            values = _plan_sheets_append_values(action.params, trigger_name=trigger.name)
            prepare_node = _compile_plan_set_row(
                node_id=_unique_node_id(
                    f"{action.id}_row",
                    used_node_ids,
                    reserved=reserved_action_ids,
                ),
                node_name=_unique_node_name("Prepare Sheets Row", used_names),
                position=[x_position, 300],
                values=values,
            )
            x_position += 250
            append_node = _compile_plan_sheets_append(
                action,
                node_name=node_name,
                position=[x_position, 300],
                trigger_name=trigger.name,
                values=values,
            )
            x_position += 250
            nodes.extend([prepare_node, append_node])
            action_nodes[action.id] = append_node.name
            _add_connection(connections, source_name, prepare_node.name)
            _add_connection(connections, prepare_node.name, append_node.name)
            previous_action_id = action.id
            continue

        node = _compile_plan_action(
            action,
            node_name=node_name,
            position=[x_position, 300],
            trigger_name=trigger.name,
        )
        x_position += 250
        nodes.append(node)
        action_nodes[action.id] = node.name
        _add_connection(connections, source_name, node.name)
        previous_action_id = action.id

    return CompiledWorkflowSpec(
        nodes=nodes,
        connections=connections,
        input_schema=_plan_input_schema(plan),
    )


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
    # This on-demand Gmail send is parametric by construction (the node already
    # carries the body expressions above), so declare the schema explicitly
    # rather than infer it from the now-filled fields.
    runtime_schema = _normalized_input_schema(input_schema) or list(_GMAIL_RUNTIME_INPUT_FIELDS)
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


async def _create_compiled_workflow_payload(
    deps: AgentDeps,
    name: str,
    validated_nodes: list[WorkflowNode],
    validated_connections: dict[str, Any],
    runtime_schema: list[WorkflowInputField],
    resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_dicts = dump_workflow_nodes(validated_nodes)
    try:
        workflow = await n8n_client.create_workflow(
            name=name,
            nodes=node_dicts,
            connections=validated_connections,
        )
    except Exception as exc:
        return {"error": _safe_error(exc)}

    metadata_kwargs: dict[str, Any] = {"input_schema": _input_schema_payload(runtime_schema)}
    if resources:
        metadata_kwargs["resources"] = resources
    await store.save_workflow_metadata(deps.user_id, workflow.id, **metadata_kwargs)

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


async def _provision_plan_resources(
    deps: AgentDeps,
    plan: WorkflowPlan,
) -> tuple[WorkflowPlan, dict[str, Any]]:
    updated = plan.model_copy(deep=True)
    resources: dict[str, Any] = {}
    for action in updated.actions:
        if action.action != "sheets.row.append":
            continue
        params = action.params
        has_spreadsheet = _input_value(params, "document_id", "spreadsheet_id") is not None
        if has_spreadsheet:
            continue
        title = str(
            params.get("spreadsheet_title")
            or params.get("spreadsheet_name")
            or params.get("document_title")
            or ""
        ).strip()
        if not title:
            continue
        sheet_name = str(
            params.get("sheet_name") or params.get("sheet") or params.get("sheet_title") or "Sheet1"
        ).strip()
        provisioned = await provision_spreadsheet_for_workflow(
            deps,
            title=title,
            sheet_name=sheet_name,
            action_id=action.id,
        )
        params["spreadsheet_id"] = provisioned["spreadsheet_id"]
        params.setdefault("sheet_name", sheet_name)
        resources[f"{action.id}.spreadsheet"] = provisioned
    return updated, resources


async def create_workflow_from_plan_payload(
    deps: AgentDeps,
    name: str,
    plan: WorkflowPlan,
) -> dict[str, Any]:
    """Compile WorkflowPlan and create the resulting n8n workflow."""

    try:
        plan, provisioned_resources = await _provision_plan_resources(deps, plan)
        compiled = compile_workflow_plan(name, plan)
        validated_nodes, validated_connections = _validated_workflow(
            compiled.nodes,
            compiled.connections,
        )
    except (WorkflowSpecCompileError, ModelRetry, PlatformActionError) as exc:
        return {
            "error": str(exc),
            "fallback": (
                "Use create_workflow only if the requested workflow is outside the "
                "supported WorkflowPlan compiler."
            ),
        }

    return await _create_compiled_workflow_payload(
        deps,
        name,
        validated_nodes,
        validated_connections,
        compiled.input_schema,
        provisioned_resources,
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

    return await _create_compiled_workflow_payload(
        deps,
        name,
        validated_nodes,
        validated_connections,
        runtime_schema,
    )
