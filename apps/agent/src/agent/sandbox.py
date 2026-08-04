"""Sandbox workflow test engine.

Build sonrası, dışarıya gerçek etki göndermeyen bir test turu çalıştırır:
workflow'u klonlar, yan-etkili node'ları güvenli probe'larla değiştirir,
klonu webhook ile çalıştırır, deterministik kurallar + LLM yargısıyla değerlendirir
(hata / boş çıktı / LLM yargısı) ve klonu siler. Saf yardımcılar n8n'siz
unit-test edilebilir; gerçek LLM çağrısı ``_run_judge_llm`` arkasındadır.
"""

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel

from src import n8n_client
from src.agent.assurance import build_oracle_contract, workflow_fingerprint
from src.agent.sandbox_nodes import (
    ActionProbe,
    is_side_effect_node,
    replace_action_nodes_with_probes,
)
from src.agent.schemas import OracleContract, Postcondition, ProbeEvidence, WorkflowInputField
from src.agent.tools.common import _preview_value
from src.agent.tools.constants import _MANUAL_TRIGGER_TYPE, _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.execution import _summarize_execution
from src.agent.tools.workflow_helpers import _webhook_type_version
from src.config import settings

log = structlog.get_logger()
_current_n8n_client: ContextVar[Any | None] = ContextVar("sandbox_n8n_client", default=None)

_SAMPLE_BY_TYPE = {
    "email": "test@example.com",
    "textarea": "Sandbox test message body.",
    "string": "test value",
}
_SEMANTIC_NULLISH_FRAGMENT = re.compile(
    r"""
    ^(?:the\s+)?
    (?:
        (?:title|subject|message|body|summary|content|description|text|
        headline|article|name|result|output|response)
        \s*[:=\-]?\s*
    )?
    (?:
        undefined|
        null|
        none|
        n/?a|
        unavailable|
        not\s+available|
        missing(?:\s+(?:data|content|text|body|message|summary|title|headline|description))?|
        empty|
        no\s+(?:content|data|summary|description|text|body|message|title|headline|result|output)
        (?:\s+available)?
    )
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SEMANTIC_SEPARATOR = re.compile(r"[\n\r|/;]+")
_STRONG_PLACEHOLDER_LINE = re.compile(
    r"""
    ^\s*
    (?:
        \d+\.\s*|
        [-*]\s*|
        (?:title|subject|message|body|summary|content|description|text|headline|
        article|name|result|output|response|url|link|source|author|date)
        \s*[:=\-]\s*
    )
    (?:
        undefined|
        null|
        none|
        n/?a|
        unavailable|
        not\s+available|
        missing(?:\s+(?:data|content|text|body|message|summary|title|headline|description|url|link))?|
        empty|
        no\s+(?:content|data|summary|description|text|body|message|title|headline|result|output)
        (?:\s+available)?
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_UNRESOLVED_TEMPLATE_INTERPOLATION = re.compile(r"\{\{[^{}]+\}\}")
_RAW_N8N_EXPRESSION = re.compile(
    r"^\s*=?\s*(?:\$json(?:\b|[.\[])|\$\([^)]+\)(?:\.|\b|\[)).*$", re.IGNORECASE
)
_SIMPLE_JSON_FIELD_EXPR = re.compile(
    r"""
    ^\s*
    (?:
        =\s*\{\{\s*(?P<braced>\$json(?:\s*(?:\.|\?\.)\s*[A-Za-z_][A-Za-z0-9_]*|\s*\[\s*['"][^'"]+['"]\s*\]))\s*\}\}|
        (?P<raw>\$json(?:\s*(?:\.|\?\.)\s*[A-Za-z_][A-Za-z0-9_]*|\s*\[\s*['"][^'"]+['"]\s*\]))
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_JSON_FIELD_SUFFIX = re.compile(
    r"""
    ^\$json
    (?:
        \s*(?:\.|\?\.)\s*(?P<dot>[A-Za-z_][A-Za-z0-9_]*)|
        \s*\[\s*['"](?P<bracket>[^'"]+)['"]\s*\]
    )
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


@contextmanager
def use_n8n_client(n8n: Any):
    token = _current_n8n_client.set(n8n)
    try:
        yield
    finally:
        _current_n8n_client.reset(token)


def _resolve_n8n(n8n: Any | None):
    return n8n or _current_n8n_client.get() or n8n_client


_STATUS_CODE_EXPR = re.compile(
    r"\$json(?:\s*(?:\.|\?\.)\s*statusCode|\s*\[\s*['\"]statusCode['\"]\s*\])",
    re.IGNORECASE,
)


def _sample_input_for_schema(input_schema: list[WorkflowInputField]) -> dict[str, Any]:
    """Type-aware sample values so a runtime-input workflow is drivable in test."""

    return {field.name: _SAMPLE_BY_TYPE.get(field.type, "test value") for field in input_schema}


def _build_test_clone(
    workflow: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    """Deep-copy the workflow and make a webhook-drivable test clone.

    Returns ``(nodes, connections, webhook_path)`` or ``None`` when the workflow
    has no webhook/manual/schedule trigger Conduut can drive.
    A fresh uuid path is always assigned so the clone never clashes with the
    live workflow's webhook.
    """

    nodes = deepcopy(workflow.get("nodes") or [])
    connections = deepcopy(workflow.get("connections") or {})
    path = f"conduut-test-{uuid4().hex}"
    # A Respond to Webhook node only fires with responseMode=responseNode; forcing
    # lastNode here makes n8n reject the test run as "Unused Respond to Webhook".
    response_mode = (
        "responseNode"
        if any(
            isinstance(n, dict) and n.get("type") == "n8n-nodes-base.respondToWebhook"
            for n in nodes
        )
        else "lastNode"
    )

    webhook = next(
        (n for n in nodes if isinstance(n, dict) and n.get("type") == _WEBHOOK_TRIGGER_TYPE),
        None,
    )
    if webhook is not None:
        params = webhook.setdefault("parameters", {})
        params["httpMethod"] = "POST"
        params["multipleMethods"] = False
        params["responseMode"] = response_mode
        params["path"] = path
        return nodes, connections, path

    convertible = next(
        (
            n
            for n in nodes
            if isinstance(n, dict)
            and n.get("type") in {_MANUAL_TRIGGER_TYPE, "n8n-nodes-base.scheduleTrigger"}
        ),
        None,
    )
    if convertible is not None:
        convertible["type"] = _WEBHOOK_TRIGGER_TYPE
        convertible["typeVersion"] = _webhook_type_version()
        convertible["webhookId"] = uuid4().hex
        convertible["parameters"] = {
            "httpMethod": "POST",
            "path": path,
            "responseMode": response_mode,
            "options": {},
        }
        return nodes, connections, path

    return None


def _node_output_items(run_data: dict[str, Any], node_name: str) -> list[Any]:
    runs = run_data.get(node_name)
    if not isinstance(runs, list) or not runs:
        return []
    latest = runs[-1] if isinstance(runs[-1], dict) else {}
    data = latest.get("data") if isinstance(latest, dict) else None
    main = data.get("main") if isinstance(data, dict) else None
    items: list[Any] = []
    if isinstance(main, list):
        for output in main:
            if not isinstance(output, list):
                continue
            for item in output:
                if isinstance(item, dict) and "json" in item:
                    items.append(item.get("json"))
                else:
                    items.append(item)
    return items


def _node_output_items_for_index(
    run_data: dict[str, Any], node_name: str, output_index: int
) -> list[Any]:
    runs = run_data.get(node_name)
    if not isinstance(runs, list) or not runs:
        return []
    latest = runs[-1] if isinstance(runs[-1], dict) else {}
    data = latest.get("data") if isinstance(latest, dict) else None
    main = data.get("main") if isinstance(data, dict) else None
    if not isinstance(main, list) or output_index >= len(main):
        return []
    output = main[output_index]
    if not isinstance(output, list):
        return []
    items: list[Any] = []
    for item in output:
        if isinstance(item, dict) and "json" in item:
            items.append(item.get("json"))
        else:
            items.append(item)
    return items


def _node_output_items_for_index_all_runs(
    run_data: dict[str, Any], node_name: str, output_index: int
) -> list[Any]:
    runs = run_data.get(node_name)
    if not isinstance(runs, list) or not runs:
        return []
    items: list[Any] = []
    for run in runs:
        data = run.get("data") if isinstance(run, dict) else None
        main = data.get("main") if isinstance(data, dict) else None
        if not isinstance(main, list) or output_index >= len(main):
            continue
        output = main[output_index]
        if not isinstance(output, list):
            continue
        for item in output:
            if isinstance(item, dict) and "json" in item:
                items.append(item.get("json"))
            else:
                items.append(item)
    return items


def _iter_main_groups(outputs: Any):
    main = outputs.get("main") if isinstance(outputs, dict) else None
    if isinstance(main, list):
        for group in main:
            if isinstance(group, list):
                yield group


def _main_edges(connections: dict[str, Any]) -> list[tuple[str, int, str]]:
    edges: list[tuple[str, int, str]] = []
    for source, outputs in (connections or {}).items():
        main = outputs.get("main") if isinstance(outputs, dict) else None
        if not isinstance(main, list):
            continue
        for output_index, group in enumerate(main):
            if not isinstance(group, list):
                continue
            for entry in group:
                if not isinstance(entry, dict) or not entry.get("node"):
                    continue
                if str(entry.get("type") or "main") != "main":
                    continue
                edges.append((str(source), output_index, str(entry["node"])))
    return edges


def _can_reach(adjacency: dict[str, set[str]], source: str, target: str) -> bool:
    pending = [source]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency.get(current, set()) - seen)
    return False


def _descendants_from(
    start_nodes: set[str] | list[str] | tuple[str, ...],
    adjacency: dict[str, set[str]],
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
        pending.extend(adjacency.get(current, set()) - descendants)
    return descendants


def _nearest_control_boundary_count(
    detail: dict[str, Any], clone_workflow: dict[str, Any], target_name: str
) -> int | None:
    """Return items on the nearest Filter/IF/Loop output feeding an action path."""

    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    nodes_by_name = {
        str(node.get("name")): node
        for node in clone_workflow.get("nodes") or []
        if isinstance(node, dict) and node.get("name")
    }
    reverse: dict[str, list[tuple[str, int]]] = {}
    for source, output_index, target in _main_edges(clone_workflow.get("connections") or {}):
        reverse.setdefault(target, []).append((source, output_index))

    pending: list[tuple[str, int]] = [(target_name, 0)]
    seen_distance: dict[str, int] = {}
    candidates: list[tuple[int, int]] = []
    while pending:
        current, distance = pending.pop(0)
        previous = seen_distance.get(current)
        if previous is not None and previous <= distance:
            continue
        seen_distance[current] = distance
        for source, output_index in reverse.get(current, []):
            node = nodes_by_name.get(source, {})
            if node.get("type") in {
                "n8n-nodes-base.filter",
                "n8n-nodes-base.if",
                "n8n-nodes-base.splitInBatches",
            }:
                count = len(_node_output_items_for_index_all_runs(run_data, source, output_index))
                candidates.append((distance + 1, count))
            pending.append((source, distance + 1))

    if not candidates:
        return None
    nearest = min(distance for distance, _count in candidates)
    return sum(count for distance, count in candidates if distance == nearest)


def _unreached_action_findings(
    detail: dict[str, Any],
    clone_workflow: dict[str, Any],
    records: list[dict[str, Any]],
    probes: list[ActionProbe],
) -> list[str]:
    """Reject a zero-record action when its nearest eligibility boundary had items."""

    recorded_nodes = {str(record.get("node") or "") for record in records}
    findings: list[str] = []
    for probe in probes:
        if not probe.covered or probe.name in recorded_nodes:
            continue
        eligible_count = _nearest_control_boundary_count(detail, clone_workflow, probe.name)
        if eligible_count is None or eligible_count == 0:
            continue
        findings.append(
            f"The action path to '{probe.name}' was not reached even though its nearest "
            f"eligibility boundary emitted {eligible_count} item(s)."
        )
    return findings


def _split_in_batches_findings(
    detail: dict[str, Any], clone_workflow: dict[str, Any], probes: list[ActionProbe]
) -> list[str]:
    """Validate Loop Over Items runtime routing and its required feedback edge."""

    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    edges = _main_edges(clone_workflow.get("connections") or {})
    adjacency: dict[str, set[str]] = {}
    for source, _output_index, target in edges:
        adjacency.setdefault(source, set()).add(target)
    probe_names = {probe.name for probe in probes}
    findings: list[str] = []

    for node in clone_workflow.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "n8n-nodes-base.splitInBatches":
            continue
        name = str(node.get("name") or "")
        try:
            version = float(node.get("typeVersion") or 1)
        except (TypeError, ValueError):
            version = 1
        if version >= 3:
            done_index, loop_index = 0, 1
        elif version >= 2:
            done_index, loop_index = 1, 0
        else:
            # v1 exposes only one main output and cannot be audited with v2/v3 semantics.
            continue

        output_targets: dict[int, list[str]] = {}
        for source, output_index, target in edges:
            if source == name:
                output_targets.setdefault(output_index, []).append(target)
        done_targets = output_targets.get(done_index, [])
        loop_targets = output_targets.get(loop_index, [])
        loop_items = _node_output_items_for_index_all_runs(run_data, name, loop_index)
        branch_adjacency = {
            source: {target for target in targets if target != name}
            for source, targets in adjacency.items()
        }

        def descendants(targets: list[str]) -> set[str]:
            found: set[str] = set()
            pending = list(targets)
            while pending:
                current = pending.pop()
                if current in found:
                    continue
                found.add(current)
                pending.extend(branch_adjacency.get(current, ()))
            return found

        loop_descendants = descendants(loop_targets)
        done_descendants = descendants(done_targets)
        feedback_sources = {
            source for source, _output_index, target in edges if target == name and source != name
        }
        shared_feedback_sources = sorted(feedback_sources & loop_descendants & done_descendants)
        valid_feedback_sources = feedback_sources & loop_descendants - done_descendants

        def reaches_probe(targets: list[str]) -> bool:
            return any(
                _can_reach(adjacency, target, probe_name)
                for target in targets
                for probe_name in probe_names
            )

        done_drives_action = reaches_probe(done_targets)
        loop_drives_action = reaches_probe(loop_targets)
        if done_drives_action and not loop_drives_action:
            findings.append(
                f"Loop Over Items node '{name}' routes its action body from the 'done' "
                f"output (index {done_index}) instead of the 'loop' output "
                f"(index {loop_index})."
            )
        if loop_items and not loop_targets:
            findings.append(
                f"Loop Over Items node '{name}' emitted {len(loop_items)} item(s) on its "
                f"'loop' output (index {loop_index}), but that output has no downstream path."
            )
        if shared_feedback_sources:
            findings.append(
                f"Loop Over Items node '{name}' returns through "
                f"{', '.join(repr(source) for source in shared_feedback_sources)}, which is "
                "reachable from both the 'loop' and 'done' outputs. Keep the feedback path "
                "exclusive to the loop body."
            )
        if loop_drives_action and not valid_feedback_sources:
            findings.append(
                f"Loop Over Items node '{name}' has no feedback path from its loop body "
                "back to the same node, so only the first batch can be processed."
            )
    return findings


def _upstream_source_names(connections: dict[str, Any], target_name: str) -> list[str]:
    sources: list[str] = []
    for source, outputs in (connections or {}).items():
        for group in _iter_main_groups(outputs):
            for entry in group:
                if isinstance(entry, dict) and entry.get("node") == target_name:
                    sources.append(str(source))
                    break
    return sources


def _non_blank(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _items_are_empty(items: list[Any]) -> bool:
    for item in items:
        if isinstance(item, dict):
            if any(_non_blank(value) for value in item.values()):
                return False
        elif _non_blank(item):
            return False
    return True


def _probe_records(detail: dict[str, Any], probes: list[ActionProbe]) -> list[dict[str, Any]]:
    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    records: list[dict[str, Any]] = []
    for probe in probes:
        for item in _node_output_items(run_data, probe.name):
            if not isinstance(item, dict):
                continue
            payload = item.get("__conduut_probe")
            if isinstance(payload, dict):
                records.append({"node": probe.name, "covered": probe.covered, **payload})
            elif isinstance(payload, str) and payload:
                record: dict[str, Any] = {
                    "node": probe.name,
                    "covered": probe.covered,
                    "kind": payload,
                }
                if payload == "gmail_send":
                    for field in ("target", "subject", "message", "email_type"):
                        record[field] = item.get(f"__conduut_probe_{field}")
                elif payload == "sheets_update":
                    columns: list[str] = []
                    values: dict[str, Any] = {}
                    index = 0
                    while True:
                        key_name = f"__conduut_probe_matching_key_{index}"
                        value_name = f"__conduut_probe_matching_value_{index}"
                        if key_name not in item:
                            break
                        column = str(item.get(key_name) or "")
                        if column:
                            columns.append(column)
                            values[column] = item.get(value_name)
                        index += 1
                    record["matching_columns"] = columns
                    record["matching_values"] = values
                    record["values"] = {
                        str(key): value
                        for key, value in item.items()
                        if not str(key).startswith("__conduut_probe")
                    }
                elif payload == "sheets_append":
                    raw_columns = item.get("__conduut_probe_columns")
                    try:
                        parsed_columns = json.loads(str(raw_columns or "[]"))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        parsed_columns = []
                    columns = (
                        [str(column) for column in parsed_columns if str(column).strip()]
                        if isinstance(parsed_columns, list)
                        else []
                    )
                    if not columns:
                        columns = [
                            str(key) for key in item if not str(key).startswith("__conduut_probe")
                        ]
                    record["columns"] = columns
                    record["values"] = {column: item.get(column) for column in columns}
                records.append(record)
    return records


def _probe_findings(records: list[dict[str, Any]], probes: list[ActionProbe]) -> list[str]:
    findings: list[str] = []
    for record in records:
        kind = record.get("kind")
        node = record.get("node")
        if kind == "gmail_send":
            for field in ("target", "subject", "message"):
                if not _non_blank(record.get(field)):
                    findings.append(f"The action '{node}' resolved an empty {field} value.")
        elif kind == "sheets_update":
            columns = record.get("matching_columns")
            values = record.get("matching_values")
            if not isinstance(columns, list) or not columns:
                findings.append(f"The write-back '{node}' has no matching identity column.")
                continue
            if not isinstance(values, dict) or any(
                not _non_blank(values.get(str(column))) for column in columns
            ):
                findings.append(f"The write-back '{node}' resolved an empty identity value.")
        elif kind == "sheets_append":
            columns = record.get("columns")
            values = record.get("values")
            if not isinstance(columns, list) or not columns:
                findings.append(f"The append action '{node}' resolved no row columns.")
            elif not isinstance(values, dict) or not any(
                _non_blank(values.get(str(column))) for column in columns
            ):
                findings.append(f"The append action '{node}' resolved an empty row.")

        if kind == "gmail_send":
            for field in ("subject", "message"):
                if _looks_like_placeholder_business_output(record.get(field)):
                    findings.append(
                        f"The action '{node}' resolved placeholder-like {field} content "
                        "instead of real business output."
                    )

    for probe in probes:
        if probe.kind != "sheets_update" or not probe.covered:
            continue
        seen: set[tuple[str, ...]] = set()
        for record in (item for item in records if item.get("node") == probe.name):
            columns = record.get("matching_columns")
            values = record.get("matching_values")
            if not isinstance(columns, list) or not isinstance(values, dict):
                continue
            identity = tuple(str(values.get(str(column)) or "") for column in columns)
            if identity in seen:
                findings.append(
                    f"The write-back '{probe.name}' received duplicate identity values. "
                    "Choose a unique ID column before running real actions."
                )
                break
            seen.add(identity)

    action_count = sum(1 for item in records if item.get("kind") == "gmail_send")
    writeback_count = sum(1 for item in records if item.get("kind") == "sheets_update")
    has_action = any(probe.kind == "gmail_send" for probe in probes)
    has_writeback = any(probe.kind == "sheets_update" for probe in probes)
    if has_action and has_writeback and action_count != writeback_count:
        findings.append(
            "The action and write-back item counts do not match "
            f"({action_count} action, {writeback_count} write-back)."
        )
    return findings


def _probe_evidence(
    records: list[dict[str, Any]], probes: list[ActionProbe]
) -> list[ProbeEvidence]:
    evidence: list[ProbeEvidence] = []
    probe_lookup = {probe.name: probe for probe in probes}
    for record in records:
        node_name = str(record.get("node") or "")
        probe = probe_lookup.get(node_name)
        kind = str(record.get("kind") or "")
        values = record.get("values") if isinstance(record.get("values"), dict) else {}
        matching_values = (
            record.get("matching_values") if isinstance(record.get("matching_values"), dict) else {}
        )
        evidence.append(
            ProbeEvidence(
                nodeName=node_name,
                kind=kind,
                covered=probe.covered if probe else bool(record.get("covered")),
                target=_mask_target(record.get("target")) if kind == "gmail_send" else None,
                subject=str(record.get("subject") or "")[:160] if kind == "gmail_send" else None,
                columns=list(record.get("columns") or []),
                matchingColumns=list(record.get("matching_columns") or []),
                itemCount=1,
                rowEmpty=_items_are_empty([values]) if kind == "sheets_append" else None,
                identityMissing=(
                    not bool(record.get("matching_columns")) if kind == "sheets_update" else None
                ),
                identityEmpty=(
                    any(not _non_blank(value) for value in matching_values.values())
                    if kind == "sheets_update" and matching_values
                    else None
                ),
            )
        )
    return evidence


def _looks_like_placeholder_business_output(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    fragments = [fragment.strip(" \t-:,.()[]{}") for fragment in _SEMANTIC_SEPARATOR.split(text)]
    fragments = [fragment for fragment in fragments if fragment]
    if not fragments:
        return False
    placeholder_fragments = [
        fragment
        for fragment in fragments
        if _SEMANTIC_NULLISH_FRAGMENT.fullmatch(re.sub(r"\s+", " ", fragment.strip()))
    ]
    return bool(placeholder_fragments) and len(placeholder_fragments) == len(fragments)


def _ancestor_source_names(connections: dict[str, Any], target_name: str) -> list[str]:
    pending = list(_upstream_source_names(connections, target_name))
    seen: set[str] = set()
    ordered: list[str] = []
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
        pending.extend(_upstream_source_names(connections, name))
    return ordered


def _iter_text_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_text_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_text_values(nested)


def _strong_placeholder_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    normalized = text.replace("\r", "\n")
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if _UNRESOLVED_TEMPLATE_INTERPOLATION.search(line):
            fragments.append(line[:160])
            continue
        if _RAW_N8N_EXPRESSION.fullmatch(line):
            fragments.append(line[:160])
            continue
        if _STRONG_PLACEHOLDER_LINE.fullmatch(line):
            fragments.append(line[:160])
    return fragments


def _upstream_semantic_findings(
    detail: dict[str, Any],
    clone_workflow: dict[str, Any],
    probes: list[ActionProbe],
) -> list[str]:
    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    connections = clone_workflow.get("connections") or {}
    findings: list[str] = []
    for probe in probes:
        if not probe.covered:
            continue
        ancestor_names = _ancestor_source_names(connections, probe.name)
        seen_fragments: list[tuple[str, str]] = []
        for ancestor in ancestor_names:
            for item in _node_output_items(run_data, ancestor):
                for text in _iter_text_values(item):
                    for fragment in _strong_placeholder_fragments(text):
                        seen_fragments.append((ancestor, fragment))
                        if len(seen_fragments) >= 3:
                            break
                    if len(seen_fragments) >= 3:
                        break
                if len(seen_fragments) >= 3:
                    break
            if len(seen_fragments) >= 3:
                break
        if seen_fragments:
            affected_nodes = ", ".join(dict.fromkeys(node for node, _ in seen_fragments))
            findings.append(
                f"The action '{probe.name}' is fed by upstream placeholder or unresolved content "
                f"from step(s) {affected_nodes}. Real business content is missing before the "
                "side effect."
            )
    return findings


def _identity_preflight_findings(
    detail: dict[str, Any],
    clone_workflow: dict[str, Any],
    records: list[dict[str, Any]],
    probes: list[ActionProbe],
) -> list[str]:
    """Prove update identity uniqueness against the full upstream read dataset."""

    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    connections = clone_workflow.get("connections") or {}
    nodes_by_name = {
        str(node.get("name")): node
        for node in clone_workflow.get("nodes") or []
        if isinstance(node, dict) and node.get("name")
    }
    findings: list[str] = []
    for probe in probes:
        if probe.kind != "sheets_update" or not probe.covered:
            continue
        matching_columns: list[str] = []
        for record in records:
            if record.get("node") == probe.name and isinstance(
                record.get("matching_columns"), list
            ):
                matching_columns = [
                    str(column) for column in record["matching_columns"] if str(column).strip()
                ]
                break
        if not matching_columns:
            continue

        pending = _upstream_source_names(connections, probe.name)
        seen_nodes: set[str] = set()
        read_nodes: list[str] = []
        while pending:
            name = pending.pop()
            if name in seen_nodes:
                continue
            seen_nodes.add(name)
            node = nodes_by_name.get(name, {})
            parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
            if node.get("type") == "n8n-nodes-base.googleSheets" and str(
                parameters.get("operation") or ""
            ).lower() in {"read", "get", "getall"}:
                read_nodes.append(name)
            pending.extend(_upstream_source_names(connections, name))

        if not read_nodes:
            findings.append(
                f"The write-back '{probe.name}' has no safe upstream dataset from which "
                "identity uniqueness can be verified. Ask the user to select or add a unique "
                "ID field before running real actions."
            )
            continue

        source_items: list[dict[str, Any]] = []
        for read_node in read_nodes:
            source_items.extend(
                item for item in _node_output_items(run_data, read_node) if isinstance(item, dict)
            )
        if not source_items:
            continue

        identities: set[tuple[str, ...]] = set()
        invalid = False
        for item in source_items:
            identity = tuple(str(item.get(column) or "").strip() for column in matching_columns)
            if any(not part for part in identity):
                findings.append(
                    f"The upstream dataset for write-back '{probe.name}' contains an empty "
                    "identity value. Choose a complete unique ID field before running actions."
                )
                invalid = True
                break
            if identity in identities:
                findings.append(
                    f"The upstream dataset for write-back '{probe.name}' contains duplicate "
                    "identity values. Email, name, and other business fields are not assumed "
                    "unique; choose or add a dedicated ID field."
                )
                invalid = True
                break
            identities.add(identity)
        if invalid:
            continue
    return findings


def _mask_target(value: Any) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return "***" if text else ""
    local, domain = text.rsplit("@", 1)
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


def _preview_actions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for record in records[:5]:
        kind = str(record.get("kind") or "")
        if kind == "gmail_send":
            preview.append(
                {
                    "kind": kind,
                    "node": str(record.get("node") or ""),
                    "target": _mask_target(record.get("target")),
                    "subject": str(record.get("subject") or "")[:160],
                    "message": str(record.get("message") or "")[:500],
                }
            )
        elif kind == "sheets_update":
            preview.append(
                {
                    "kind": kind,
                    "node": str(record.get("node") or ""),
                    "matching_columns": list(record.get("matching_columns") or []),
                }
            )
        elif kind == "sheets_append":
            preview.append(
                {
                    "kind": kind,
                    "node": str(record.get("node") or ""),
                    "columns": list(record.get("columns") or []),
                }
            )
    return preview


def _simple_field_reference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _SIMPLE_JSON_FIELD_EXPR.match(value.strip())
    if match is None:
        return None
    expression = (match.group("braced") or match.group("raw") or "").strip()
    suffix = _JSON_FIELD_SUFFIX.match(expression)
    if suffix is None:
        return None
    return (suffix.group("dot") or suffix.group("bracket") or "").strip() or None


def _rule_references_status_code(rule: dict[str, Any]) -> bool:
    left_value = rule.get("leftValue")
    return isinstance(left_value, str) and bool(_STATUS_CODE_EXPR.search(left_value))


def _node_references_status_code(node: dict[str, Any]) -> bool:
    if str(node.get("type") or "") not in {
        "n8n-nodes-base.if",
        "n8n-nodes-base.filter",
    }:
        return False
    parameters = node.get("parameters")
    conditions = parameters.get("conditions") if isinstance(parameters, dict) else None
    rules = conditions.get("conditions") if isinstance(conditions, dict) else None
    return isinstance(rules, list) and any(
        isinstance(rule, dict) and _rule_references_status_code(rule) for rule in rules
    )


def _bool_parameter(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def _nested_mapping(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _http_request_response_guards(node: dict[str, Any]) -> tuple[bool, bool, bool]:
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        return False, False, False
    response_options = _nested_mapping(parameters, "options", "response", "response")
    full_response = _bool_parameter(response_options.get("fullResponse"))
    never_error = _bool_parameter(response_options.get("neverError"))
    continue_regular_output = str(node.get("onError") or "").strip()
    return full_response, never_error, continue_regular_output == "continueRegularOutput"


def _node_has_side_effect(node: dict[str, Any]) -> bool:
    return is_side_effect_node(node)


def _http_status_condition_findings(
    detail: dict[str, Any], clone_workflow: dict[str, Any]
) -> list[str]:
    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    nodes_by_name = {
        str(node.get("name")): node
        for node in clone_workflow.get("nodes") or []
        if isinstance(node, dict) and node.get("name")
    }
    reverse: dict[str, set[str]] = {}
    for source, _output_index, target in _main_edges(clone_workflow.get("connections") or {}):
        reverse.setdefault(target, set()).add(source)
    adjacency: dict[str, set[str]] = {}
    for source, _output_index, target in _main_edges(clone_workflow.get("connections") or {}):
        adjacency.setdefault(source, set()).add(target)

    findings: list[str] = []
    seen: set[str] = set()
    for node_name, node in nodes_by_name.items():
        if not _node_references_status_code(node):
            continue

        pending = list(reverse.get(node_name, ()))
        visited: set[str] = set()
        http_sources: set[str] = set()
        while pending:
            source = pending.pop()
            if source in visited:
                continue
            visited.add(source)
            source_node = nodes_by_name.get(source, {})
            if source_node.get("type") == "n8n-nodes-base.httpRequest":
                http_sources.add(source)
                continue
            pending.extend(reverse.get(source, ()))

        descendant_nodes = _descendants_from(
            adjacency.get(node_name, ()),
            adjacency,
            stop_at=node_name,
        )
        drives_side_effect = any(
            descendant != node_name and _node_has_side_effect(nodes_by_name.get(descendant, {}))
            for descendant in descendant_nodes
        )

        for http_name in sorted(http_sources):
            http_node = nodes_by_name.get(http_name, {})
            full_response, never_error, continue_output = _http_request_response_guards(http_node)
            if not full_response:
                finding = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}' via "
                    "$json.statusCode, but parameters.options.response.response.fullResponse is "
                    "false. Enable 'Include Response Headers and Status' so the branch reads the "
                    "real HTTP status."
                )
                if finding not in seen:
                    seen.add(finding)
                    findings.append(finding)
            if not never_error:
                finding = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}' via "
                    "$json.statusCode, but parameters.options.response.response.neverError is "
                    "false. Enable 'Never Error' so non-2xx HTTP responses still emit items for "
                    "the downstream condition."
                )
                if finding not in seen:
                    seen.add(finding)
                    findings.append(finding)
            if drives_side_effect and not continue_output:
                finding = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}', whose "
                    "downstream path reaches a side-effect node, but node.onError is not "
                    "'continueRegularOutput'. Enable top-level onError=continueRegularOutput so "
                    "connection and timeout failures also reach the handler branch."
                )
                if finding not in seen:
                    seen.add(finding)
                    findings.append(finding)

            source_items = [
                item for item in _node_output_items(run_data, http_name) if isinstance(item, dict)
            ]
            if source_items and not any("statusCode" in item for item in source_items):
                finding = (
                    f"HTTP Request node '{http_name}' feeds condition node '{node_name}' via "
                    "$json.statusCode, but the sandbox output had no statusCode field. The "
                    "workflow is branching on a value that the HTTP node did not emit."
                )
                if finding not in seen:
                    seen.add(finding)
                    findings.append(finding)
    return findings


def _simple_if_equals_rule(node: dict[str, Any]) -> tuple[str, str, bool] | None:
    if str(node.get("type") or "") not in {
        "n8n-nodes-base.if",
        "n8n-nodes-base.filter",
    }:
        return None
    parameters = node.get("parameters")
    conditions = parameters.get("conditions") if isinstance(parameters, dict) else None
    rules = conditions.get("conditions") if isinstance(conditions, dict) else None
    if not isinstance(rules, list) or len(rules) != 1:
        return None
    rule = rules[0]
    if not isinstance(rule, dict):
        return None
    operator = rule.get("operator")
    if not isinstance(operator, dict):
        return None
    if (
        str(operator.get("type") or "").strip().lower() != "string"
        or str(operator.get("operation") or "").strip().lower() != "equals"
    ):
        return None
    field = _simple_field_reference(rule.get("leftValue"))
    if not field:
        return None
    expected = rule.get("rightValue")
    if not isinstance(expected, str):
        return None
    if "{{" in expected or _RAW_N8N_EXPRESSION.fullmatch(expected):
        return None
    options = conditions.get("options") if isinstance(conditions.get("options"), dict) else {}
    case_sensitive = options.get("caseSensitive") is not False
    return field, expected, case_sensitive


def _string_value_matches(actual: Any, expected: str, *, case_sensitive: bool) -> bool | None:
    if actual is None:
        return False
    if not isinstance(actual, str):
        return None
    left = actual
    right = expected
    if not case_sensitive:
        left = left.casefold()
        right = right.casefold()
    return left == right


def _simple_if_predicate_findings(
    detail: dict[str, Any], clone_workflow: dict[str, Any]
) -> list[str]:
    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    findings: list[str] = []
    for node in clone_workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        rule = _simple_if_equals_rule(node)
        if rule is None:
            continue
        field, expected, case_sensitive = rule
        node_name = str(node.get("name") or "")
        true_items = _node_output_items_for_index(run_data, node_name, 0)
        false_items = _node_output_items_for_index(run_data, node_name, 1)
        true_results = [
            _string_value_matches(item.get(field), expected, case_sensitive=case_sensitive)
            for item in true_items
            if isinstance(item, dict)
        ]
        false_results = [
            _string_value_matches(item.get(field), expected, case_sensitive=case_sensitive)
            for item in false_items
            if isinstance(item, dict)
        ]
        true_contradiction = any(result is False for result in true_results)
        false_contradiction = any(result is True for result in false_results)
        if true_contradiction or false_contradiction:
            findings.append(
                f"IF node '{node_name}' produced branch output that contradicts its simple "
                f"equals predicate on $json.{field}."
            )
    return findings


def _projected_status_loop_rerun(
    clone_workflow: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    action_count: int,
    writeback_count: int,
) -> tuple[bool, bool]:
    """Return (status_loop_detected, projected_no_action_verified)."""

    rules = [
        rule
        for node in clone_workflow.get("nodes") or []
        if isinstance(node, dict)
        for rule in [_simple_if_equals_rule(node)]
        if rule is not None
    ]
    writebacks = [record for record in records if record.get("kind") == "sheets_update"]
    if not rules or not writebacks:
        return False, False
    relevant = False
    for field_name, expected, case_sensitive in rules:
        changed_values: list[Any] = []
        for record in writebacks:
            values = record.get("values")
            if isinstance(values, dict) and field_name in values:
                changed_values.append(values.get(field_name))
        if not changed_values:
            continue
        relevant = True
        if any(
            _string_value_matches(value, expected, case_sensitive=case_sensitive) is not False
            for value in changed_values
        ):
            return True, False
    verified = (
        relevant
        and action_count > 0
        and action_count == writeback_count
        and len(writebacks) == writeback_count
    )
    return relevant, verified


def _check_empty_outputs(
    detail: dict[str, Any], clone_workflow: dict[str, Any], neutralized: list[str]
) -> list[str]:
    """For each neutralized action node, flag when its upstream produced no data.

    The action node is disabled (skipped), so its intended input is the output of
    the node(s) wired into it. If all of those produced empty/blank items, the
    action's result would be blank — the classic "empty mail" failure.
    """

    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    connections = clone_workflow.get("connections") or {}
    findings: list[str] = []
    for name in neutralized:
        sources = _upstream_source_names(connections, name)
        if not sources:
            continue
        source_items = [_node_output_items(run_data, src) for src in sources]
        # A filter legitimately producing zero items is a clean no-op. Flag only
        # when items reached the action boundary but every field is blank.
        if any(source_items) and all(_items_are_empty(items) for items in source_items):
            findings.append(
                f"The step '{name}' would receive empty data, so its result would be blank."
            )
    return findings


class JudgeVerdict(BaseModel):
    ok: bool = True
    issue: str = ""


_JUDGE_INSTRUCTIONS = (
    "You judge whether an automation would produce a meaningful, non-empty, "
    "correct-looking result. You are given the automation's purpose and the action "
    "steps that would run (their config and the data that would feed them). Set "
    "ok=false with a short issue when a key value would be empty, an expression "
    "clearly did not resolve, or the data shape is wrong (e.g. an array where a "
    "single value is expected). If the purpose implies formatted or styled delivery "
    "(for example a digest, newsletter, or richly formatted email), require the "
    "delivery format to match; plain text or raw Markdown is not correct when the "
    "workflow is supposed to send rendered HTML/styled output. Otherwise ok=true "
    "with an empty issue."
)

_judge_agent = None


def _build_judge_agent():
    from pydantic_ai import Agent

    from src.agent.provider_factory import build_model
    from src.config import key_for_provider

    model = build_model("google", settings.research_model, key_for_provider("google"))
    return Agent(model, output_type=JudgeVerdict, instructions=_JUDGE_INSTRUCTIONS)


async def _run_judge_llm(prompt: str) -> JudgeVerdict:
    global _judge_agent
    if _judge_agent is None:
        _judge_agent = _build_judge_agent()
    result = await _judge_agent.run(prompt)
    return result.output


def _action_summaries(
    detail: dict[str, Any], clone_workflow: dict[str, Any], neutralized: list[str]
) -> list[dict[str, Any]]:
    run_data = (((detail.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    connections = clone_workflow.get("connections") or {}
    nodes_by_name = {
        str(node.get("name")): node
        for node in clone_workflow.get("nodes") or []
        if isinstance(node, dict)
    }
    summaries: list[dict[str, Any]] = []
    for name in neutralized:
        node = nodes_by_name.get(name, {})
        would_be: list[Any] = []
        for src in _upstream_source_names(connections, name):
            would_be.extend(_node_output_items(run_data, src))
        summaries.append(
            {
                "name": name,
                "type": str(node.get("type") or ""),
                "params": _preview_value(node.get("parameters") or {}),
                "would_be_input": _preview_value(would_be[:3]),
            }
        )
    return summaries


def _judge_prompt(intent: str, action_summaries: list[dict[str, Any]]) -> str:
    payload = json.dumps(action_summaries, ensure_ascii=False, default=str)[:4000]
    return (
        f"Automation purpose: {intent or 'unknown'}\n\n"
        "Action steps that would run (config + data that would feed them):\n"
        f"{payload}"
    )


async def _run_judge(intent: str, action_summaries: list[dict[str, Any]]) -> JudgeVerdict:
    return await _run_judge_llm(_judge_prompt(intent, action_summaries))


@dataclass
class SandboxTestResult:
    passed: bool
    skipped: bool = False
    status: str = "needs_attention"
    coverage: str = "none"
    oracle: OracleContract | None = None
    probe_evidence: list[ProbeEvidence] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    failed_node: str | None = None
    empty_fields: list[str] = field(default_factory=list)
    judge_issue: str | None = None
    execution_id: str | None = None
    eligible_count: int | None = None
    action_count: int | None = None
    writeback_count: int | None = None
    projected_second_run_eligible_count: int | None = None
    projected_second_run_action_count: int | None = None
    projected_second_run_writeback_count: int | None = None
    preview_actions: list[dict[str, Any]] = field(default_factory=list)


def _sandbox_rule_code(finding: str) -> str:
    lowered = finding.lower()
    if "duplicate" in lowered and "identity" in lowered:
        return "identity_duplicate"
    if "empty identity" in lowered or "identity value" in lowered:
        return "identity_empty"
    if "no matching identity" in lowered or "no safe upstream dataset" in lowered:
        return "identity_missing"
    if "counts do not match" in lowered:
        return "count_mismatch"
    if "empty" in lowered or "blank" in lowered:
        return "required_field_empty"
    if "contract" in lowered or "coverage" in lowered:
        return "contract_coverage_missing"
    if "execution" in lowered:
        return "execution_failed"
    return "semantic_quality_finding"


def _log_sandbox_result(workflow: dict[str, Any], result: SandboxTestResult) -> None:
    log.info(
        "sandbox_test_finished",
        workflow_id=str(workflow.get("id") or ""),
        fingerprint=workflow_fingerprint(workflow),
        passed=result.passed,
        status=result.status,
        coverage=result.coverage,
        skipped=result.skipped,
        failed_node=result.failed_node,
        eligible_count=result.eligible_count,
        action_count=result.action_count,
        writeback_count=result.writeback_count,
        rule_codes=sorted({_sandbox_rule_code(finding) for finding in result.findings}),
    )


async def _evaluate_sandbox_run(
    detail: dict[str, Any], clone_workflow: dict[str, Any], probes: list[ActionProbe], intent: str
) -> SandboxTestResult:
    oracle = build_oracle_contract(clone_workflow, context_source="exact")
    summary = _summarize_execution(detail, workflow=clone_workflow)
    if summary.status in {"error", "failed"} or summary.error:
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage="full" if all(probe.covered for probe in probes) else "partial",
            oracle=oracle,
            findings=[summary.error or "Workflow execution failed."],
            failed_node=summary.failedNode,
            execution_id=summary.executionId,
        )

    action_names = [probe.name for probe in probes]
    empty = _check_empty_outputs(detail, clone_workflow, action_names)
    if empty:
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage="full" if all(probe.covered for probe in probes) else "partial",
            oracle=oracle,
            findings=empty,
            empty_fields=empty,
            execution_id=summary.executionId,
        )

    # Return-only / read-only workflows (fetch-and-return, lookups) have no
    # side-effect action node to neutralize, so the action judge has nothing to
    # assess and would falsely fail them ("no action steps"). The run succeeded
    # and no upstream was flagged empty above, so the data path works: pass.
    if not probes:
        return SandboxTestResult(
            passed=True,
            status="passed",
            coverage="full",
            oracle=oracle,
            execution_id=summary.executionId,
        )

    records = _probe_records(detail, probes)
    probe_evidence = _probe_evidence(records, probes)
    deterministic_findings = [
        *_probe_findings(records, probes),
        *_identity_preflight_findings(detail, clone_workflow, records, probes),
        *_http_status_condition_findings(detail, clone_workflow),
        *_simple_if_predicate_findings(detail, clone_workflow),
        *_upstream_semantic_findings(detail, clone_workflow, probes),
        *_unreached_action_findings(detail, clone_workflow, records, probes),
        *_split_in_batches_findings(detail, clone_workflow, probes),
    ]
    action_count = sum(1 for item in records if item.get("kind") in {"gmail_send", "sheets_append"})
    writeback_count = sum(1 for item in records if item.get("kind") == "sheets_update")
    boundary_counts = [
        count
        for probe in probes
        if (count := _nearest_control_boundary_count(detail, clone_workflow, probe.name))
        is not None
    ]
    eligible_count = max([action_count, writeback_count, *boundary_counts])
    status_loop, projected_no_action = _projected_status_loop_rerun(
        clone_workflow,
        records,
        action_count=action_count,
        writeback_count=writeback_count,
    )
    if status_loop:
        oracle = oracle.model_copy(
            update={
                "expectedPostconditions": [
                    *oracle.expectedPostconditions,
                    Postcondition(
                        code="rerun_no_action",
                        description="Projected second run produces no action or write-back",
                        status="verified" if projected_no_action else "failed",
                    ),
                ]
            }
        )
        if not projected_no_action:
            deterministic_findings.append(
                "Projected second-run idempotency failed: the write-back does not make "
                "the filter predicate ineligible."
            )
    coverage = "full" if all(probe.covered for probe in probes) else "partial"
    if deterministic_findings:
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage=coverage,
            oracle=oracle,
            probe_evidence=probe_evidence,
            findings=deterministic_findings,
            execution_id=summary.executionId,
            eligible_count=eligible_count,
            action_count=action_count,
            writeback_count=writeback_count,
            preview_actions=_preview_actions(records),
        )
    if eligible_count == 0 and all(probe.covered for probe in probes):
        return SandboxTestResult(
            passed=True,
            status="no_action",
            coverage="full",
            oracle=oracle,
            probe_evidence=[],
            execution_id=summary.executionId,
            eligible_count=0,
            action_count=0,
            writeback_count=0,
            preview_actions=[],
        )
    if coverage == "partial":
        return SandboxTestResult(
            passed=True,
            status="partial_coverage",
            coverage="partial",
            oracle=oracle,
            probe_evidence=probe_evidence,
            findings=["Some action nodes do not yet have deterministic sandbox contracts."],
            execution_id=summary.executionId,
            eligible_count=eligible_count,
            action_count=action_count,
            writeback_count=writeback_count,
            preview_actions=_preview_actions(records),
        )

    return SandboxTestResult(
        passed=True,
        status="passed",
        coverage=coverage,
        oracle=oracle,
        probe_evidence=probe_evidence,
        execution_id=summary.executionId,
        eligible_count=eligible_count,
        action_count=action_count,
        writeback_count=writeback_count,
        projected_second_run_eligible_count=0 if projected_no_action else None,
        projected_second_run_action_count=0 if projected_no_action else None,
        projected_second_run_writeback_count=0 if projected_no_action else None,
        preview_actions=_preview_actions(records),
    )


async def run_sandbox_test(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_schema: list[WorkflowInputField],
    intent: str,
    input_payload: dict[str, Any] | None = None,
    n8n: Any | None = None,
) -> SandboxTestResult:
    n8n_ops = _resolve_n8n(n8n)
    name = str(workflow.get("name") or "Workflow")
    clone = _build_test_clone(workflow)
    if clone is None:
        result = SandboxTestResult(
            passed=False,
            skipped=True,
            findings=["No webhook/manual trigger to drive a safe test (e.g. schedule-only)."],
        )
        _log_sandbox_result(workflow, result)
        return result

    clone_nodes, clone_connections, path = clone
    probes = replace_action_nodes_with_probes(clone_nodes)
    sample = (
        dict(input_payload)
        if input_payload is not None
        else (_sample_input_for_schema(input_schema) or {"source": "conduut_test"})
    )

    created = await n8n_ops.create_workflow(
        name=f"[conduut-test] {name}"[:120],
        nodes=clone_nodes,
        connections=clone_connections,
    )
    clone_workflow = {
        "id": created.id,
        "name": created.name,
        "nodes": clone_nodes,
        "connections": clone_connections,
    }
    detail: dict[str, Any] | None = None
    try:
        await n8n_ops.activate_workflow(created.id)
        await n8n_ops.call_webhook(path, sample)
        executions = await n8n_ops.list_executions(workflow_id=created.id, limit=1)
        if executions:
            detail = await n8n_ops.get_execution_detail(executions[0].id)
    finally:
        try:
            await n8n_ops.delete_workflow(created.id)
        except Exception as exc:  # noqa: BLE001 - cleanup must never raise
            log.warning("sandbox_clone_delete_failed", clone_id=created.id, error=str(exc))

    if detail is None:
        result = SandboxTestResult(
            passed=False, skipped=True, findings=["The sandbox run produced no execution details."]
        )
        _log_sandbox_result(workflow, result)
        return result

    result = await _evaluate_sandbox_run(detail, clone_workflow, probes, intent)
    _log_sandbox_result(workflow, result)
    return result
