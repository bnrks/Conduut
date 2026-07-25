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
_FIRST_REFERENCE = re.compile(r"\$\(\s*['\"]([^'\"]+)['\"]\s*\)\.first\(\)\.json\b")
_TRIGGER_TYPES = {
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.webhook",
}
_SHEETS_UPDATE_OPERATIONS = {"update", "appendorupdate"}
_SPLIT_IN_BATCHES_TYPE = "n8n-nodes-base.splitInBatches"


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


def _node_references(value: Any, pattern: re.Pattern[str]) -> set[str]:
    refs: set[str] = set()
    for text in _iter_strings(value):
        refs.update(match.strip() for match in pattern.findall(text) if match.strip())
    return refs


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


def _split_output_label(output_index: int, branch_name: str) -> str:
    return f"main output {output_index} ('{branch_name}')"


def _main_targets(connections: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, connection in connections.items():
        for group in _main_connection_groups(connection):
            adjacency[str(source)].extend(str(target["node"]) for target in group)
    return {source: tuple(targets) for source, targets in adjacency.items()}


def _is_trigger(node: Mapping[str, Any]) -> bool:
    node_type = str(node.get("type") or "")
    return node_type in _TRIGGER_TYPES or "trigger" in node_type.lower()


def _sanctioned_split_loopback_edges(
    nodes_by_name: Mapping[str, Mapping[str, Any]],
    adjacency: Mapping[str, tuple[str, ...]],
    connections: Mapping[str, Any],
) -> set[tuple[str, str]]:
    sanctioned: set[tuple[str, str]] = set()
    predecessors = _predecessors(adjacency)

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
        if not loop_targets:
            continue

        loop_descendants = _descendants_from(loop_targets, adjacency, stop_at=name)
        done_descendants = _descendants_from(done_targets, adjacency, stop_at=name)
        for source in predecessors.get(name, ()):
            source_node = nodes_by_name.get(source)
            if (
                source in loop_descendants
                and source not in done_descendants
                and source_node is not None
                and not _is_trigger(source_node)
            ):
                sanctioned.add((source, name))

    return sanctioned


def _without_edges(
    adjacency: Mapping[str, tuple[str, ...]], ignored: set[tuple[str, str]]
) -> dict[str, tuple[str, ...]]:
    return {
        source: tuple(target for target in targets if (source, target) not in ignored)
        for source, targets in adjacency.items()
    }


def _graph_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]],
    adjacency: Mapping[str, tuple[str, ...]],
    connections: Mapping[str, Any],
) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    sanctioned_loopbacks = _sanctioned_split_loopback_edges(nodes_by_name, adjacency, connections)
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
            if (node_name, target) in sanctioned_loopbacks:
                continue
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


def _side_effect_first_reference_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]], adjacency: Mapping[str, tuple[str, ...]]
) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    for name, node in nodes_by_name.items():
        contract = output_contract(node)
        if contract is None or not contract.side_effect:
            continue

        parameters = node.get("parameters") or {}
        first_refs = _node_references(parameters, _FIRST_REFERENCE)
        if not first_refs:
            continue

        direct_predecessors = set(_predecessors(adjacency).get(name, ()))
        related_sources = sorted(
            source
            for source in first_refs
            if source in nodes_by_name
            and source in direct_predecessors
            and not _is_trigger(nodes_by_name[source])
        )
        if not related_sources:
            continue

        findings.append(
            AssuranceFinding(
                code="side_effect_direct_first_reference",
                severity=FindingSeverity.ERROR,
                node_name=name,
                related_nodes=tuple(related_sources),
                message=(
                    f"Side-effect node '{name}' reads its direct predecessor through "
                    f"{', '.join(f'$({source!r}).first().json' for source in related_sources)}. "
                    "This can reuse the first record's data for every item. Read the direct "
                    "predecessor through the current item ($json...) instead."
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


def _split_in_batches_findings(
    nodes_by_name: Mapping[str, Mapping[str, Any]],
    adjacency: Mapping[str, tuple[str, ...]],
    connections: Mapping[str, Any],
) -> list[AssuranceFinding]:
    findings: list[AssuranceFinding] = []
    predecessors = _predecessors(adjacency)

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
            for source in predecessors.get(name, ())
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
            if node_name != name
            and (contract := output_contract(nodes_by_name.get(node_name))) is not None
            and contract.side_effect
        )
        loop_side_effects = sorted(
            node_name
            for node_name in loop_descendants
            if node_name != name
            and (contract := output_contract(nodes_by_name.get(node_name))) is not None
            and contract.side_effect
        )

        if wrong_return_sources:
            wrong_label = (
                _split_output_label(done_output, "done")
                if any(source in done_descendants for source in wrong_return_sources)
                else f"a non-loop branch of '{name}'"
            )
            findings.append(
                AssuranceFinding(
                    code="split_in_batches_wrong_loop_output",
                    severity=FindingSeverity.ERROR,
                    node_name=name,
                    related_nodes=wrong_return_sources,
                    message=(
                        f"Split In Batches node '{name}' loops back from {wrong_label} via "
                        f"{', '.join(repr(source) for source in wrong_return_sources)}. For "
                        f"typeVersion {node.get('typeVersion')}, the per-item body must leave "
                        f"{_split_output_label(loop_output, 'loop')} and only that branch may "
                        f"return to '{name}'."
                    ),
                )
            )

        if loop_descendants and not sanctioned_return_sources:
            findings.append(
                AssuranceFinding(
                    code="split_in_batches_missing_loop_return",
                    severity=FindingSeverity.ERROR,
                    node_name=name,
                    related_nodes=tuple(sorted(loop_descendants)),
                    message=(
                        f"Split In Batches node '{name}' sends items into "
                        f"{_split_output_label(loop_output, 'loop')} but nothing returns to "
                        f"'{name}'. Connect the last per-item node back to the Split In Batches "
                        "node so the next batch can run."
                    ),
                )
            )

        if done_side_effects and not loop_side_effects and not sanctioned_return_sources:
            findings.append(
                AssuranceFinding(
                    code="split_in_batches_done_port_drives_body",
                    severity=FindingSeverity.ERROR,
                    node_name=name,
                    related_nodes=tuple(done_side_effects),
                    message=(
                        f"Split In Batches node '{name}' reaches side-effect node(s) "
                        f"{', '.join(repr(node_name) for node_name in done_side_effects)} from "
                        f"{_split_output_label(done_output, 'done')}. That branch runs only "
                        "after the loop finishes. Move the per-item action/write-back body to "
                        f"{_split_output_label(loop_output, 'loop')} instead."
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
    sanctioned_loopbacks = _sanctioned_split_loopback_edges(
        nodes_by_name, adjacency, normalized_connections
    )
    forward_adjacency = _without_edges(adjacency, sanctioned_loopbacks)
    findings = [
        *_graph_findings(nodes_by_name, adjacency, normalized_connections),
        *_if_findings(nodes_by_name),
        *_gmail_dataflow_findings(nodes_by_name, adjacency),
        *_side_effect_first_reference_findings(nodes_by_name, adjacency),
        *_sheets_matching_findings(nodes_by_name, adjacency),
        *_choreography_findings(nodes_by_name, forward_adjacency),
        *_split_in_batches_findings(nodes_by_name, adjacency, normalized_connections),
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
