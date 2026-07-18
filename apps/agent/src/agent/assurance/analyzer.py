"""Deterministic graph and dataflow assurance for normalized n8n workflows."""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.agent.assurance.contracts import NodeContract, output_contract
from src.agent.assurance.fingerprint import workflow_semantic_fingerprint
from src.agent.assurance.models import (
    AssuranceFinding,
    AssurancePlan,
    AssuranceReport,
    FindingSeverity,
)
from src.agent.schemas import WorkflowNode

_UNQUALIFIED_JSON_DOT = re.compile(r"\$json\s*(?:\.|\?\.)\s*([A-Za-z_][A-Za-z0-9_]*)")
_UNQUALIFIED_JSON_BRACKET = re.compile(r"\$json\s*\[\s*['\"]([^'\"]+)['\"]\s*\]")
_TRIGGER_TYPES = {
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.webhook",
}
_SHEETS_UPDATE_OPERATIONS = {"update", "appendorupdate"}


def _node_dict(node: WorkflowNode | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(node, WorkflowNode):
        return node.model_dump(exclude_none=True)
    return dict(node)


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_strings(nested)


def _unqualified_json_fields(value: Any) -> set[str]:
    fields: set[str] = set()
    for text in _iter_strings(value):
        fields.update(_UNQUALIFIED_JSON_DOT.findall(text))
        fields.update(_UNQUALIFIED_JSON_BRACKET.findall(text))
    return fields


def _main_targets(connections: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, connection in connections.items():
        if not isinstance(connection, Mapping):
            continue
        groups = connection.get("main")
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, list):
                continue
            for target in group:
                if not isinstance(target, Mapping) or not target.get("node"):
                    continue
                if str(target.get("type") or "main") != "main":
                    continue
                adjacency[str(source)].append(str(target["node"]))
    return {source: tuple(targets) for source, targets in adjacency.items()}


def _is_trigger(node: Mapping[str, Any]) -> bool:
    node_type = str(node.get("type") or "")
    return node_type in _TRIGGER_TYPES or "trigger" in node_type.lower()


def _graph_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]], adjacency: Mapping[str, tuple[str, ...]]
) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    trigger_names = {name for name, node in nodes_by_name.items() if _is_trigger(node)}
    for source, targets in adjacency.items():
        for target in targets:
            if target in trigger_names:
                findings.append(
                    AssuranceFinding(
                        code="trigger_back_edge",
                        severity=FindingSeverity.ERROR,
                        node_name=target,
                        related_nodes=(source,),
                        message=(
                            f"Main-flow connection '{source}' -> '{target}' points back into a "
                            "trigger. Trigger nodes must start a run and cannot receive main input."
                        ),
                    )
                )

    state: dict[str, int] = {}
    stack: list[str] = []
    reported: set[frozenset[str]] = set()

    def visit(node_name: str) -> None:
        state[node_name] = 1
        stack.append(node_name)
        for target in adjacency.get(node_name, ()):
            target_state = state.get(target, 0)
            if target_state == 0:
                visit(target)
            elif target_state == 1:
                start = stack.index(target)
                cycle = tuple(stack[start:] + [target])
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    findings.append(
                        AssuranceFinding(
                            code="main_flow_cycle",
                            severity=FindingSeverity.ERROR,
                            node_name=target,
                            related_nodes=cycle,
                            message=f"Main workflow contains a cycle: {' -> '.join(cycle)}.",
                        )
                    )
        stack.pop()
        state[node_name] = 2

    for node_name in nodes_by_name:
        if state.get(node_name, 0) == 0:
            visit(node_name)
    return findings


def _if_findings(nodes_by_name: Mapping[str, Mapping[str, Any]]) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    for name, node in nodes_by_name.items():
        if node.get("type") != "n8n-nodes-base.if":
            continue
        parameters = node.get("parameters")
        conditions = parameters.get("conditions") if isinstance(parameters, Mapping) else None
        rules = conditions.get("conditions") if isinstance(conditions, Mapping) else None
        if not isinstance(rules, list) or len(rules) < 2:
            continue
        combinator = str(conditions.get("combinator") or "").lower()
        if combinator not in {"and", "or"}:
            findings.append(
                AssuranceFinding(
                    code="if_combinator_missing",
                    severity=FindingSeverity.ERROR,
                    node_name=name,
                    message=(
                        f"IF node '{name}' has multiple conditions but no explicit "
                        "conditions.combinator. Set it to 'and' or 'or'."
                    ),
                )
            )
    return findings


def _predecessors(adjacency: Mapping[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = defaultdict(list)
    for source, targets in adjacency.items():
        for target in targets:
            result[target].append(source)
    return {target: tuple(sources) for target, sources in result.items()}


def _gmail_dataflow_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]], adjacency: Mapping[str, tuple[str, ...]]
) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    for source, targets in adjacency.items():
        source_node = nodes_by_name.get(source)
        if source_node is None:
            continue
        contract = output_contract(source_node)
        if contract is None or source_node.get("type") != "n8n-nodes-base.gmail":
            continue
        parameters = source_node.get("parameters")
        params = parameters if isinstance(parameters, Mapping) else {}
        if str(params.get("resource") or "message").lower() != "message":
            continue
        if str(params.get("operation") or "send").lower() != "send":
            continue
        for target in targets:
            target_node = nodes_by_name.get(target)
            if target_node is None:
                continue
            fields = _unqualified_json_fields(target_node.get("parameters") or {})
            unavailable = sorted(
                field for field in fields if contract.field_is_available(field) is False
            )
            if unavailable:
                findings.append(
                    AssuranceFinding(
                        code="gmail_output_field_unavailable",
                        severity=FindingSeverity.ERROR,
                        node_name=target,
                        related_nodes=(source,),
                        message=(
                            f"Node '{target}' reads "
                            f"{', '.join(f'$json.{field}' for field in unavailable)} immediately "
                            f"after Gmail send node '{source}'. Gmail send replaces the "
                            "input item with id/threadId/labelIds; use an explicit upstream node "
                            "reference or preserve the business item with a merge step."
                        ),
                    )
                )
    return findings


def _matching_columns(node: Mapping[str, Any]) -> tuple[list[str], Mapping[str, Any], str]:
    parameters = node.get("parameters")
    params = parameters if isinstance(parameters, Mapping) else {}
    columns = params.get("columns")
    column_map = columns if isinstance(columns, Mapping) else {}
    raw_matching = column_map.get("matchingColumns")
    matching = (
        [str(value).strip() for value in raw_matching if str(value).strip()]
        if isinstance(raw_matching, list)
        else []
    )
    values = column_map.get("value")
    value_map = values if isinstance(values, Mapping) else {}
    mode = str(column_map.get("mappingMode") or "defineBelow").lower()
    return matching, value_map, mode


def _field_liveness(
    field: str,
    predecessors: tuple[str, ...],
    nodes_by_name: Mapping[str, Mapping[str, Any]],
) -> tuple[bool | None, tuple[str, ...]]:
    if not predecessors:
        return False, ()
    known_results: list[bool] = []
    unresolved: list[str] = []
    for predecessor in predecessors:
        node = nodes_by_name.get(predecessor)
        contract: NodeContract | None = output_contract(node) if node is not None else None
        if contract is None:
            unresolved.append(predecessor)
            continue
        result = contract.field_is_available(field)
        if result is None:
            unresolved.append(predecessor)
        else:
            known_results.append(result)
    if any(known_results):
        return True, tuple(unresolved)
    if unresolved:
        return None, tuple(unresolved)
    return False, ()


def _sheets_matching_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]], adjacency: Mapping[str, tuple[str, ...]]
) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    predecessors = _predecessors(adjacency)
    for name, node in nodes_by_name.items():
        if node.get("type") != "n8n-nodes-base.googleSheets":
            continue
        parameters = node.get("parameters")
        params = parameters if isinstance(parameters, Mapping) else {}
        operation = str(params.get("operation") or "").lower()
        if operation not in _SHEETS_UPDATE_OPERATIONS:
            continue
        matching, value_map, mode = _matching_columns(node)
        if not matching:
            findings.append(
                AssuranceFinding(
                    code="sheets_matching_key_missing",
                    severity=FindingSeverity.ERROR,
                    node_name=name,
                    message=f"Google Sheets update node '{name}' has no matching column.",
                )
            )
            continue

        for match_key in matching:
            match_value = value_map.get(match_key)
            if mode == "definebelow" and not str(match_value or "").strip():
                findings.append(
                    AssuranceFinding(
                        code="sheets_matching_value_missing",
                        severity=FindingSeverity.ERROR,
                        node_name=name,
                        message=(
                            f"Google Sheets update node '{name}' matches on '{match_key}' but "
                            "does not map a value for that key."
                        ),
                    )
                )
                continue

            required_fields = (
                _unqualified_json_fields(match_value) if mode == "definebelow" else {match_key}
            )
            for required_field in sorted(required_fields):
                live, unresolved = _field_liveness(
                    required_field, predecessors.get(name, ()), nodes_by_name
                )
                if live is False:
                    findings.append(
                        AssuranceFinding(
                            code="sheets_matching_key_not_live",
                            severity=FindingSeverity.ERROR,
                            node_name=name,
                            related_nodes=predecessors.get(name, ()),
                            message=(
                                f"Google Sheets update node '{name}' needs "
                                f"'$json.{required_field}' "
                                "for its matching key, but its immediate predecessor output cannot "
                                "provide that field."
                            ),
                        )
                    )
                elif live is None:
                    findings.append(
                        AssuranceFinding(
                            code="sheets_matching_key_liveness_unproven",
                            severity=FindingSeverity.SHADOW,
                            node_name=name,
                            related_nodes=unresolved,
                            message=(
                                f"Could not statically prove that '$json.{required_field}' is live "
                                f"at Google Sheets update node '{name}'."
                            ),
                        )
                    )
    return findings


def _contract_coverage_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]], adjacency: Mapping[str, tuple[str, ...]]
) -> list[AssuranceFinding]:
    participating = set(adjacency)
    participating.update(target for targets in adjacency.values() for target in targets)
    findings: list[AssuranceFinding] = []
    for name in sorted(participating):
        node = nodes_by_name.get(name)
        if node is None or output_contract(node) is not None:
            continue
        findings.append(
            AssuranceFinding(
                code="contract_coverage_missing",
                severity=FindingSeverity.SHADOW,
                node_name=name,
                message=(
                    f"Node '{name}' ({node.get('type')}) has no static output contract; "
                    "field-liveness checks remain in shadow mode for this boundary."
                ),
            )
        )
    return findings


def _can_reach(source: str, target: str, adjacency: Mapping[str, tuple[str, ...]]) -> bool:
    pending = list(adjacency.get(source, ()))
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency.get(current, ()))
    return False


def _choreography_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]], adjacency: Mapping[str, tuple[str, ...]]
) -> list[AssuranceFinding]:
    actions: list[str] = []
    writebacks: list[str] = []
    for name, node in nodes_by_name.items():
        node_type = str(node.get("type") or "")
        parameters = node.get("parameters")
        params = parameters if isinstance(parameters, Mapping) else {}
        operation = str(params.get("operation") or "").lower()
        if node_type == "n8n-nodes-base.gmail" and operation in {"", "send"}:
            actions.append(name)
        if node_type == "n8n-nodes-base.googleSheets" and operation in _SHEETS_UPDATE_OPERATIONS:
            writebacks.append(name)

    findings: list[AssuranceFinding] = []
    for writeback in writebacks:
        unsafe_actions = [action for action in actions if _can_reach(writeback, action, adjacency)]
        if unsafe_actions:
            findings.append(
                AssuranceFinding(
                    code="writeback_before_action",
                    severity=FindingSeverity.ERROR,
                    node_name=writeback,
                    related_nodes=tuple(unsafe_actions),
                    message=(
                        f"Write-back node '{writeback}' runs before side-effect action "
                        f"{', '.join(repr(name) for name in unsafe_actions)}. If the action "
                        "fails, the source row would already be marked complete. Run the action "
                        "first and write back only from its successful receipt path."
                    ),
                )
            )
            continue
        if actions and not any(_can_reach(action, writeback, adjacency) for action in actions):
            findings.append(
                AssuranceFinding(
                    code="action_writeback_order_ambiguous",
                    severity=FindingSeverity.SHADOW,
                    node_name=writeback,
                    related_nodes=tuple(actions),
                    message=(
                        f"Could not prove that write-back node '{writeback}' is downstream of a "
                        "successful action receipt. Keep the action and write-back on one explicit "
                        "success path."
                    ),
                )
            )
    return findings


def _assurance_plan(
    fingerprint: str,
    nodes_by_name: Mapping[str, Mapping[str, Any]],
) -> AssurancePlan:
    roles: dict[str, str] = {}
    identities: dict[str, tuple[str, ...]] = {}
    action_names: list[str] = []
    writeback_names: list[str] = []
    for name, node in nodes_by_name.items():
        contract = output_contract(node)
        if _is_trigger(node):
            roles[name] = "trigger"
        elif contract and contract.side_effect:
            parameters = node.get("parameters")
            params = parameters if isinstance(parameters, Mapping) else {}
            if (
                node.get("type") == "n8n-nodes-base.googleSheets"
                and str(params.get("operation") or "").lower() in _SHEETS_UPDATE_OPERATIONS
            ):
                roles[name] = "writeback"
                writeback_names.append(name)
                matching, _, _ = _matching_columns(node)
                if matching:
                    identities[name] = tuple(matching)
            else:
                roles[name] = "action"
                action_names.append(name)
        elif contract and contract.pass_through:
            roles[name] = "filter_or_passthrough"
        else:
            roles[name] = "transform_or_read"

    cardinality: list[str] = []
    postconditions: list[str] = []
    if action_names:
        cardinality.append("eligible_count == action_count")
        postconditions.append("every action has a provider receipt")
    if writeback_names:
        cardinality.append("action_count == writeback_count")
        postconditions.append("every successful action has one write-back")
        postconditions.append("write-back identity is non-empty and unique")
    return AssurancePlan(
        fingerprint=fingerprint,
        node_roles=roles,
        cardinality_relations=tuple(cardinality),
        identity_fields=identities,
        expected_postconditions=tuple(postconditions),
    )


def analyze_workflow_semantics(
    nodes: Sequence[WorkflowNode | Mapping[str, Any]],
    connections: Mapping[str, Any] | None,
) -> AssuranceReport:
    """Run deterministic assurance checks over a normalized workflow graph."""

    raw_nodes = [_node_dict(node) for node in nodes]
    nodes_by_name = {
        str(node.get("name")): node for node in raw_nodes if str(node.get("name") or "")
    }
    normalized_connections = dict(connections or {})
    adjacency = _main_targets(normalized_connections)
    findings = [
        *_graph_findings(nodes_by_name, adjacency),
        *_if_findings(nodes_by_name),
        *_gmail_dataflow_findings(nodes_by_name, adjacency),
        *_sheets_matching_findings(nodes_by_name, adjacency),
        *_choreography_findings(nodes_by_name, adjacency),
        *_contract_coverage_findings(nodes_by_name, adjacency),
    ]
    # Stable ordering keeps ModelRetry feedback and tests deterministic.
    findings.sort(
        key=lambda finding: (
            0 if finding.blocking else 1,
            finding.code,
            finding.node_name or "",
            finding.message,
        )
    )
    fingerprint = workflow_semantic_fingerprint(raw_nodes, normalized_connections)
    return AssuranceReport(
        fingerprint=fingerprint,
        plan=_assurance_plan(fingerprint, nodes_by_name),
        findings=tuple(findings),
    )
