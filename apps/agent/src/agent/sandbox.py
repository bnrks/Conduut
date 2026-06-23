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
