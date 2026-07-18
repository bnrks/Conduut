from src.agent.assurance.instrumentation import inject_schedule_identity_guards


def _workflow():
    nodes = [
        {"name": "Schedule", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}},
        {
            "name": "Read",
            "type": "n8n-nodes-base.googleSheets",
            "parameters": {"operation": "read"},
        },
        {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
        {
            "name": "Update",
            "type": "n8n-nodes-base.googleSheets",
            "parameters": {
                "operation": "update",
                "columns": {
                    "matchingColumns": ["customer_id"],
                    "value": {"customer_id": "={{ $('Read').item.json.customer_id }}"},
                },
            },
        },
    ]
    connections = {
        "Schedule": {"main": [[{"node": "Read", "type": "main", "index": 0}]]},
        "Read": {"main": [[{"node": "Send", "type": "main", "index": 0}]]},
        "Send": {"main": [[{"node": "Update", "type": "main", "index": 0}]]},
    }
    return nodes, connections


def test_schedule_identity_guard_is_inserted_before_action():
    nodes, connections = _workflow()
    guarded_nodes, guarded_connections = inject_schedule_identity_guards(nodes, connections)
    guard = next(node for node in guarded_nodes if node["name"].startswith("[Conduut]"))
    assert guarded_connections["Read"]["main"][0][0]["node"] == guard["name"]
    assert guarded_connections[guard["name"]]["main"][0][0]["node"] == "Send"
    assert "duplicate" in guard["parameters"]["jsCode"]


def test_identity_guard_is_idempotent():
    nodes, connections = _workflow()
    inject_schedule_identity_guards(nodes, connections)
    inject_schedule_identity_guards(nodes, connections)
    assert sum(node["name"].startswith("[Conduut]") for node in nodes) == 1


def test_manual_workflow_is_not_instrumented():
    nodes, connections = _workflow()
    nodes[0]["type"] = "n8n-nodes-base.manualTrigger"
    inject_schedule_identity_guards(nodes, connections)
    assert not any(node["name"].startswith("[Conduut]") for node in nodes)
