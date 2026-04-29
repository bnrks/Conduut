from typing import Any

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
    "n8n-nodes-base.set": {
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
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


def test_valid_minimal_workflow_passes():
    errors = validate_workflow_payload(
        valid_nodes(),
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


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


def test_bad_connection_reference_fails():
    errors = validate_workflow_payload(
        valid_nodes(),
        {"Manual Trigger": {"main": [[{"node": "Missing", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert "connections references unknown target node 'Missing'" in errors
