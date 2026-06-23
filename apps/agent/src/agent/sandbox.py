"""Sandbox workflow test engine.

Build sonrası, dışarıya gerçek etki göndermeyen bir test turu çalıştırır:
workflow'u klonlar, yan-etkili (aksiyon) node'larını ``disabled=true`` yaparak
nötralize eder, klonu webhook ile çalıştırır, 3 katmanlı değerlendirir
(hata / boş çıktı / LLM yargısı) ve klonu siler. Saf yardımcılar n8n'siz
unit-test edilebilir; gerçek LLM çağrısı ``_run_judge_llm`` arkasındadır.
"""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from src.agent.schemas import WorkflowInputField
from src.agent.tools.constants import _MANUAL_TRIGGER_TYPE, _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.workflow_helpers import _webhook_type_version

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
