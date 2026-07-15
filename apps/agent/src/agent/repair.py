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
  4. expressions         — {{input.x}} -> trigger body expr; declared runtime
                           inputs read via $json.<field> become $json.body.<field>
                           (node fed directly by the trigger) or
                           $('<trigger>').first().json.body.<field> (any later
                           node); fields holding {{ }} get the leading '=' so n8n
                           evaluates them (Code jsCode excluded)
  5. email attribution   — email-send nodes (Gmail send/reply, Send Email) get
                           options.appendAttribution=false so n8n stops appending
                           "This email was sent automatically with n8n" (only when
                           the model has not made an explicit choice)
  6. sheets schema       — googleSheets row ops written in the pre-v4 shape
                           (resource "spreadsheet" + spreadsheetId + range) are
                           upgraded to v4 (resource "sheet" + documentId +
                           sheetName); the v4 router has no read/update handler
                           under "spreadsheet", so the node crashes otherwise
  7. resourceLocators    — bare-string RL params (googleSheets documentId/
                           sheetName) wrapped into {"__rl", "mode", "value"};
                           a string n8n reads as value/mode undefined otherwise
  8. webhook response    — webhook triggers get responseMode=lastNode so a Conduut
                           run returns the execution result (default "onReceived"
                           acks immediately -> "no response from n8n")

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

# node type -> {parameter: default resourceLocator mode}. n8n expects these
# fields as {"__rl": True, "mode", "value"} objects; the model's natural prior is
# a bare string, which n8n reads as value/mode undefined ("Can not get sheet
# 'undefined' ...") at runtime. Mirrors the curated compilers' RL handling.
_RESOURCE_LOCATOR_FIELDS: dict[str, dict[str, str]] = {
    "n8n-nodes-base.googleSheets": {"documentId": "id", "sheetName": "name"},
}

_GOOGLE_SHEETS_TYPE = "n8n-nodes-base.googleSheets"
# googleSheets operations that only exist under resource "sheet" (row-level ops).
# Under resource "spreadsheet" the node's router implements ONLY create/delete of
# the spreadsheet file, so these resolve to undefined and crash at runtime. The
# ambiguous ops (create/delete exist under both resources) are deliberately
# excluded so a genuine "delete spreadsheet" is never rewritten.
_SHEET_ROW_OPERATIONS = frozenset({"read", "update", "append", "appendOrUpdate", "clear", "remove"})
# A1 notation with no sheet/tab prefix, e.g. "A", "A1", "A:F", "A1:C10". A bare
# googleSheets ``range`` that matches this is a real cell range (left for
# validation); a bare value that does NOT match is a tab name -> sheetName.
_A1_RANGE_RE = re.compile(r"^[A-Za-z]{1,3}\d*(?::[A-Za-z]{1,3}\d*)?$")

_INPUT_EXPR_RE = re.compile(r"\{\{\s*input\.(\w+)\s*\}\}")
_JSON_DOT_RE = re.compile(r"\$json\.(?!body\.)(\w+)")
_JSON_BRACKET_RE = re.compile(r"""\$json\[(['"])(\w+)\1\]""")
_JSON_BODY_RE = re.compile(r"\$json\.body\.(\w+)")


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
    _repair_http_array_indexing(nodes, connections, repairs)
    _normalize_google_sheets_schema(nodes, repairs)
    _normalize_resource_locators(nodes, repairs)
    _strip_email_attribution(nodes, repairs)
    _normalize_webhook_response_mode(nodes, repairs)

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

    # A node directly fed by the trigger reads webhook input as $json.body.<field>.
    # Any other node must qualify the reference to the trigger node, because its
    # own $json is the previous node's output (e.g. the AI Agent's {output}).
    qualified = f"$('{trigger_name}').first().json.body." if trigger_name else "$json.body."

    def _input_repl(match: re.Match[str]) -> str:
        field = match.group(1)
        if trigger_name:
            return "{{$('" + trigger_name + "').first().json.body." + field + "}}"
        return "{{$json.body." + field + "}}"

    def transform(text: str, is_fed: bool, add_prefix: bool = True) -> str:
        new = _INPUT_EXPR_RE.sub(_input_repl, text)
        if runtime_fields:
            if is_fed:
                # bare $json.<field> / $json["<field>"] -> $json.body.<field>
                new = _JSON_DOT_RE.sub(
                    lambda m: (
                        f"$json.body.{m.group(1)}" if m.group(1) in runtime_fields else m.group(0)
                    ),
                    new,
                )
                new = _JSON_BRACKET_RE.sub(
                    lambda m: (
                        f"$json.body.{m.group(2)}" if m.group(2) in runtime_fields else m.group(0)
                    ),
                    new,
                )
            else:
                # $json.body.<field> / $json.<field> / $json["<field>"] -> qualified
                new = _JSON_BODY_RE.sub(
                    lambda m: (
                        f"{qualified}{m.group(1)}" if m.group(1) in runtime_fields else m.group(0)
                    ),
                    new,
                )
                new = _JSON_DOT_RE.sub(
                    lambda m: (
                        f"{qualified}{m.group(1)}" if m.group(1) in runtime_fields else m.group(0)
                    ),
                    new,
                )
                new = _JSON_BRACKET_RE.sub(
                    lambda m: (
                        f"{qualified}{m.group(2)}" if m.group(2) in runtime_fields else m.group(0)
                    ),
                    new,
                )
        return _ensure_expression(new) if add_prefix else new

    # Code nodes hold JavaScript, not an n8n expression; rewrite $json paths but
    # never prefix '=' (that would turn the code into an expression).
    code_types = {"n8n-nodes-base.code", "n8n-nodes-base.function"}
    for node in nodes:
        is_fed = node["name"] in trigger_fed
        prefix = node.get("type") not in code_types
        parameters = node.get("parameters")
        if not isinstance(parameters, Mapping):
            continue
        rewritten = _rewrite_strings(
            parameters, lambda text, fed=is_fed, pre=prefix: transform(text, fed, pre)
        )
        if rewritten != parameters:
            node["parameters"] = rewritten
            repairs.append(f"rewrote runtime-input expressions in '{node['name']}'")


def _ensure_expression(text: str) -> str:
    """n8n evaluates {{ }} only when the field value is an expression (starts
    with '='). The model often omits the '=', so a {{ }} reference is sent
    literally. Prefix '=' when the string contains a template but is not yet an
    expression."""

    if "{{" in text and not text.startswith("="):
        return "=" + text
    return text


def _rewrite_strings(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, Mapping):
        return {key: _rewrite_strings(nested, fn) for key, nested in value.items()}
    if isinstance(value, list):
        return [_rewrite_strings(nested, fn) for nested in value]
    return value


# ---------------------------------------------------------------------------
# Stage 5b — HTTP array-response indexing
# ---------------------------------------------------------------------------

_HTTP_REQUEST_TYPE = "n8n-nodes-base.httpRequest"
# Direct reference on the current item: $json[0].field
_JSON_INDEX_RE = re.compile(r"\$json\[\d+\]\.")


def _repair_http_array_indexing(
    nodes: list[dict[str, Any]],
    connections: Mapping[str, Any],
    repairs: list[str],
) -> None:
    """Drop array indexing on HTTP Request output references.

    n8n's HTTP Request node splits a JSON array response into separate items, so
    the next node's $json is the OBJECT, not the array — $json[0].field resolves
    to empty. Rewrite $json[0].field -> $json.field for nodes directly fed by an
    HTTP Request node, and $('Http').first().json[0].field -> ...json.field for
    any node referencing one. Scoped to HTTP nodes so genuine arrays (e.g. a Code
    node's output) are left alone.
    """

    http_names = {
        node["name"]
        for node in nodes
        if isinstance(node, dict) and node.get("type") == _HTTP_REQUEST_TYPE and node.get("name")
    }
    if not http_names:
        return

    http_fed: set[str] = set()
    for source in http_names:
        conn = connections.get(source)
        if not isinstance(conn, Mapping):
            continue
        for group in conn.get("main", []) or []:
            for target in group or []:
                if isinstance(target, Mapping) and target.get("node"):
                    http_fed.add(str(target["node"]))

    ref_patterns = [
        re.compile(r"(\$\((['\"])" + re.escape(name) + r"\2\)[^\[]*?\.json)\[\d+\]\.")
        for name in http_names
    ]

    touched: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        parameters = node.get("parameters")
        if not isinstance(parameters, Mapping):
            continue
        is_fed = node.get("name") in http_fed

        def fix(text: str, _fed: bool = is_fed) -> str:
            new = text
            for pattern in ref_patterns:
                new = pattern.sub(r"\1.", new)
            if _fed:
                new = _JSON_INDEX_RE.sub("$json.", new)
            return new

        rewritten = _rewrite_strings(parameters, fix)
        if rewritten != parameters:
            node["parameters"] = rewritten
            if node.get("name"):
                touched.append(str(node["name"]))
    if touched:
        repairs.append(
            "rewrote HTTP array indexing ($json[0] -> $json) for " + ", ".join(sorted(set(touched)))
        )


# ---------------------------------------------------------------------------
# Stage 5 — strip n8n email attribution footer
# ---------------------------------------------------------------------------

# Operations on email-send nodes that append the n8n attribution footer.
_EMAIL_ATTRIBUTION_OPERATIONS = {"send", "reply"}


def _is_email_send_node(node: dict[str, Any]) -> bool:
    """True for nodes that append "This email was sent automatically with n8n"."""

    node_type = node.get("type")
    parameters = node.get("parameters")
    operation = parameters.get("operation") if isinstance(parameters, Mapping) else None
    if node_type == "n8n-nodes-base.emailSend":
        # Default operation is send; a missing operation still sends mail.
        return operation is None or operation in _EMAIL_ATTRIBUTION_OPERATIONS
    if node_type == "n8n-nodes-base.gmail":
        resource = parameters.get("resource") if isinstance(parameters, Mapping) else None
        return resource == "message" and operation in _EMAIL_ATTRIBUTION_OPERATIONS
    return False


def _strip_email_attribution(nodes: list[dict[str, Any]], repairs: list[str]) -> None:
    for node in nodes:
        if not _is_email_send_node(node):
            continue
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
            node["parameters"] = parameters
        options = parameters.get("options")
        if not isinstance(options, dict):
            options = {}
            parameters["options"] = options
        if "appendAttribution" not in options:
            options["appendAttribution"] = False
            repairs.append(f"disabled n8n email attribution on '{node.get('name')}'")


# ---------------------------------------------------------------------------
# Stage 6 — resourceLocator normalization
# ---------------------------------------------------------------------------


def _normalize_google_sheets_schema(nodes: list[dict[str, Any]], repairs: list[str]) -> None:
    """Upgrade legacy/compact googleSheets params to the v4 addressing shape.

    The model frequently emits a pre-v4 mental model for row operations::

        resource: "spreadsheet", operation: "read"/"update", spreadsheetId, range

    On the installed googleSheets v4 node this crashes at runtime: the node's
    router dispatches resource ``"spreadsheet"`` to a module implementing only
    ``create``/``delete`` of the spreadsheet file, so ``read``/``update`` resolve
    to ``undefined`` (``Cannot read properties of undefined (reading 'execute')``).
    v4 addresses rows via resource ``"sheet"`` + ``documentId``/``sheetName``
    resourceLocators. This maps deterministically:

    * ``resource: "spreadsheet"`` + a row-level op -> ``resource: "sheet"``
    * ``spreadsheetId`` (string) -> ``documentId`` (wrapped into an ``__rl`` object
      by :func:`_normalize_resource_locators`, which runs next)
    * ``range: "Tab!A:F"`` -> ``sheetName: "Tab"`` (v4 read/update have no free A1
      range; the tab is the literal before ``!``). A range without ``!`` is
      ambiguous (bare tab vs bare A1 range) and is left for validation.

    The update column mapping (``dataMode``/``values``) is intentionally left
    untouched: reconstructing the matching column is ambiguous, so it is deferred
    to validation / ModelRetry rather than guessed (a wrong guess writes to the
    wrong row).
    """

    for node in nodes:
        if node.get("type") != _GOOGLE_SHEETS_TYPE:
            continue
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            continue
        name = node.get("name")
        operation = parameters.get("operation")

        if parameters.get("resource") == "spreadsheet" and operation in _SHEET_ROW_OPERATIONS:
            parameters["resource"] = "sheet"
            repairs.append(f"set googleSheets resource=sheet on '{name}'")

        spreadsheet_id = parameters.get("spreadsheetId")
        if isinstance(spreadsheet_id, str) and spreadsheet_id and "documentId" not in parameters:
            del parameters["spreadsheetId"]
            parameters["documentId"] = spreadsheet_id
            repairs.append(f"mapped googleSheets spreadsheetId->documentId on '{name}'")

        range_value = parameters.get("range")
        if isinstance(range_value, str) and range_value.strip() and "sheetName" not in parameters:
            raw = range_value.lstrip("=").strip().strip("'\"")
            if "!" in raw:
                # "Tab!A:F" -> the tab is the literal before "!".
                tab = raw.split("!", 1)[0].strip().strip("'\"")
            elif raw and not _A1_RANGE_RE.match(raw):
                # Bare value, no "!", not A1 notation ("Kayıtlar", "Orders",
                # "Sheet1") -> it is the tab name. A bare A1 range ("A:F",
                # "A1:C10") has no v4 field and is left for validation.
                tab = raw
            else:
                tab = ""
            if tab:
                del parameters["range"]
                parameters["sheetName"] = tab
                repairs.append(f"mapped googleSheets range->sheetName on '{name}'")

        # v4 append needs a column mapping to know what to write; the model often
        # omits it, so n8n rejects the node. autoMapInputData (n8n's "Map
        # Automatically") maps the incoming item fields to same-named columns --
        # the only unambiguous default for append. update/appendOrUpdate need a
        # matching column, so they are NOT auto-filled (left to validation). Only
        # fills when absent; an explicit mapping is preserved.
        if operation == "append" and "columns" not in parameters:
            parameters["columns"] = {
                "mappingMode": "autoMapInputData",
                "matchingColumns": [],
                "schema": [],
            }
            repairs.append(f"set googleSheets append autoMap columns on '{name}'")

        columns = parameters.get("columns")
        if isinstance(columns, dict):
            _normalize_sheets_columns_shape(columns, name, repairs)


def _sheets_schema_entry(column: str) -> dict[str, Any]:
    """One googleSheets v4 ResourceMapper schema entry for a defineBelow column."""

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


def _normalize_sheets_columns_shape(columns: dict[str, Any], name: Any, repairs: list[str]) -> None:
    """Normalize a googleSheets ``defineBelow`` column mapping to the shape n8n v4
    actually executes: a flat ``value`` map plus a ``schema`` array. The model
    sometimes emits the values as ``value: {"mappingValues": [{"column",
    "mappingValue"}]}`` and omits ``schema`` -> n8n throws "Could not get
    parameter: columns.schema" at runtime (confirmed on scenario E1). Correct
    mappings and ``autoMapInputData`` (which needs no value/schema) are left alone.
    """

    value = columns.get("value")
    changed = False

    # ``define`` is a plausible model shorthand, but it is not a ResourceMapper
    # mode understood by the Google Sheets v4 node. n8n then reaches for
    # ``columns.schema`` using an invalid shape and fails at execution time.
    if str(columns.get("mappingMode") or "").lower() == "define":
        columns["mappingMode"] = "defineBelow"
        changed = True

    # Flatten value.mappingValues[{column, mappingValue}] -> {column: expr}.
    if isinstance(value, dict) and isinstance(value.get("mappingValues"), list):
        flat: dict[str, Any] = {}
        for item in value["mappingValues"]:
            if isinstance(item, dict) and item.get("column"):
                flat[str(item["column"])] = item.get("mappingValue", "")
        columns["value"] = flat
        value = flat
        columns.setdefault("mappingMode", "defineBelow")
        changed = True

    mode = str(columns.get("mappingMode") or "").lower()
    if mode == "definebelow" and isinstance(value, dict) and value:
        # Synthesize the schema from the mapped columns when absent; without it
        # n8n cannot read columns.schema and fails at runtime.
        schema = columns.get("schema")
        if not (isinstance(schema, list) and schema):
            columns["schema"] = [_sheets_schema_entry(col) for col in value]
            changed = True
        columns.setdefault("matchingColumns", [])

    if changed:
        repairs.append(f"normalized googleSheets column mapping on '{name}'")


def _normalize_resource_locators(nodes: list[dict[str, Any]], repairs: list[str]) -> None:
    """Wrap bare-string resourceLocator params (e.g. googleSheets documentId/
    sheetName) into n8n ``{"__rl": True, "mode", "value"}`` objects. Values that
    are already resourceLocator dicts (or non-strings) are left untouched."""

    for node in nodes:
        fields = _RESOURCE_LOCATOR_FIELDS.get(node.get("type") or "")
        if not fields:
            continue
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for field_name, default_mode in fields.items():
            value = parameters.get(field_name)
            if not isinstance(value, str) or not value:
                # missing, already an __rl dict, or non-string -> leave for validate
                continue
            mode = "url" if value.startswith(("http://", "https://")) else default_mode
            parameters[field_name] = {"__rl": True, "mode": mode, "value": value}
            repairs.append(f"wrapped resourceLocator '{field_name}' on '{node.get('name')}'")


# ---------------------------------------------------------------------------
# Stage 7 — webhook responseMode (so Conduut runs return execution data)
# ---------------------------------------------------------------------------


def _normalize_webhook_response_mode(nodes: list[dict[str, Any]], repairs: list[str]) -> None:
    """Reconcile the webhook trigger's responseMode with how it returns data.

    Without responseMode (or with "onReceived") n8n acks immediately and the run
    returns no execution data, so Conduut shows "no response from n8n". When the
    workflow has a Respond to Webhook node, the webhook MUST use
    responseMode=responseNode — with lastNode (or default) n8n rejects the run as
    "Unused Respond to Webhook node found". Otherwise lastNode makes the webhook
    return the final node's output synchronously.
    """

    has_respond_node = any(
        isinstance(node, dict) and node.get("type") == "n8n-nodes-base.respondToWebhook"
        for node in nodes
    )
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.webhook":
            continue
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
            node["parameters"] = parameters
        current = parameters.get("responseMode")
        if has_respond_node:
            if current != "responseNode":
                parameters["responseMode"] = "responseNode"
                repairs.append(f"set webhook responseMode=responseNode on '{node.get('name')}'")
        elif current in (None, "", "onReceived"):
            parameters["responseMode"] = "lastNode"
            repairs.append(f"set webhook responseMode=lastNode on '{node.get('name')}'")


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
