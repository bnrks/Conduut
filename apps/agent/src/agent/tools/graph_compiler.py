"""Graph workflow compiler.

Compiles a semantic :class:`WorkflowGraph` (typed nodes + edges + AI sub-nodes)
into validated n8n workflow JSON. The agent only writes a small semantic graph;
this module owns every piece of n8n boilerplate: exact node type and
typeVersion, connection topology (main, branch true/false, AI ``ai_*`` ports),
positions, webhook ids, resourceLocators, expression syntax and runtime inputs.

Curated nodes resolve through :data:`blocks.BLOCKS`; anything else resolves
through the generic ``n8n:<exact-type>`` fallback so uncommon nodes still work
best-effort. Validation runs at the end, surfacing problems back to the agent.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic_ai import ModelRetry

from src.agent.schemas import (
    AgentDeps,
    GraphNode,
    WorkflowGraph,
    WorkflowInputField,
    WorkflowNode,
)
from src.agent.tools.blocks import ROLE_PORTS, UNSET, Block, ParamRule, get_block
from src.agent.tools.runtime_inputs import _normalized_input_schema
from src.agent.tools.spec_compiler import (
    CompiledWorkflowSpec,
    WorkflowSpecCompileError,
    _create_compiled_workflow_payload,
    _default_input_field,
    _filter_operation,
    _iter_input_refs,
    _json_field_expression,
    _json_path_expression,
    _parse_daily_time,
    _plan_value_expression,
    _ref_value,
    _sheet_locator,
    _unique_node_name,
    _webhook_path,
)
from src.agent.tools.validation import _validated_runtime_workflow
from src.registry import registry

_N8N_TYPE_PREFIXES = ("n8n-nodes-base.", "@n8n/", "n8n-nodes-")
_GENERIC_PREFIX = "n8n:"


class WorkflowGraphCompileError(WorkflowSpecCompileError):
    """Raised when a WorkflowGraph cannot be compiled without guessing."""


@dataclass
class _Ctx:
    trigger_name: str
    id_to_name: dict[str, str]


# ---------------------------------------------------------------------------
# Value / expression helpers
# ---------------------------------------------------------------------------


def _is_ref(value: Any) -> bool:
    if isinstance(value, dict) and isinstance(value.get("ref"), str):
        return True
    return _ref_value(value) is not None


def _graph_value_expression(value: Any, *, ctx: _Ctx) -> Any:
    """Resolve a semantic value into an n8n literal or expression.

    Adds ``node.<id>.<path>`` cross-node references on top of the plan
    compiler's ``input.*`` / ``item.*`` / ``json.*`` handling.
    """

    if isinstance(value, dict) and isinstance(value.get("ref"), str):
        ref = value["ref"].strip()
        if ref.startswith("node."):
            parts = [part for part in ref[len("node.") :].split(".") if part]
            if len(parts) < 2:
                raise WorkflowGraphCompileError(f"node ref must be node.<id>.<field>, got '{ref}'")
            node_id, path = parts[0], parts[1:]
            name = ctx.id_to_name.get(node_id)
            if not name:
                raise WorkflowGraphCompileError(f"node ref points to unknown node id '{node_id}'")
            return _json_path_expression(name, path)
    return _plan_value_expression(value, trigger_name=ctx.trigger_name)


def _expr_walk(value: Any, ctx: _Ctx) -> Any:
    if isinstance(value, dict):
        if isinstance(value.get("ref"), str):
            return _graph_value_expression(value, ctx=ctx)
        return {key: _expr_walk(item, ctx) for key, item in value.items()}
    if isinstance(value, list):
        return [_expr_walk(item, ctx) for item in value]
    if isinstance(value, str):
        return _plan_value_expression(value, trigger_name=ctx.trigger_name)
    return value


def _assignment_type(value: Any) -> str:
    if isinstance(value, dict) and "ref" in value:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _required_param(gnode: GraphNode, *keys: str) -> Any:
    for key in keys:
        value = gnode.params.get(key)
        if value not in (None, ""):
            return value
    raise WorkflowGraphCompileError(f"node '{gnode.id}' ({gnode.kind}) requires param '{keys[0]}'")


# ---------------------------------------------------------------------------
# typeVersion resolution
# ---------------------------------------------------------------------------


def _resolve_type_version(n8n_type: str, fallback: int | float | None) -> int | float:
    schema = registry.get_node_schema(n8n_type)
    if isinstance(schema, dict):
        type_version = schema.get("typeVersion")
        if isinstance(type_version, int | float) and not isinstance(type_version, bool):
            return type_version
    if fallback is not None:
        return fallback
    raise WorkflowGraphCompileError(
        f"No typeVersion available for '{n8n_type}'. Call get_node_schema or use a supported kind."
    )


# ---------------------------------------------------------------------------
# Builders (rich parameter shapes referenced by Block.builder)
# ---------------------------------------------------------------------------


def _conditions_payload(field: Any, operator: Any, value: Any, ctx: _Ctx) -> dict[str, Any]:
    operator_type, operation = _filter_operation(operator, value)
    left = (
        _graph_value_expression(field, ctx=ctx)
        if _is_ref(field)
        else _json_field_expression(str(field))
    )
    return {
        "options": {
            "version": 2,
            "leftValue": "",
            "caseSensitive": True,
            "typeValidation": "strict",
        },
        "combinator": "and",
        "conditions": [
            {
                "id": "condition",
                "operator": {"type": operator_type, "operation": operation},
                "leftValue": left,
                "rightValue": _graph_value_expression(value, ctx=ctx),
            }
        ],
    }


def _build_set_fields(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    fields = gnode.params.get("fields")
    if fields is None:
        fields = gnode.params.get("values")
    if not isinstance(fields, dict) or not fields:
        raise WorkflowGraphCompileError(
            f"set node '{gnode.id}' requires a non-empty 'fields' map of name -> value"
        )
    assignments = []
    for raw_name, raw_value in fields.items():
        name = str(raw_name).strip()
        if not name:
            continue
        assignments.append(
            {
                "id": name,
                "name": name,
                "type": _assignment_type(raw_value),
                "value": _graph_value_expression(raw_value, ctx=ctx),
            }
        )
    if not assignments:
        raise WorkflowGraphCompileError(f"set node '{gnode.id}' fields must not be empty")
    params["mode"] = "manual"
    params["assignments"] = {"assignments": assignments}
    params["includeOtherFields"] = bool(gnode.params.get("include_other_fields", True))
    params["options"] = {}


def _build_if(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    field = gnode.params.get("field", gnode.params.get("column"))
    if field is None or "value" not in gnode.params:
        raise WorkflowGraphCompileError(f"if node '{gnode.id}' requires 'field' and 'value' params")
    params["conditions"] = _conditions_payload(
        field, gnode.params.get("operator"), gnode.params.get("value"), ctx
    )
    params["options"] = {}


def _build_filter(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    field = gnode.params.get("field", gnode.params.get("column"))
    if field is None or "value" not in gnode.params:
        raise WorkflowGraphCompileError(
            f"filter node '{gnode.id}' requires 'field' and 'value' params"
        )
    params["conditions"] = _conditions_payload(
        field, gnode.params.get("operator"), gnode.params.get("value"), ctx
    )
    params["options"] = {}


def _build_code(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    code = _required_param(gnode, "code", "js_code", "python_code")
    language = str(gnode.params.get("language", "javascript")).lower()
    if language in {"python", "py", "pythonnative", "python (beta)"}:
        params["language"] = "python"
        params["pythonCode"] = str(code)
    else:
        params["language"] = "javaScript"
        params["jsCode"] = str(code)


def _build_http_request(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    params["url"] = _graph_value_expression(_required_param(gnode, "url"), ctx=ctx)
    params["method"] = str(gnode.params.get("method", "GET")).upper()

    headers = gnode.params.get("headers")
    if isinstance(headers, dict) and headers:
        params["sendHeaders"] = True
        params["headerParameters"] = {
            "parameters": [
                {"name": str(key), "value": _graph_value_expression(val, ctx=ctx)}
                for key, val in headers.items()
            ]
        }

    query = gnode.params.get("query")
    if isinstance(query, dict) and query:
        params["sendQuery"] = True
        params["queryParameters"] = {
            "parameters": [
                {"name": str(key), "value": _graph_value_expression(val, ctx=ctx)}
                for key, val in query.items()
            ]
        }

    body = gnode.params.get("body", gnode.params.get("json_body", gnode.params.get("json")))
    if body is not None:
        params["sendBody"] = True
        params["specifyBody"] = "json"
        if isinstance(body, dict | list):
            params["jsonBody"] = json.dumps(_expr_walk(body, ctx))
        else:
            params["jsonBody"] = _graph_value_expression(body, ctx=ctx)

    params["options"] = {}


def _build_ai_agent(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    text = gnode.params.get("text", gnode.params.get("prompt", gnode.params.get("input")))
    if text is not None:
        params["promptType"] = "define"
        params["text"] = _graph_value_expression(text, ctx=ctx)
    else:
        params["promptType"] = "auto"

    options: dict[str, Any] = {}
    system = gnode.params.get("system_prompt", gnode.params.get("system"))
    if system:
        options["systemMessage"] = str(system)
    max_iterations = gnode.params.get("max_iterations")
    if isinstance(max_iterations, int) and not isinstance(max_iterations, bool):
        options["maxIterations"] = max_iterations
    params["options"] = options


def _build_chat_model(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    model = gnode.params.get("model")
    if model:
        params["model"] = {"__rl": True, "mode": "list", "value": str(model)}
    params.setdefault("options", {})


def _build_gmail_send(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    params["resource"] = "message"
    params["operation"] = "send"
    params["sendTo"] = _graph_value_expression(_required_param(gnode, "to"), ctx=ctx)
    params["subject"] = _graph_value_expression(_required_param(gnode, "subject"), ctx=ctx)
    params["message"] = _graph_value_expression(_required_param(gnode, "message"), ctx=ctx)
    params["emailType"] = "text"


def _build_sheets_read(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    document_id = str(_required_param(gnode, "spreadsheet_id", "document_id")).strip()
    sheet_value = str(_required_param(gnode, "sheet_name", "sheet_id", "sheet")).strip()
    sheet_mode = "id" if gnode.params.get("sheet_id") not in (None, "") else "name"
    params["authentication"] = "oAuth2"
    params["resource"] = "sheet"
    params["operation"] = "read"
    params["documentId"] = _sheet_locator(document_id, mode="id")
    params["sheetName"] = _sheet_locator(sheet_value, mode=sheet_mode)
    params["options"] = {}


def _build_sheets_append(gnode: GraphNode, params: dict[str, Any], ctx: _Ctx) -> None:
    document_id = str(_required_param(gnode, "spreadsheet_id", "document_id")).strip()
    sheet_value = str(_required_param(gnode, "sheet_name", "sheet_id", "sheet")).strip()
    sheet_mode = "id" if gnode.params.get("sheet_id") not in (None, "") else "name"
    params["authentication"] = "oAuth2"
    params["resource"] = "sheet"
    params["operation"] = "append"
    params["documentId"] = _sheet_locator(document_id, mode="id")
    params["sheetName"] = _sheet_locator(sheet_value, mode=sheet_mode)
    params["columns"] = {"mappingMode": "autoMapInputData", "value": {}}
    params["options"] = {"handlingExtraData": "insertInNewColumn"}


_BUILDERS = {
    "set_fields": _build_set_fields,
    "if_conditions": _build_if,
    "filter_conditions": _build_filter,
    "code": _build_code,
    "http_request": _build_http_request,
    "ai_agent": _build_ai_agent,
    "chat_model": _build_chat_model,
    "gmail_send": _build_gmail_send,
    "sheets_read": _build_sheets_read,
    "sheets_append": _build_sheets_append,
}


# ---------------------------------------------------------------------------
# Node compilation
# ---------------------------------------------------------------------------


def _set_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cursor = target
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def _apply_rule(
    params: dict[str, Any], key: str, rule: ParamRule, gnode: GraphNode, ctx: _Ctx
) -> None:
    if rule.const is not UNSET:
        value = rule.const
    else:
        raw = gnode.params.get(rule.source or key, UNSET)
        if raw is UNSET:
            if rule.required:
                raise WorkflowGraphCompileError(
                    f"node '{gnode.id}' ({gnode.kind}) requires param '{rule.source or key}'"
                )
            if rule.default is UNSET:
                return
            value = rule.default
        else:
            value = raw
    if rule.enum_map:
        value = rule.enum_map.get(str(value), value)
    if rule.rl_mode:
        value = {"__rl": True, "mode": rule.rl_mode, "value": value}
    elif rule.expr:
        value = _graph_value_expression(value, ctx=ctx)
    _set_path(params, rule.path, value)


def _looks_generic(kind: str) -> bool:
    return kind.startswith(_GENERIC_PREFIX) or kind.startswith(_N8N_TYPE_PREFIXES)


def _generic_type(kind: str) -> str:
    return kind[len(_GENERIC_PREFIX) :] if kind.startswith(_GENERIC_PREFIX) else kind


def _generic_display(kind: str) -> str:
    return _generic_type(kind).split(".")[-1] or "Node"


def _compile_generic_node(gnode: GraphNode, name: str, ctx: _Ctx) -> WorkflowNode:
    n8n_type = _generic_type(gnode.kind)
    type_version = _resolve_type_version(n8n_type, None)
    params = _expr_walk(dict(gnode.params), ctx)
    return WorkflowNode(
        id=gnode.id,
        name=name,
        type=n8n_type,
        typeVersion=type_version,
        position=[0, 0],
        parameters=params if isinstance(params, dict) else {},
    )


def _compile_block_node(gnode: GraphNode, block: Block, name: str, ctx: _Ctx) -> WorkflowNode:
    params: dict[str, Any] = deepcopy(block.static)
    for key, rule in block.params.items():
        _apply_rule(params, key, rule, gnode, ctx)
    if block.builder:
        _BUILDERS[block.builder](gnode, params, ctx)
    type_version = _resolve_type_version(block.n8n_type, block.type_version)
    return WorkflowNode(
        id=gnode.id,
        name=name,
        type=block.n8n_type,
        typeVersion=type_version,
        position=[0, 0],
        parameters=params,
    )


def _compile_trigger(name: str, gnode: GraphNode, used_names: set[str]) -> WorkflowNode:
    block = get_block(gnode.kind)
    if block is None or not block.is_trigger:
        if _looks_generic(gnode.kind):
            display = gnode.name or _generic_display(gnode.kind)
            return _compile_generic_node(
                gnode, _unique_node_name(display, used_names), _Ctx("", {})
            )
        raise WorkflowGraphCompileError(
            f"Unknown trigger kind '{gnode.kind}'. Use manual, webhook, schedule, chat, "
            "or n8n:<trigger-type>."
        )

    node_name = _unique_node_name(gnode.name or block.base_name or "Trigger", used_names)
    type_version = _resolve_type_version(block.n8n_type, block.type_version)

    if gnode.kind in {"webhook", "on_demand"}:
        return WorkflowNode(
            id=gnode.id,
            name=node_name,
            type=block.n8n_type,
            typeVersion=type_version,
            position=[250, 300],
            parameters={
                "httpMethod": "POST",
                "path": _webhook_path(name),
                "responseMode": "lastNode",
                "options": {},
            },
            webhookId=str(uuid4()),
        )
    if gnode.kind == "schedule":
        raw_time = gnode.params.get("time")
        hour, minute = _parse_daily_time(str(raw_time) if raw_time else None)
        params = {
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
        }
    else:
        params = deepcopy(block.static)

    return WorkflowNode(
        id=gnode.id,
        name=node_name,
        type=block.n8n_type,
        typeVersion=type_version,
        position=[250, 300],
        parameters=params,
    )


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


def _add_main_connection(connections: dict[str, Any], source: str, target: str, index: int) -> None:
    node_conns = connections.setdefault(source, {})
    outputs = node_conns.setdefault("main", [])
    while len(outputs) <= index:
        outputs.append([])
    outputs[index].append({"node": target, "type": "main", "index": 0})


def _add_typed_connection(connections: dict[str, Any], source: str, target: str, port: str) -> None:
    node_conns = connections.setdefault(source, {})
    groups = node_conns.setdefault(port, [[]])
    if not groups:
        groups.append([])
    groups[0].append({"node": target, "type": port, "index": 0})


def _output_index(block: Block | None, on: str | None, source_id: str) -> int:
    if on is None:
        return 0
    if block and on in block.output_ports:
        return block.output_ports[on]
    default = {"true": 0, "false": 1, "yes": 0, "no": 1}
    key = on.strip().lower()
    if key in default:
        return default[key]
    raise WorkflowGraphCompileError(f"node '{source_id}' has no '{on}' branch output")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _assign_positions(
    graph: WorkflowGraph,
    main_ids: list[str],
    sub_nodes: list[GraphNode],
    compiled_by_id: dict[str, WorkflowNode],
) -> None:
    depth: dict[str, int] = {graph.trigger.id: 0}
    for _ in range(len(main_ids) + 1):
        changed = False
        for edge in graph.edges:
            if edge.source in depth:
                candidate = depth[edge.source] + 1
                if depth.get(edge.target, -1) < candidate:
                    depth[edge.target] = candidate
                    changed = True
        if not changed:
            break

    by_depth: dict[int, list[str]] = {}
    for node_id in [graph.trigger.id, *main_ids]:
        level = depth.get(node_id, 1)
        by_depth.setdefault(level, []).append(node_id)
    for level, node_ids in by_depth.items():
        for row, node_id in enumerate(node_ids):
            compiled_by_id[node_id].position = [250 + level * 260, 300 + row * 180]

    child_index: dict[str, int] = {}
    for sub in sub_nodes:
        parent = compiled_by_id[sub.attached_to]
        index = child_index.get(sub.attached_to, 0)
        child_index[sub.attached_to] = index + 1
        parent_x, parent_y = parent.position
        compiled_by_id[sub.id].position = [parent_x - 40 + index * 200, parent_y + 220]


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


def _graph_input_schema(graph: WorkflowGraph) -> list[WorkflowInputField]:
    fields = _normalized_input_schema(graph.inputs)
    seen = {field.name for field in fields}
    for gnode in [graph.trigger, *graph.nodes]:
        for field_name in _iter_input_refs(gnode.params):
            if field_name in seen:
                continue
            fields.append(_default_input_field(field_name))
            seen.add(field_name)
    return fields


# ---------------------------------------------------------------------------
# Top-level compile
# ---------------------------------------------------------------------------


def compile_workflow_graph(name: str, graph: WorkflowGraph) -> CompiledWorkflowSpec:
    """Compile a semantic workflow graph into n8n nodes and connections."""

    all_nodes = [graph.trigger, *graph.nodes]
    ids = [node.id for node in all_nodes]
    if len(ids) != len(set(ids)):
        raise WorkflowGraphCompileError("Duplicate node id in graph; node ids must be unique.")
    id_set = set(ids)

    main_nodes = [node for node in graph.nodes if not node.attached_to]
    sub_nodes = [node for node in graph.nodes if node.attached_to]
    sub_ids = {node.id for node in sub_nodes}

    for sub in sub_nodes:
        if sub.attached_to not in id_set:
            raise WorkflowGraphCompileError(
                f"sub-node '{sub.id}' attached_to unknown node '{sub.attached_to}'"
            )
        if sub.attached_to in sub_ids:
            raise WorkflowGraphCompileError(
                f"sub-node '{sub.id}' cannot attach to another sub-node"
            )
        if not sub.role:
            raise WorkflowGraphCompileError(f"sub-node '{sub.id}' requires a 'role'")

    for gnode in main_nodes:
        block = get_block(gnode.kind)
        if block and block.sub_only:
            raise WorkflowGraphCompileError(
                f"'{gnode.kind}' is an AI sub-node and cannot stand alone in the main flow. "
                f"Add an ai_agent node and attach this node to it: set "
                f"attached_to=<agent id> and role (language_model / memory / tool). "
                f"Do not put it on edges."
            )

    for edge in graph.edges:
        if edge.source not in id_set:
            raise WorkflowGraphCompileError(f"edge source '{edge.source}' is not a known node")
        if edge.target not in id_set:
            raise WorkflowGraphCompileError(f"edge target '{edge.target}' is not a known node")
        if edge.source in sub_ids or edge.target in sub_ids:
            raise WorkflowGraphCompileError(
                "edges connect main nodes only; attach sub-nodes via attached_to instead"
            )

    used_names: set[str] = set()
    trigger_node = _compile_trigger(name, graph.trigger, used_names)
    id_to_name = {graph.trigger.id: trigger_node.name}
    block_by_id: dict[str, Block | None] = {graph.trigger.id: get_block(graph.trigger.kind)}

    # Pass 1: reserve display names so node.<id> refs resolve during pass 2.
    planned: list[tuple[GraphNode, Block | None, str]] = []
    for gnode in [*main_nodes, *sub_nodes]:
        block = get_block(gnode.kind)
        if block is None and not _looks_generic(gnode.kind):
            raise WorkflowGraphCompileError(
                f"Unknown node kind '{gnode.kind}'. Use a supported kind or "
                "n8n:<exact-type> after get_node_schema."
            )
        base = gnode.name or (block.base_name if block else _generic_display(gnode.kind))
        node_name = _unique_node_name(base or gnode.kind, used_names)
        id_to_name[gnode.id] = node_name
        block_by_id[gnode.id] = block
        planned.append((gnode, block, node_name))

    ctx = _Ctx(trigger_name=trigger_node.name, id_to_name=id_to_name)

    # Pass 2: compile parameters.
    nodes = [trigger_node]
    compiled_by_id: dict[str, WorkflowNode] = {graph.trigger.id: trigger_node}
    for gnode, block, node_name in planned:
        if block is None:
            wnode = _compile_generic_node(gnode, node_name, ctx)
        else:
            wnode = _compile_block_node(gnode, block, node_name, ctx)
        nodes.append(wnode)
        compiled_by_id[gnode.id] = wnode

    connections: dict[str, Any] = {}
    for edge in graph.edges:
        index = _output_index(block_by_id.get(edge.source), edge.on, edge.source)
        _add_main_connection(connections, id_to_name[edge.source], id_to_name[edge.target], index)

    for sub in sub_nodes:
        parent_block = block_by_id.get(sub.attached_to)
        port = None
        if parent_block:
            port = parent_block.sub_ports.get(sub.role)
        port = port or ROLE_PORTS.get(sub.role)
        if not port:
            raise WorkflowGraphCompileError(f"sub-node '{sub.id}' has unknown role '{sub.role}'")
        _add_typed_connection(connections, id_to_name[sub.id], id_to_name[sub.attached_to], port)

    _assign_positions(graph, [node.id for node in main_nodes], sub_nodes, compiled_by_id)

    return CompiledWorkflowSpec(
        nodes=nodes,
        connections=connections,
        input_schema=_graph_input_schema(graph),
    )


async def create_workflow_from_graph_payload(
    deps: AgentDeps,
    name: str,
    graph: WorkflowGraph,
) -> dict[str, Any]:
    """Compile a WorkflowGraph and create the resulting n8n workflow."""

    try:
        compiled = compile_workflow_graph(name, graph)
        validated_nodes, validated_connections, runtime_schema = _validated_runtime_workflow(
            compiled.nodes,
            compiled.connections,
            compiled.input_schema,
        )
    except (WorkflowSpecCompileError, ModelRetry) as exc:
        return {
            "error": str(exc),
            "fallback": (
                "Fix the graph and retry, or use create_workflow with raw n8n JSON only "
                "if the workflow is outside the graph compiler."
            ),
        }

    return await _create_compiled_workflow_payload(
        deps,
        name,
        validated_nodes,
        validated_connections,
        runtime_schema,
    )
