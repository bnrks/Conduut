from typing import Any

import pytest

from src.agent.validation import (
    normalize_workflow_connections,
    normalize_workflow_nodes,
    validate_workflow_payload,
)


class FakeRegistry:
    def __init__(self, schemas: dict[str, dict[str, Any]]):
        self.schemas = schemas

    def get_node_schema(self, node_type: str):
        if node_type in self.schemas:
            return self.schemas[node_type]
        for schema in self.schemas.values():
            if schema["type"].split(".")[-1].lower() == node_type.lower():
                return schema
        return None


SCHEMAS = {
    "n8n-nodes-base.manualTrigger": {
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "isTrigger": True,
    },
    "n8n-nodes-base.scheduleTrigger": {
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.3,
        "isTrigger": True,
    },
    "n8n-nodes-base.set": {
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "isTrigger": False,
    },
    "n8n-nodes-base.gmail": {
        "type": "n8n-nodes-base.gmail",
        "typeVersion": 2.1,
        "isTrigger": False,
    },
    "n8n-nodes-base.if": {
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "isTrigger": False,
    },
    "n8n-nodes-base.filter": {
        "type": "n8n-nodes-base.filter",
        "typeVersion": 2.1,
        "isTrigger": False,
    },
    "n8n-nodes-base.code": {
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "isTrigger": False,
    },
    "n8n-nodes-base.googleSheets": {
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "isTrigger": False,
    },
    "n8n-nodes-base.httpRequest": {
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.3,
        "isTrigger": False,
    },
}


def valid_nodes():
    return [
        {
            "id": "trigger",
            "name": "Manual Trigger",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [250, 300],
            "parameters": {},
        },
        {
            "id": "set",
            "name": "Set",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [500, 300],
            "parameters": {
                "mode": "manual",
                "assignments": {
                    "assignments": [
                        {
                            "id": "message",
                            "name": "message",
                            "type": "string",
                            "value": "hello from Conduut",
                        }
                    ]
                },
                "options": {},
            },
        },
    ]


def schedule_node(interval: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "schedule",
        "name": "Schedule",
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.3,
        "position": [250, 300],
        "parameters": {"rule": {"interval": [interval]}},
    }


def test_valid_minimal_workflow_passes():
    errors = validate_workflow_payload(
        valid_nodes(),
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_valid_daily_schedule_passes():
    errors = validate_workflow_payload(
        [schedule_node({"field": "days", "triggerAtHour": 22, "triggerAtMinute": 20})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_schedule_alias_fails_before_n8n_activation():
    errors = validate_workflow_payload(
        [schedule_node({"field": "daily", "triggerAtHour": 22})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("field must be one of" in error and "daily" in error for error in errors)


def test_schedule_hour_and_minute_ranges_are_validated():
    errors = validate_workflow_payload(
        [schedule_node({"field": "days", "triggerAtHour": 24, "triggerAtMinute": 60})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("triggerAtHour" in error for error in errors)
    assert any("triggerAtMinute" in error for error in errors)


def test_schedule_month_interval_has_no_invented_upper_bound():
    errors = validate_workflow_payload(
        [schedule_node({"field": "months", "monthsInterval": 18})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_schedule_interval_requires_rule():
    node = schedule_node({"field": "days"})
    node["parameters"] = {}

    errors = validate_workflow_payload(
        [node],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("parameters.rule.interval" in error for error in errors)


def test_schedule_cron_expression_cannot_be_empty():
    errors = validate_workflow_payload(
        [schedule_node({"field": "cronExpression", "expression": ""})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("non-empty expression" in error for error in errors)


def test_schedule_cron_expression_requires_six_valid_fields():
    errors = validate_workflow_payload(
        [schedule_node({"field": "cronExpression", "expression": "not a cron"})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("six valid cron fields" in error for error in errors)


def test_schedule_valid_six_field_cron_expression_passes():
    errors = validate_workflow_payload(
        [schedule_node({"field": "cronExpression", "expression": "0 20 22 * * *"})],
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_normalize_chat_model_wraps_model_as_resource_locator():
    # n8n's lmChat* nodes expect `model` as a resourceLocator, not a plain
    # string; a bare string raises "Could not get parameter" at run time.
    nodes = [
        {
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.3,
            "position": [0, 0],
            "parameters": {"model": "gpt-4o-mini", "options": {}},
        }
    ]
    out = normalize_workflow_nodes(nodes, node_registry=FakeRegistry({}))  # type: ignore[arg-type]
    assert out[0].parameters["model"] == {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}


def test_normalize_chat_model_leaves_resource_locator_untouched():
    rl = {"__rl": True, "mode": "list", "value": "gpt-4o"}
    nodes = [
        {
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.3,
            "position": [0, 0],
            "parameters": {"model": rl},
        }
    ]
    out = normalize_workflow_nodes(nodes, node_registry=FakeRegistry({}))  # type: ignore[arg-type]
    assert out[0].parameters["model"] == rl


def test_normalize_connections_assigns_ai_port_type():
    # The connection type under an AI sub-node port must be the port name, not
    # "main" — otherwise n8n ignores the chat model and the agent runs empty.
    nodes = [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
        {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"},
        {"name": "AI Agent", "type": "@n8n/n8n-nodes-langchain.agent"},
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent"}]]},
        "OpenAI Chat Model": {"ai_languageModel": [[{"node": "AI Agent"}]]},
    }
    out = normalize_workflow_connections(connections, nodes)
    assert out["OpenAI Chat Model"]["ai_languageModel"][0][0]["type"] == "ai_languageModel"
    assert out["Webhook"]["main"][0][0]["type"] == "main"


def test_empty_nodes_fail():
    errors = validate_workflow_payload([], {}, node_registry=FakeRegistry({}))  # type: ignore[arg-type]

    assert errors == ["nodes array is empty; every workflow needs at least one trigger node"]


def test_duplicate_node_ids_fail():
    nodes = valid_nodes()
    nodes[1]["id"] = "trigger"

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Duplicate node id: 'trigger'" in errors


def test_missing_required_field_fails():
    nodes = valid_nodes()
    del nodes[0]["parameters"]

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Node 'Manual Trigger' missing required field: parameters" in errors


def test_missing_trigger_fails():
    nodes = [valid_nodes()[1]]

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "No trigger node found; workflow needs a trigger node" in errors


def test_invalid_type_version_fails():
    nodes = valid_nodes()
    nodes[1]["typeVersion"] = 2

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Node 'Set' typeVersion must be 3.4 for n8n-nodes-base.set" in errors


def test_non_numeric_type_version_fails():
    nodes = valid_nodes()
    nodes[1]["typeVersion"] = "3.4"

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Node 'Set' typeVersion must be a number" in errors


def test_set_node_without_assignments_fails():
    nodes = valid_nodes()
    nodes[1]["parameters"] = {"mode": "manual", "options": {}}

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert (
        "Set node 'Set' must define parameters.assignments.assignments with at least one field"
        in errors
    )


def test_set_node_assignment_missing_value_fails():
    nodes = valid_nodes()
    del nodes[1]["parameters"]["assignments"]["assignments"][0]["value"]

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Set node 'Set assignment 1' missing required field: value" in errors


def test_set_node_raw_mode_requires_json_output():
    nodes = valid_nodes()
    nodes[1]["parameters"] = {"mode": "raw", "options": {}}

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Set node 'Set' raw mode requires parameters.jsonOutput" in errors


def test_normalize_workflow_nodes_canonicalizes_shorthand_type_and_version():
    nodes = valid_nodes()
    nodes[1]["type"] = "set"
    nodes[1]["typeVersion"] = 1

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[1].type == "n8n-nodes-base.set"
    assert normalized[1].typeVersion == 3.4


def test_normalize_workflow_nodes_rewrites_gmail_message_create_to_send():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "create",
                "authentication": "oAuth2",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["operation"] == "send"


def test_normalize_workflow_nodes_maps_gmail_send_alias_parameters():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "toEmail": "user@example.test",
                "subject": "Hello",
                "bodyContent": "Message body",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["sendTo"] == "user@example.test"
    assert normalized[2].parameters["subject"] == "Hello"
    assert normalized[2].parameters["message"] == "Message body"
    assert "toEmail" not in normalized[2].parameters
    assert "bodyContent" not in normalized[2].parameters


def test_normalize_workflow_nodes_preserves_html_body_content_type():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "toEmail": "user@example.test",
                "subject": "Digest",
                "bodyContent": "<h1>Digest</h1>",
                "bodyContentType": "text/html",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["emailType"] == "html"


def test_normalize_workflow_nodes_rewrites_google_sheets_append_resource_to_sheet():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "sheets",
            "name": "Google Sheets",
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
            "position": [750, 300],
            "parameters": {
                "resource": "spreadsheet",
                "operation": "append",
                "authentication": "oAuth2",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["resource"] == "sheet"


def _sheets_node(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "sheets",
        "name": "Update Siparis",
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "position": [750, 300],
        "parameters": parameters,
    }


def _if_node(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "if",
        "name": "Filter",
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [625, 300],
        "parameters": parameters,
    }


def _filter_node(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "filter",
        "name": "Filter Rows",
        "type": "n8n-nodes-base.filter",
        "typeVersion": 2.1,
        "position": [625, 300],
        "parameters": parameters,
    }


def _code_node(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "code",
        "name": "Filter Code",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [625, 300],
        "parameters": parameters,
    }


def _split_in_batches_node(
    type_version: float = 3,
    name: str = "Loop Over Leads",
) -> dict[str, Any]:
    return {
        "id": "split",
        "name": name,
        "type": "n8n-nodes-base.splitInBatches",
        "typeVersion": type_version,
        "position": [625, 300],
        "parameters": {"batchSize": 1, "options": {}},
    }


def _gmail_send_node(name: str = "Send Email") -> dict[str, Any]:
    return {
        "id": "gmail",
        "name": name,
        "type": "n8n-nodes-base.gmail",
        "typeVersion": 2.1,
        "position": [875, 300],
        "parameters": {
            "resource": "message",
            "operation": "send",
            "sendTo": "={{ $json.email }}",
            "subject": "Hello",
            "message": "Body",
        },
    }


def _split_branch(groups: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {"main": groups}


def _http_request_node(
    *,
    name: str = "Check Website",
    full_response: bool = False,
    never_error: bool = False,
    on_error: str | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "method": "GET",
        "url": "https://example.test/health",
        "options": {
            "response": {
                "response": {
                    "fullResponse": full_response,
                    "neverError": never_error,
                    "responseFormat": "json",
                }
            }
        },
    }
    node: dict[str, Any] = {
        "id": "http",
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.3,
        "position": [500, 300],
        "parameters": parameters,
    }
    if on_error is not None:
        node["onError"] = on_error
    return node


def test_google_sheets_update_missing_columns_fails_validation():
    # The pre-v4 shape (dataMode/values, no columns) passes structural checks but
    # n8n v4 ignores it -> the "mark as sent" write silently does nothing.
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
                "dataMode": "raw",
                "values": {"teslim_mail": "evet"},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    joined = "\n".join(errors)
    assert "Update Siparis" in joined
    assert "parameters.columns" in joined
    assert "matchingColumns" in joined
    # The legacy keys are named so the model knows to drop them.
    assert "dataMode" in joined


def test_if_v2_string_operator_fails_validation_before_n8n():
    nodes = valid_nodes()
    nodes.append(
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": "equals",
                            "rightValue": "pending",
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("operator='equals'" in error or 'operator="equals"' in error for error in errors)
    assert any("operator must be an object" in error for error in errors)


def test_if_v2_operator_object_passes_validation():
    nodes = valid_nodes()
    nodes.append(
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": {"type": "string", "operation": "equals"},
                            "rightValue": "pending",
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_if_v2_empty_conditions_fail_validation():
    nodes = valid_nodes()
    nodes.append(_if_node({"conditions": {"conditions": []}}))

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("requires at least one condition rule" in error for error in errors)


def test_if_v2_empty_parameters_fail_validation():
    nodes = valid_nodes()
    nodes.append(_if_node({}))

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("conditionless IF cannot safely filter items" in error for error in errors)


def test_filter_v2_string_operator_fails_validation_before_n8n():
    nodes = valid_nodes()
    nodes.append(
        _filter_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": "equals",
                            "rightValue": "pending",
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("Filter Rows" in error and "operator='equals'" in error for error in errors)


def test_filter_v2_operator_object_passes_validation():
    nodes = valid_nodes()
    nodes.append(
        _filter_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": {"type": "string", "operation": "equals"},
                            "rightValue": "pending",
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


@pytest.mark.parametrize("factory", [_if_node, _filter_node])
def test_condition_node_v2_missing_left_operand_fails_validation(factory):
    nodes = valid_nodes()
    nodes.append(
        factory(
            {
                "conditions": {
                    "conditions": [
                        {
                            "operator": {"type": "string", "operation": "equals"},
                            "rightValue": "pending",
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("non-empty leftValue" in error for error in errors)


@pytest.mark.parametrize("factory", [_if_node, _filter_node])
def test_condition_node_v2_binary_operator_missing_right_operand_fails_validation(factory):
    nodes = valid_nodes()
    nodes.append(
        factory(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("requires rightValue" in error for error in errors)


@pytest.mark.parametrize("factory", [_if_node, _filter_node])
def test_condition_node_v2_unary_operator_may_omit_right_operand(factory):
    nodes = valid_nodes()
    nodes.append(
        factory(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": {"type": "string", "operation": "isNotEmpty"},
                        }
                    ]
                }
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_code_v2_lowercase_javascript_language_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        _code_node(
            {
                "mode": "runOnceForAllItems",
                "language": "javascript",
                "jsCode": "return $input.all();",
            }
        )
    )

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any(
        "language='javascript'" in error or 'language="javascript"' in error for error in errors
    )
    assert any("exact n8n value 'javaScript'" in error for error in errors)


def test_code_v2_javascript_requires_non_empty_jscode():
    nodes = valid_nodes()
    nodes.append(_code_node({"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": ""}))

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("parameters.jsCode" in error for error in errors)


def test_code_v2_omitted_language_with_jscode_passes_validation():
    nodes = valid_nodes()
    nodes.append(_code_node({"mode": "runOnceForAllItems", "jsCode": "return $input.all();"}))

    errors = validate_workflow_payload(
        nodes,
        {},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_google_sheets_update_with_columns_passes_validation():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": ["siparis_no"],
                    # A complete defineBelow update carries the matching column's
                    # value (so n8n knows which row) plus the fields to write.
                    "value": {"siparis_no": "={{ $json.siparis_no }}", "teslim_mail": "evet"},
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert errors == []


def test_google_sheets_update_matching_column_missing_from_value_fails_validation():
    # defineBelow reads the match value from columns.value["<matchCol>"]; if the
    # matching column has no value there, n8n throws "The 'Column to Match On'
    # parameter is required" at runtime. Catch it statically.
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": ["siparis_no"],
                    "value": {"teslim_mail": "evet"},  # no siparis_no -> unmatchable
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    joined = "\n".join(errors)
    assert "siparis_no" in joined
    assert "columns.value" in joined


def test_google_sheets_update_automap_does_not_require_value():
    # autoMapInputData maps the whole input item, so the matching value comes from
    # the item -> no explicit columns.value required.
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
                "columns": {
                    "mappingMode": "autoMapInputData",
                    "matchingColumns": ["siparis_no"],
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert not any("columns" in error for error in errors)


def test_google_sheets_update_columns_without_matching_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
                "columns": {"mappingMode": "defineBelow", "value": {"teslim_mail": "evet"}},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("matchingColumns" in error for error in errors)


def test_google_sheets_append_define_alias_fails_validation_before_n8n():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "E-posta Logu"},
                "columns": {
                    "mappingMode": "define",
                    "value": {
                        "from": "={{ $json.from }}",
                        "subject": "={{ $json.subject }}",
                        "date": "={{ $json.date }}",
                    },
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("unsupported" in error and "defineBelow" in error for error in errors)


def test_google_sheets_append_missing_columns_gets_append_specific_guidance():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "E-posta Logu"},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("autoMapInputData" in error and "matchingColumns" not in error for error in errors)


def test_google_sheets_append_definebelow_missing_schema_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "E-posta Logu"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": [],
                    "value": {"from": "={{ $json.from }}"},
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("columns.schema" in error for error in errors)


def test_google_sheets_append_automap_still_passes_without_schema():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "E-posta Logu"},
                "columns": {
                    "mappingMode": "autoMapInputData",
                    "matchingColumns": [],
                    "schema": [],
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert not any("columns" in error for error in errors)


def test_google_sheets_read_not_flagged_for_columns():
    # Read writes nothing -> no column mapping required.
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "read",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert not any("columns" in error for error in errors)


def test_google_sheets_row_op_missing_sheetname_fails_validation():
    # v4 row ops address the tab via a sheetName resourceLocator. When the model
    # leaves the tab in a top-level range (or omits it) and repair could not derive
    # it, n8n rejects the workflow ("has issues, cannot be executed"). Backstop it.
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "range": "Kayıtlar",
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("sheetName" in error for error in errors)


def test_google_sheets_row_op_missing_documentid_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "sheetName": {"__rl": True, "mode": "name", "value": "Kayıtlar"},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("documentId" in error for error in errors)


def test_google_sheets_row_op_empty_documentid_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "read",
                "documentId": {"__rl": True, "mode": "id", "value": ""},
                "sheetName": {"__rl": True, "mode": "name", "value": "Siparisler"},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("documentId" in error for error in errors)


def test_google_sheets_row_op_numeric_sheetid_is_rejected_as_ambiguous():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "sheetId": "123456789",
                "sheetName": {"__rl": True, "mode": "name", "value": "Kayıtlar"},
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("sheetId looks numeric" in error for error in errors)


def test_google_sheets_row_op_conflicting_legacy_and_current_document_ids_fail_validation():
    nodes = valid_nodes()
    nodes.append(
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetId": "1different",
                "sheetName": {"__rl": True, "mode": "name", "value": "Kayıtlar"},
                "columns": {
                    "mappingMode": "autoMapInputData",
                    "matchingColumns": [],
                    "schema": [],
                },
            }
        )
    )
    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]
    assert any("conflicting legacy sheetId" in error for error in errors)


def test_gmail_send_placeholder_recipient_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "receiver@email.com",
                "subject": "Hello",
                "message": "Message body",
            },
        }
    )

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Gmail node 'Gmail' sendTo must be a real recipient email" in errors


def test_gmail_send_runtime_expression_recipient_passes_validation():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "={{$json.to}}",
                "subject": "={{$json.subject}}",
                "message": "={{$json.message}}",
            },
        }
    )

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert errors == []


def test_gmail_send_missing_message_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "user@example.test",
                "subject": "Hello",
            },
        }
    )

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Gmail node 'Gmail' send operation requires parameters.message" in errors


def test_http_status_condition_requires_full_response():
    nodes = [
        valid_nodes()[0],
        _http_request_node(never_error=True),
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("fullResponse" in error and "Check Website" in error for error in errors)


def test_http_status_condition_requires_never_error():
    nodes = [
        valid_nodes()[0],
        _http_request_node(full_response=True),
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("neverError" in error and "Check Website" in error for error in errors)


def test_http_status_condition_requires_top_level_continue_regular_output_for_alert_path():
    nodes = [
        valid_nodes()[0],
        _http_request_node(full_response=True, never_error=True),
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
        _gmail_send_node(name="Send Alert"),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
        "Filter": {"main": [[{"node": "Send Alert", "type": "main", "index": 0}], []]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("node.onError" in error and "Check Website" in error for error in errors)


def test_http_status_alert_flow_rejects_parameter_level_on_error_alias():
    http_node = _http_request_node(full_response=True, never_error=True)
    http_node["parameters"]["onError"] = "continueRegularOutput"
    nodes = [
        valid_nodes()[0],
        http_node,
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
        _gmail_send_node(name="Send Alert"),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
        "Filter": {"main": [[{"node": "Send Alert", "type": "main", "index": 0}], []]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("node.onError" in error and "Check Website" in error for error in errors)


def test_http_status_alert_flow_accepts_current_response_shape_and_top_level_on_error():
    nodes = [
        valid_nodes()[0],
        _http_request_node(
            full_response=True,
            never_error=True,
            on_error="continueRegularOutput",
        ),
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
        _gmail_send_node(name="Send Alert"),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
        "Filter": {"main": [[{"node": "Send Alert", "type": "main", "index": 0}], []]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_http_status_condition_uses_nearest_http_source_only():
    warmup = _http_request_node(name="Warmup")
    warmup["id"] = "warmup"
    check = _http_request_node(
        full_response=True,
        never_error=True,
    )
    nodes = [
        valid_nodes()[0],
        warmup,
        check,
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Warmup", "type": "main", "index": 0}]]},
        "Warmup": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert not any("Warmup" in error for error in errors)
    assert errors == []


def test_http_status_alert_flow_requires_transport_policy_for_http_post_action():
    nodes = [
        valid_nodes()[0],
        _http_request_node(full_response=True, never_error=True),
        _if_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.statusCode }}",
                            "operator": {"type": "number", "operation": "notEqual"},
                            "rightValue": 200,
                        }
                    ]
                }
            }
        ),
        {
            "id": "post-alert",
            "name": "Post Alert",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.3,
            "position": [875, 300],
            "parameters": {
                "method": "POST",
                "url": "https://alerts.example.test/hook",
                "options": {},
            },
        },
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Check Website", "type": "main", "index": 0}]]},
        "Check Website": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
        "Filter": {"main": [[{"node": "Post Alert", "type": "main", "index": 0}], []]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("node.onError" in error and "Check Website" in error for error in errors)


def test_split_in_batches_v3_done_port_body_fails_validation():
    nodes = [
        valid_nodes()[0],
        _split_in_batches_node(type_version=3),
        _gmail_send_node(),
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Leads"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": ["email"],
                    "value": {"email": "lead@example.test", "status": "Contacted"},
                },
            }
        ),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
        "Loop Over Leads": _split_branch(
            [[{"node": "Send Email", "type": "main", "index": 0}], []]
        ),
        "Send Email": {"main": [[{"node": "Update Siparis", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("main output 0 ('done')" in error and "Loop Over Leads" in error for error in errors)


def test_split_in_batches_v3_loop_branch_without_return_fails_validation():
    nodes = [
        valid_nodes()[0],
        _split_in_batches_node(type_version=3),
        _gmail_send_node(),
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Leads"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": ["email"],
                    "value": {"email": "lead@example.test", "status": "Contacted"},
                },
            }
        ),
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
        "Loop Over Leads": _split_branch(
            [[], [{"node": "Send Email", "type": "main", "index": 0}]]
        ),
        "Send Email": {"main": [[{"node": "Update Siparis", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("nothing returns to 'Loop Over Leads'" in error for error in errors)


def test_split_in_batches_shared_done_and_loop_return_fails_validation():
    nodes = [
        valid_nodes()[0],
        _split_in_batches_node(type_version=3),
        _gmail_send_node(),
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Leads"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": ["email"],
                    "value": {"email": "lead@example.test", "status": "Contacted"},
                },
            }
        ),
        {
            "id": "after-loop",
            "name": "After Loop",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [900, 150],
            "parameters": {"mode": "manual", "assignments": {"assignments": []}},
        },
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
        "Loop Over Leads": _split_branch(
            [
                [{"node": "After Loop", "type": "main", "index": 0}],
                [{"node": "Send Email", "type": "main", "index": 0}],
            ]
        ),
        "After Loop": {"main": [[{"node": "Update Siparis", "type": "main", "index": 0}]]},
        "Send Email": {"main": [[{"node": "Update Siparis", "type": "main", "index": 0}]]},
        "Update Siparis": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any(
        "only that branch may return" in error and "'Update Siparis'" in error for error in errors
    )


def test_split_in_batches_version_aware_loop_topology_passes_validation():
    base_nodes = [
        valid_nodes()[0],
        _filter_node(
            {
                "conditions": {
                    "conditions": [
                        {
                            "leftValue": "={{ $json.status }}",
                            "operator": {"type": "string", "operation": "equals"},
                            "rightValue": "New",
                        }
                    ]
                }
            }
        ),
        _gmail_send_node(),
        _sheets_node(
            {
                "resource": "sheet",
                "operation": "update",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Leads"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "matchingColumns": ["email"],
                    "value": {
                        "email": "={{ $('Filter Rows').item.json.email }}",
                        "status": "Contacted",
                    },
                },
            }
        ),
        {
            "id": "set-after",
            "name": "After Loop",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [1125, 150],
            "parameters": {
                "mode": "manual",
                "assignments": {
                    "assignments": [
                        {
                            "id": "summary",
                            "name": "summary",
                            "type": "string",
                            "value": "done",
                        }
                    ]
                },
                "options": {},
            },
        },
    ]

    nodes_v3 = [*base_nodes[:2], _split_in_batches_node(type_version=3), *base_nodes[2:]]
    errors_v3 = validate_workflow_payload(
        nodes_v3,
        {
            "Manual Trigger": {"main": [[{"node": "Filter Rows", "type": "main", "index": 0}]]},
            "Filter Rows": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
            "Loop Over Leads": _split_branch(
                [
                    [{"node": "After Loop", "type": "main", "index": 0}],
                    [{"node": "Send Email", "type": "main", "index": 0}],
                ]
            ),
            "Send Email": {"main": [[{"node": "Update Siparis", "type": "main", "index": 0}]]},
            "Update Siparis": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
        },
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    nodes_v2 = [*base_nodes[:2], _split_in_batches_node(type_version=2), *base_nodes[2:]]
    errors_v2 = validate_workflow_payload(
        nodes_v2,
        {
            "Manual Trigger": {"main": [[{"node": "Filter Rows", "type": "main", "index": 0}]]},
            "Filter Rows": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
            "Loop Over Leads": _split_branch(
                [
                    [{"node": "Send Email", "type": "main", "index": 0}],
                    [{"node": "After Loop", "type": "main", "index": 0}],
                ]
            ),
            "Send Email": {"main": [[{"node": "Update Siparis", "type": "main", "index": 0}]]},
            "Update Siparis": {"main": [[{"node": "Loop Over Leads", "type": "main", "index": 0}]]},
        },
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors_v3 == []
    assert errors_v2 == []


def test_normalize_workflow_connections_resolves_node_ids_to_names():
    nodes = valid_nodes()
    nodes[0]["id"] = "1"
    nodes[1]["id"] = "2"

    normalized = normalize_workflow_connections(
        {"1": {"main": [[{"node": "2", "type": "main", "index": 0}]]}},
        nodes,
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_normalize_workflow_connections_resolves_ordinal_aliases_to_names():
    normalized = normalize_workflow_connections(
        {"node1": {"main": [[{"node": "node2", "type": "main", "index": 0}]]}},
        valid_nodes(),
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_normalize_workflow_connections_wraps_flat_main_targets():
    normalized = normalize_workflow_connections(
        {"Manual Trigger": {"main": [{"node": "Set", "type": "main"}]}},
        valid_nodes(),
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_normalize_workflow_connections_adds_main_for_direct_target():
    normalized = normalize_workflow_connections(
        {"Manual Trigger": {"node": "Set"}},
        valid_nodes(),
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_bad_connection_reference_fails():
    errors = validate_workflow_payload(
        valid_nodes(),
        {"Manual Trigger": {"main": [[{"node": "Missing", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert "connections references unknown target node 'Missing'" in errors


def test_langchain_chat_model_wired_into_main_flow_fails():
    """Reproduces the empty-email bug: a langchain chat-model sub-node has no
    main output, so wiring it into the main flow yields empty downstream data.
    It must attach to an AI Agent via an ai_languageModel port instead."""
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "chat",
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.2,
            "position": [750, 300],
            "parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}},
        }
    )
    connections = {
        "Manual Trigger": {"main": [[{"node": "OpenAI Chat Model", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("OpenAI Chat Model" in error and "ai_languageModel" in error for error in errors), (
        errors
    )


def test_langchain_chat_model_as_main_source_fails():
    """A chat-model sub-node must not be a source of a main connection either."""
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "chat",
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.2,
            "position": [750, 300],
            "parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}},
        }
    )
    connections = {
        "Manual Trigger": {"main": [[{"node": "OpenAI Chat Model", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "Set", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("OpenAI Chat Model" in error and "ai_languageModel" in error for error in errors), (
        errors
    )


def test_langchain_chat_model_attached_via_ai_port_passes():
    """A chat model correctly attached to an AI Agent via the ai_languageModel
    port is valid and must not trigger the sub-node guard (no false positive)."""
    nodes = [
        valid_nodes()[0],
        {
            "id": "agent",
            "name": "AI Agent",
            "type": "@n8n/n8n-nodes-langchain.agent",
            "typeVersion": 1.9,
            "position": [500, 300],
            "parameters": {"promptType": "define", "text": "hello", "options": {}},
        },
        {
            "id": "chat",
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.2,
            "position": [500, 520],
            "parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}},
        },
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {
            "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
        },
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == [], errors


def test_bare_input_expression_fails():
    """The agent sometimes leaks the graph-ref syntax {{input.x}} into raw JSON.
    'input' is not an n8n variable, so the field renders empty and the AI prompt
    or email loses the runtime values. It must use the trigger json.body path."""
    nodes = valid_nodes()
    nodes[1]["parameters"]["assignments"]["assignments"][0]["value"] = (
        "=Merhaba {{input.company_name}}, teklifimiz hazir."
    )

    errors = validate_workflow_payload(
        nodes,
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("input." in error and "Set" in error for error in errors), errors


def test_valid_trigger_body_expression_passes():
    """Referencing runtime input through the trigger json.body path is valid."""
    nodes = valid_nodes()
    nodes[1]["parameters"]["assignments"]["assignments"][0]["value"] = (
        "={{$('Manual Trigger').first().json.body.company_name}}"
    )

    errors = validate_workflow_payload(
        nodes,
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == [], errors
