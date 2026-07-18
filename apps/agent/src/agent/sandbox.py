"""Sandbox workflow test engine.

Build sonrası, dışarıya gerçek etki göndermeyen bir test turu çalıştırır:
workflow'u klonlar, yan-etkili node'ları güvenli probe'larla değiştirir,
klonu webhook ile çalıştırır, deterministik kurallar + LLM yargısıyla değerlendirir
(hata / boş çıktı / LLM yargısı) ve klonu siler. Saf yardımcılar n8n'siz
unit-test edilebilir; gerçek LLM çağrısı ``_run_judge_llm`` arkasındadır.
"""

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel

from src import n8n_client
from src.agent.assurance import workflow_fingerprint
from src.agent.sandbox_nodes import ActionProbe, replace_action_nodes_with_probes
from src.agent.schemas import WorkflowInputField
from src.agent.tools.common import _preview_value
from src.agent.tools.constants import _MANUAL_TRIGGER_TYPE, _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.execution import _summarize_execution
from src.agent.tools.workflow_helpers import _webhook_type_version
from src.config import settings

log = structlog.get_logger()

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


def _iter_main_groups(outputs: Any):
    main = outputs.get("main") if isinstance(outputs, dict) else None
    if isinstance(main, list):
        for group in main:
            if isinstance(group, list):
                yield group


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
    return preview


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
    findings: list[str] = field(default_factory=list)
    failed_node: str | None = None
    empty_fields: list[str] = field(default_factory=list)
    judge_issue: str | None = None
    execution_id: str | None = None
    eligible_count: int | None = None
    action_count: int | None = None
    writeback_count: int | None = None
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
    summary = _summarize_execution(detail, workflow=clone_workflow)
    if summary.status in {"error", "failed"} or summary.error:
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage="full" if all(probe.covered for probe in probes) else "partial",
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
            passed=True, status="passed", coverage="full", execution_id=summary.executionId
        )

    records = _probe_records(detail, probes)
    deterministic_findings = [
        *_probe_findings(records, probes),
        *_identity_preflight_findings(detail, clone_workflow, records, probes),
        *_upstream_semantic_findings(detail, clone_workflow, probes),
    ]
    action_count = sum(1 for item in records if item.get("kind") == "gmail_send")
    writeback_count = sum(1 for item in records if item.get("kind") == "sheets_update")
    eligible_count = max(action_count, writeback_count)
    coverage = "full" if all(probe.covered for probe in probes) else "partial"
    if deterministic_findings:
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage=coverage,
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
            findings=["Some action nodes do not yet have deterministic sandbox contracts."],
            execution_id=summary.executionId,
            eligible_count=eligible_count,
            action_count=action_count,
            writeback_count=writeback_count,
            preview_actions=_preview_actions(records),
        )

    verdict = await _run_judge(intent, records[:6])
    if not verdict.ok:
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage=coverage,
            findings=[verdict.issue or "The result may not match the request."],
            judge_issue=verdict.issue or None,
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
        execution_id=summary.executionId,
        eligible_count=eligible_count,
        action_count=action_count,
        writeback_count=writeback_count,
        preview_actions=_preview_actions(records),
    )


async def run_sandbox_test(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_schema: list[WorkflowInputField],
    intent: str,
    input_payload: dict[str, Any] | None = None,
) -> SandboxTestResult:
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

    created = await n8n_client.create_workflow(
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
        await n8n_client.activate_workflow(created.id)
        await n8n_client.call_webhook(path, sample)
        executions = await n8n_client.list_executions(workflow_id=created.id, limit=1)
        if executions:
            detail = await n8n_client.get_execution_detail(executions[0].id)
    finally:
        try:
            await n8n_client.delete_workflow(created.id)
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
