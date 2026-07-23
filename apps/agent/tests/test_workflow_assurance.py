"""Focused coverage for Workflow Assurance V1 static invariants."""

from copy import deepcopy
from typing import Any

import pytest
from pydantic_ai import ModelRetry

from src.agent.assurance import (
    analyze_workflow_semantics,
    workflow_fingerprint,
    workflow_semantic_fingerprint,
)
from src.agent.schemas import WorkflowNode
from src.agent.tools.build_pipeline import _validated_runtime_workflow


def _node(name: str, node_type: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "type": node_type, "parameters": parameters or {}}


def _connections(*edges: tuple[str, str]) -> dict[str, Any]:
    connections: dict[str, Any] = {}
    for source, target in edges:
        groups = connections.setdefault(source, {"main": [[]]})["main"]
        groups[0].append({"node": target, "type": "main", "index": 0})
    return connections


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def _gmail(name: str = "Send Email") -> dict[str, Any]:
    return _node(
        name,
        "n8n-nodes-base.gmail",
        {
            "resource": "message",
            "operation": "send",
            "sendTo": "={{ $json.email }}",
            "subject": "Reminder",
            "message": "Hello",
        },
    )


def _sheets_update(match_value: str | None = "={{ $json.email }}") -> dict[str, Any]:
    value = {"status": "sent"}
    if match_value is not None:
        value["email"] = match_value
    return _node(
        "Update Status",
        "n8n-nodes-base.googleSheets",
        {
            "resource": "sheet",
            "operation": "update",
            "columns": {
                "mappingMode": "defineBelow",
                "matchingColumns": ["email"],
                "value": value,
            },
        },
    )


def test_trigger_back_edge_and_main_cycle_are_blocking():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Filter", "n8n-nodes-base.if"),
    ]
    report = analyze_workflow_semantics(
        nodes,
        _connections(("Webhook", "Filter"), ("Filter", "Webhook")),
    )

    assert {"trigger_back_edge", "main_flow_cycle"} <= _codes(report)
    assert all(finding.blocking for finding in report.findings)


def test_if_with_multiple_conditions_requires_explicit_combinator():
    conditions = {
        "conditions": [
            {
                "leftValue": "={{ $json.status }}",
                "operator": {"type": "string", "operation": "equals"},
                "rightValue": "pending",
            },
            {
                "leftValue": "={{ $json.sent }}",
                "operator": {"type": "string", "operation": "equals"},
                "rightValue": "no",
            },
        ]
    }
    missing = analyze_workflow_semantics(
        [_node("IF", "n8n-nodes-base.if", {"conditions": conditions})], {}
    )
    assert "if_combinator_missing" in _codes(missing)

    conditions["combinator"] = "and"
    valid = analyze_workflow_semantics(
        [_node("IF", "n8n-nodes-base.if", {"conditions": conditions})], {}
    )
    assert "if_combinator_missing" not in _codes(valid)


def test_gmail_send_blocks_unqualified_business_fields_in_immediate_downstream_node():
    report = analyze_workflow_semantics(
        [_gmail(), _sheets_update()],
        _connections(("Send Email", "Update Status")),
    )

    assert "gmail_output_field_unavailable" in _codes(report)
    assert "sheets_matching_key_not_live" in _codes(report)


def test_explicit_upstream_reference_survives_non_passthrough_gmail_boundary():
    update = _sheets_update("={{ $('Filter').item.json.email }}")
    report = analyze_workflow_semantics(
        [_node("Filter", "n8n-nodes-base.if"), _gmail(), update],
        _connections(("Filter", "Send Email"), ("Send Email", "Update Status")),
    )

    assert "gmail_output_field_unavailable" not in _codes(report)
    assert "sheets_matching_key_not_live" not in _codes(report)


def test_multi_item_ai_to_gmail_first_reference_is_blocked():
    gmail = _node(
        "Send Email",
        "n8n-nodes-base.gmail",
        {
            "resource": "message",
            "operation": "send",
            "sendTo": "={{ $json.email }}",
            "subject": "Reminder",
            "message": "={{ $('AI Agent').first().json.output }}",
        },
    )
    report = analyze_workflow_semantics(
        [
            _node("Webhook", "n8n-nodes-base.webhook"),
            _node("Read Rows", "n8n-nodes-base.googleSheets", {"operation": "read"}),
            _node("Filter", "n8n-nodes-base.if"),
            _node("AI Agent", "@n8n/n8n-nodes-langchain.agent"),
            gmail,
        ],
        _connections(
            ("Webhook", "Read Rows"),
            ("Read Rows", "Filter"),
            ("Filter", "AI Agent"),
            ("AI Agent", "Send Email"),
        ),
    )

    assert "side_effect_direct_first_reference" in _codes(report)


def test_all_first_references_on_side_effect_are_blocked():
    gmail = _node(
        "Send Email",
        "n8n-nodes-base.gmail",
        {
            "resource": "message",
            "operation": "send",
            "sendTo": "={{ $('AI Agent').first().json.email }}",
            "subject": "Reminder",
            "message": "={{ $('AI Agent').first().json.output }}",
        },
    )
    report = analyze_workflow_semantics(
        [
            _node("Webhook", "n8n-nodes-base.webhook"),
            _node("Read Rows", "n8n-nodes-base.googleSheets", {"operation": "read"}),
            _node("AI Agent", "@n8n/n8n-nodes-langchain.agent"),
            gmail,
        ],
        _connections(
            ("Webhook", "Read Rows"),
            ("Read Rows", "AI Agent"),
            ("AI Agent", "Send Email"),
        ),
    )

    assert "side_effect_direct_first_reference" in _codes(report)


def test_single_item_webhook_first_reference_is_not_flagged():
    gmail = _node(
        "Send Email",
        "n8n-nodes-base.gmail",
        {
            "resource": "message",
            "operation": "send",
            "sendTo": "person@example.com",
            "subject": "Reminder",
            "message": "={{ $('Webhook').first().json.body.message }}",
        },
    )
    report = analyze_workflow_semantics(
        [_node("Webhook", "n8n-nodes-base.webhook"), gmail],
        _connections(("Webhook", "Send Email")),
    )

    assert "side_effect_direct_first_reference" not in _codes(report)


def test_non_direct_singleton_first_reference_is_not_blocked():
    gmail = _node(
        "Send Email",
        "n8n-nodes-base.gmail",
        {
            "resource": "message",
            "operation": "send",
            "sendTo": "={{ $json.email }}",
            "subject": "={{ $('Load Config').first().json.subject }}",
            "message": "={{ $json.message }}",
        },
    )
    report = analyze_workflow_semantics(
        [
            _node("Webhook", "n8n-nodes-base.webhook"),
            _node("Load Config", "n8n-nodes-base.set"),
            _node("Prepare Rows", "n8n-nodes-base.code"),
            gmail,
        ],
        _connections(
            ("Webhook", "Load Config"),
            ("Load Config", "Prepare Rows"),
            ("Prepare Rows", "Send Email"),
        ),
    )

    assert "side_effect_direct_first_reference" not in _codes(report)


def test_sheets_matching_key_presence_and_shadow_liveness_are_reported():
    missing = _sheets_update(match_value=None)
    missing_report = analyze_workflow_semantics(
        [_node("Prepare", "n8n-nodes-base.code"), missing],
        _connections(("Prepare", "Update Status")),
    )
    assert "sheets_matching_value_missing" in _codes(missing_report)

    dynamic_report = analyze_workflow_semantics(
        [_node("Prepare", "n8n-nodes-base.code"), _sheets_update()],
        _connections(("Prepare", "Update Status")),
    )
    liveness = next(
        finding
        for finding in dynamic_report.findings
        if finding.code == "sheets_matching_key_liveness_unproven"
    )
    assert liveness.blocking is False


def test_writeback_before_action_is_rejected_and_plan_exposes_postconditions():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Read", "n8n-nodes-base.googleSheets", {"operation": "read"}),
        _sheets_update(),
        _gmail(),
    ]
    report = analyze_workflow_semantics(
        nodes,
        _connections(
            ("Webhook", "Read"),
            ("Read", "Update Status"),
            ("Update Status", "Send Email"),
        ),
    )

    assert "writeback_before_action" in _codes(report)
    assert report.plan.node_roles["Send Email"] == "action"
    assert report.plan.node_roles["Update Status"] == "writeback"
    assert report.plan.identity_fields["Update Status"] == ("email",)
    assert "action_count == writeback_count" in report.plan.cardinality_relations
    assert "every successful action has one write-back" in report.plan.expected_postconditions


def test_missing_contract_is_a_non_blocking_shadow_finding():
    report = analyze_workflow_semantics(
        [
            _node("Webhook", "n8n-nodes-base.webhook"),
            _node("Custom", "n8n-nodes-community.custom"),
        ],
        _connections(("Webhook", "Custom")),
    )

    finding = next(item for item in report.findings if item.code == "contract_coverage_missing")
    assert finding.node_name == "Custom"
    assert finding.blocking is False


def test_semantic_fingerprint_ignores_ui_ids_positions_and_timestamps():
    nodes = [
        {
            **_gmail(),
            "id": "node-a",
            "position": [100, 200],
            "webhookId": "hook-a",
            "updatedAt": "yesterday",
        }
    ]
    changed_metadata = deepcopy(nodes)
    changed_metadata[0].update(
        {
            "id": "node-b",
            "position": [900, 1000],
            "webhookId": "hook-b",
            "updatedAt": "today",
        }
    )

    first = workflow_semantic_fingerprint(nodes, {}, {"timezone": "Europe/Istanbul"})
    assert (
        workflow_fingerprint(
            {
                "nodes": nodes,
                "connections": {},
                "settings": {"timezone": "Europe/Istanbul"},
            }
        )
        == first
    )
    assert (
        workflow_semantic_fingerprint(
            changed_metadata,
            {},
            {"timezone": "Europe/Istanbul", "updatedAt": "today"},
        )
        == first
    )

    assert workflow_semantic_fingerprint(changed_metadata, {}, {"timezone": "UTC"}) != first

    changed_metadata[0]["parameters"]["subject"] = "Different reminder"
    assert (
        workflow_semantic_fingerprint(changed_metadata, {}, {"timezone": "Europe/Istanbul"})
        != first
    )


def _pipeline_if_nodes() -> list[WorkflowNode]:
    return [
        WorkflowNode(
            name="Webhook",
            type="n8n-nodes-base.webhook",
            typeVersion=2.1,
            parameters={"path": "p"},
        ),
        WorkflowNode(
            name="IF",
            type="n8n-nodes-base.if",
            typeVersion=2.2,
            parameters={
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": {"type": "string", "operation": "equals"},
                            "rightValue": "pending",
                        },
                        {
                            "leftValue": "={{ $json.sent }}",
                            "operator": {"type": "string", "operation": "equals"},
                            "rightValue": "no",
                        },
                    ]
                }
            },
        ),
    ]


def test_build_pipeline_retries_before_n8n_on_string_if_operator():
    nodes = _pipeline_if_nodes()
    nodes[1].parameters["conditions"]["conditions"][0]["operator"] = "equals"

    with pytest.raises(ModelRetry, match="operator must be an object"):
        _validated_runtime_workflow(
            nodes,
            _connections(("Webhook", "IF")),
            input_schema=[],
        )


def test_build_pipeline_retries_on_semantic_assurance_error(monkeypatch):
    monkeypatch.setattr("src.agent.tools.build_pipeline.settings.workflow_assurance_mode", "hybrid")
    with pytest.raises(ModelRetry, match="semantic assurance"):
        _validated_runtime_workflow(
            _pipeline_if_nodes(),
            _connections(("Webhook", "IF")),
            input_schema=[],
        )


def test_build_pipeline_observe_mode_does_not_block(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.build_pipeline.settings.workflow_assurance_mode", "observe"
    )

    _, connections, _ = _validated_runtime_workflow(
        _pipeline_if_nodes(),
        _connections(("Webhook", "IF")),
        input_schema=[],
    )

    assert "Webhook" in connections


def test_build_pipeline_enforce_mode_promotes_shadow_findings(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.build_pipeline.settings.workflow_assurance_mode", "enforce"
    )
    nodes = [
        WorkflowNode(
            name="Webhook",
            type="n8n-nodes-base.webhook",
            typeVersion=2.1,
            parameters={"path": "p"},
        ),
        WorkflowNode(
            name="Custom",
            type="n8n-nodes-community.custom",
            typeVersion=1,
            parameters={},
        ),
    ]

    with pytest.raises(ModelRetry, match="no static output contract"):
        _validated_runtime_workflow(
            nodes,
            _connections(("Webhook", "Custom")),
            input_schema=[],
        )
