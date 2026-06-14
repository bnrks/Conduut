"""Deterministic workflow repair layer.

The model writes compact, near-native n8n JSON (its strongest prior). This
module fixes the recurring mistakes deterministically *before* validation,
turning "reject + ModelRetry" into "repair" wherever there is a single correct
interpretation. Ambiguous cases are left untouched for
``validate_workflow_payload`` to reject (the safety net).

Repairs performed (in order):
  1. boilerplate fill   — id, typeVersion (registry), webhookId, position
  2. linear wiring       — infer sequential ``main`` connections when missing
  3. sub-node ports      — move langchain chat-model/memory/tool out of the main
                           flow onto the AI Agent's ai_* port (single-agent only)
  4. expressions         — {{input.x}} -> trigger body expr; bare $json.<field>
                           -> $json.body.<field> for declared runtime inputs read
                           by a node directly fed by the trigger

Every change is appended to a ``repairs`` list (logged, not user-facing) so we
can measure what fires and, later, build a finetune corpus.
"""

import copy
import re
from collections import deque
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import structlog

from src.agent.validation import _as_node_dict, _is_langchain_ai_subnode, _is_trigger_node
from src.registry import registry as default_registry

log = structlog.get_logger()

_LANGCHAIN_PREFIX = "@n8n/n8n-nodes-langchain."

# langchain sub-node local-name prefix -> n8n ai_* connection port
_SUBNODE_PORT_BY_LOCAL: tuple[tuple[str, str], ...] = (
    ("lm", "ai_languageModel"),
    ("memory", "ai_memory"),
    ("embeddings", "ai_embedding"),
    ("outputParser", "ai_outputParser"),
    ("textSplitter", "ai_textSplitter"),
    ("retriever", "ai_retriever"),
    ("tool", "ai_tool"),
)
# langchain nodes that DO have main I/O and accept ai_* sub-nodes
_AGENT_LOCALS = ("agent", "chainLlm", "conversationalAgent", "openAiAssistant")

_INPUT_EXPR_RE = re.compile(r"\{\{\s*input\.(\w+)\s*\}\}")
_JSON_DOT_RE = re.compile(r"\$json\.(?!body\.)(\w+)")
_JSON_BRACKET_RE = re.compile(r"""\$json\[(['"])(\w+)\1\]""")


def repair_workflow(
    nodes: list[dict[str, Any]],
    connections: Mapping[str, Any] | None,
    *,
    runtime_fields: set[str] | frozenset[str] = frozenset(),
    trigger_name: str | None = None,
    registry: Any = default_registry,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Repair compact n8n JSON in place-safe fashion. Returns (nodes, connections, repairs)."""

    nodes = [copy.deepcopy(_as_node_dict(node)) for node in nodes]
    connections = copy.deepcopy(dict(connections)) if connections else {}
    repairs: list[str] = []

    _fill_boilerplate(nodes, registry, repairs)

    if not connections:
        _infer_linear_connections(nodes, connections, repairs)

    if trigger_name is None:
        trigger_name = _find_trigger_name(nodes, registry)

    _repair_subnode_ports(nodes, connections, repairs)
    _assign_positions(nodes, connections)
    _repair_expressions(nodes, connections, set(runtime_fields), trigger_name, repairs)

    if repairs:
        log.info("workflow_repaired", repairs=repairs)
    return nodes, connections, repairs


# ---------------------------------------------------------------------------
# Stage 1 — boilerplate
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "node"


def _fill_boilerplate(nodes: list[dict[str, Any]], registry: Any, repairs: list[str]) -> None:
    used_ids = {str(node["id"]) for node in nodes if node.get("id")}
    for node in nodes:
        if not node.get("id"):
            base = _slugify(node.get("name") or node.get("type") or "node")
            candidate = base
            counter = 2
            while candidate in used_ids:
                candidate = f"{base}-{counter}"
                counter += 1
            used_ids.add(candidate)
            node["id"] = candidate
            repairs.append(f"filled id for '{node.get('name')}'")

        if node.get("typeVersion") is None:
            schema = registry.get_node_schema(node.get("type") or "") if node.get("type") else None
            if schema and schema.get("typeVersion") is not None:
                node["typeVersion"] = schema["typeVersion"]
                repairs.append(f"filled typeVersion for '{node.get('name')}'")

        if node.get("type") == "n8n-nodes-base.webhook" and not node.get("webhookId"):
            node["webhookId"] = str(uuid4())
            repairs.append(f"filled webhookId for '{node.get('name')}'")


# ---------------------------------------------------------------------------
# Stage 2 — linear connection inference
# ---------------------------------------------------------------------------


def _infer_linear_connections(
    nodes: list[dict[str, Any]],
    connections: dict[str, Any],
    repairs: list[str],
) -> None:
    main_nodes = [n for n in nodes if not _is_langchain_ai_subnode(n.get("type", ""))]
    if len(main_nodes) < 2:
        return
    for source, target in zip(main_nodes, main_nodes[1:], strict=False):
        _add_main(connections, source["name"], target["name"])
    repairs.append("inferred linear main connections")


# ---------------------------------------------------------------------------
# Stage 3 — sub-node port repair
# ---------------------------------------------------------------------------


def _find_trigger_name(nodes: list[dict[str, Any]], registry: Any) -> str | None:
    for node in nodes:
        node_type = node.get("type") or ""
        schema = registry.get_node_schema(node_type) if node_type else None
        if _is_trigger_node(node, schema):
            return node.get("name")
    return None


def _is_agent_node(node_type: str) -> bool:
    if not node_type.startswith(_LANGCHAIN_PREFIX):
        return False
    return node_type[len(_LANGCHAIN_PREFIX) :].startswith(_AGENT_LOCALS)


def _subnode_port(node_type: str) -> str:
    local = node_type[len(_LANGCHAIN_PREFIX) :]
    for prefix, port in _SUBNODE_PORT_BY_LOCAL:
        if local.startswith(prefix):
            return port
    return "ai_tool"


def _repair_subnode_ports(
    nodes: list[dict[str, Any]],
    connections: dict[str, Any],
    repairs: list[str],
) -> None:
    type_by_name = {n["name"]: n.get("type", "") for n in nodes}
    subnodes = [name for name, t in type_by_name.items() if _is_langchain_ai_subnode(t)]
    if not subnodes:
        return
    agents = [name for name, t in type_by_name.items() if _is_agent_node(t)]
    if len(agents) != 1:
        # zero or ambiguous target -> decline; validate will reject.
        return
    agent = agents[0]

    for sub in subnodes:
        if not _remove_node_from_main(connections, sub):
            continue
        port = _subnode_port(type_by_name[sub])
        _add_typed(connections, sub, agent, port)
        repairs.append(f"moved sub-node '{sub}' to {port} of '{agent}'")


# ---------------------------------------------------------------------------
# Stage 4 — positions (cosmetic; deterministic)
# ---------------------------------------------------------------------------


def _assign_positions(nodes: list[dict[str, Any]], connections: dict[str, Any]) -> None:
    name_to_node = {n["name"]: n for n in nodes}
    main_adj: dict[str, list[str]] = {}
    for source, value in connections.items():
        outs: list[str] = []
        for group in value.get("main", []) if isinstance(value, Mapping) else []:
            for conn in group:
                outs.append(conn["node"])
        main_adj[source] = outs

    targeted = {target for outs in main_adj.values() for target in outs}
    main_names = [n["name"] for n in nodes if not _is_langchain_ai_subnode(n.get("type", ""))]

    depth: dict[str, int] = {}
    queue: deque[str] = deque()
    for name in main_names:
        if name not in targeted:
            depth[name] = 0
            queue.append(name)
    while queue:
        current = queue.popleft()
        for nxt in main_adj.get(current, []):
            if nxt not in depth or depth[nxt] < depth[current] + 1:
                depth[nxt] = depth[current] + 1
                queue.append(nxt)

    rows: dict[int, int] = {}
    for name in main_names:
        level = depth.get(name, 0)
        row = rows.get(level, 0)
        rows[level] = row + 1
        name_to_node[name]["position"] = [250 + level * 260, 300 + row * 180]

    # Sub-nodes: place beneath the agent they attach to (via ai_* port).
    for source, value in connections.items():
        if not isinstance(value, Mapping):
            continue
        for port, groups in value.items():
            if not port.startswith("ai_"):
                continue
            for group in groups:
                for conn in group:
                    agent = name_to_node.get(conn["node"])
                    if agent and source in name_to_node:
                        ax, ay = agent.get("position", [250, 300])
                        name_to_node[source]["position"] = [ax, ay + 220]
    for node in nodes:
        node.setdefault("position", [250, 300])


# ---------------------------------------------------------------------------
# Stage 5 — expression repair
# ---------------------------------------------------------------------------


def _repair_expressions(
    nodes: list[dict[str, Any]],
    connections: dict[str, Any],
    runtime_fields: set[str],
    trigger_name: str | None,
    repairs: list[str],
) -> None:
    trigger_fed: set[str] = set()
    if trigger_name and isinstance(connections.get(trigger_name), Mapping):
        for group in connections[trigger_name].get("main", []):
            for conn in group:
                trigger_fed.add(conn["node"])

    def _input_repl(match: re.Match[str]) -> str:
        field = match.group(1)
        if trigger_name:
            return "{{$('" + trigger_name + "').first().json.body." + field + "}}"
        return "{{$json.body." + field + "}}"

    def _dot_repl(match: re.Match[str]) -> str:
        field = match.group(1)
        return f"$json.body.{field}" if field in runtime_fields else match.group(0)

    def _bracket_repl(match: re.Match[str]) -> str:
        field = match.group(2)
        return f"$json.body.{field}" if field in runtime_fields else match.group(0)

    for node in nodes:
        is_fed = node["name"] in trigger_fed

        def transform(text: str, is_fed: bool = is_fed) -> str:
            new = _INPUT_EXPR_RE.sub(_input_repl, text)
            if is_fed and runtime_fields:
                new = _JSON_DOT_RE.sub(_dot_repl, new)
                new = _JSON_BRACKET_RE.sub(_bracket_repl, new)
            return new

        parameters = node.get("parameters")
        if not isinstance(parameters, Mapping):
            continue
        rewritten = _rewrite_strings(parameters, transform)
        if rewritten != parameters:
            node["parameters"] = rewritten
            repairs.append(f"rewrote runtime-input expressions in '{node['name']}'")


def _rewrite_strings(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, Mapping):
        return {key: _rewrite_strings(nested, fn) for key, nested in value.items()}
    if isinstance(value, list):
        return [_rewrite_strings(nested, fn) for nested in value]
    return value


# ---------------------------------------------------------------------------
# Connection helpers (inlined; operate on plain n8n connection dicts)
# ---------------------------------------------------------------------------


def _add_main(connections: dict[str, Any], source: str, target: str, index: int = 0) -> None:
    node_conns = connections.setdefault(source, {})
    outputs = node_conns.setdefault("main", [])
    while len(outputs) <= index:
        outputs.append([])
    outputs[index].append({"node": target, "type": "main", "index": 0})


def _add_typed(connections: dict[str, Any], source: str, target: str, port: str) -> None:
    node_conns = connections.setdefault(source, {})
    groups = node_conns.setdefault(port, [[]])
    if not groups:
        groups.append([])
    groups[0].append({"node": target, "type": port, "index": 0})


def _remove_node_from_main(connections: dict[str, Any], name: str) -> bool:
    changed = False
    for value in connections.values():
        if not isinstance(value, Mapping) or "main" not in value:
            continue
        new_groups = []
        for group in value["main"]:
            filtered = [conn for conn in group if conn.get("node") != name]
            if len(filtered) != len(group):
                changed = True
            new_groups.append(filtered)
        value["main"] = new_groups
    if name in connections and "main" in connections[name]:
        del connections[name]["main"]
        changed = True
        if not connections[name]:
            del connections[name]
    return changed
