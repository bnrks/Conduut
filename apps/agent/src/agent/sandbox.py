"""Sandbox workflow test engine.

Build sonrası, dışarıya gerçek etki göndermeyen bir test turu çalıştırır:
workflow'u klonlar, yan-etkili (aksiyon) node'larını ``disabled=true`` yaparak
nötralize eder, klonu webhook ile çalıştırır, 3 katmanlı değerlendirir
(hata / boş çıktı / LLM yargısı) ve klonu siler. Saf yardımcılar n8n'siz
unit-test edilebilir; gerçek LLM çağrısı ``_run_judge_llm`` arkasındadır.
"""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import structlog
from pydantic import BaseModel

from src import n8n_client
from src.agent.sandbox_nodes import neutralize_action_nodes
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


def _sample_input_for_schema(input_schema: list[WorkflowInputField]) -> dict[str, Any]:
    """Type-aware sample values so a runtime-input workflow is drivable in test."""

    return {field.name: _SAMPLE_BY_TYPE.get(field.type, "test value") for field in input_schema}


def _build_test_clone(
    workflow: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    """Deep-copy the workflow and make a webhook-drivable test clone.

    Returns ``(nodes, connections, webhook_path)`` or ``None`` when the workflow
    has no webhook/manual trigger Conduut can drive (e.g. schedule-only).
    A fresh uuid path is always assigned so the clone never clashes with the
    live workflow's webhook.
    """

    nodes = deepcopy(workflow.get("nodes") or [])
    connections = deepcopy(workflow.get("connections") or {})
    path = f"conduut-test-{uuid4().hex}"

    webhook = next(
        (n for n in nodes if isinstance(n, dict) and n.get("type") == _WEBHOOK_TRIGGER_TYPE),
        None,
    )
    if webhook is not None:
        params = webhook.setdefault("parameters", {})
        params["httpMethod"] = "POST"
        params["multipleMethods"] = False
        params["responseMode"] = "lastNode"
        params["path"] = path
        return nodes, connections, path

    manual = next(
        (n for n in nodes if isinstance(n, dict) and n.get("type") == _MANUAL_TRIGGER_TYPE),
        None,
    )
    if manual is not None:
        manual["type"] = _WEBHOOK_TRIGGER_TYPE
        manual["typeVersion"] = _webhook_type_version()
        manual["webhookId"] = uuid4().hex
        manual["parameters"] = {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "lastNode",
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
        if all(_items_are_empty(_node_output_items(run_data, src)) for src in sources):
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
    "single value is expected). Otherwise ok=true with an empty issue."
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
    findings: list[str] = field(default_factory=list)
    failed_node: str | None = None
    empty_fields: list[str] = field(default_factory=list)
    judge_issue: str | None = None
    execution_id: str | None = None


async def _evaluate_sandbox_run(
    detail: dict[str, Any], clone_workflow: dict[str, Any], neutralized: list[str], intent: str
) -> SandboxTestResult:
    summary = _summarize_execution(detail, workflow=clone_workflow)
    if summary.status in {"error", "failed"} or summary.error:
        return SandboxTestResult(
            passed=False,
            findings=[summary.error or "Workflow execution failed."],
            failed_node=summary.failedNode,
            execution_id=summary.executionId,
        )

    empty = _check_empty_outputs(detail, clone_workflow, neutralized)
    if empty:
        return SandboxTestResult(
            passed=False, findings=empty, empty_fields=empty, execution_id=summary.executionId
        )

    verdict = await _run_judge(intent, _action_summaries(detail, clone_workflow, neutralized))
    if not verdict.ok:
        return SandboxTestResult(
            passed=False,
            findings=[verdict.issue or "The result may not match the request."],
            judge_issue=verdict.issue or None,
            execution_id=summary.executionId,
        )

    return SandboxTestResult(passed=True, execution_id=summary.executionId)


async def run_sandbox_test(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_schema: list[WorkflowInputField],
    intent: str,
) -> SandboxTestResult:
    name = str(workflow.get("name") or "Workflow")
    clone = _build_test_clone(workflow)
    if clone is None:
        return SandboxTestResult(
            passed=False,
            skipped=True,
            findings=["No webhook/manual trigger to drive a safe test (e.g. schedule-only)."],
        )

    clone_nodes, clone_connections, path = clone
    neutralized = neutralize_action_nodes(clone_nodes)
    sample = _sample_input_for_schema(input_schema) or {"source": "conduut_test"}

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
        return SandboxTestResult(
            passed=False, skipped=True, findings=["The sandbox run produced no execution details."]
        )

    result = await _evaluate_sandbox_run(detail, clone_workflow, neutralized, intent)
    log.info(
        "sandbox_test_finished",
        workflow_id=str(workflow.get("id") or ""),
        passed=result.passed,
        skipped=result.skipped,
        failed_node=result.failed_node,
    )
    return result
