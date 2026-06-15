"""Tests for the deterministic workflow repair layer (agent.repair)."""

from typing import Any

from src.agent.repair import repair_workflow


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
    "n8n-nodes-base.webhook": {
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "isTrigger": True,
    },
    "n8n-nodes-base.code": {
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "isTrigger": False,
    },
    "n8n-nodes-base.gmail": {
        "type": "n8n-nodes-base.gmail",
        "typeVersion": 2.1,
        "isTrigger": False,
    },
    "@n8n/n8n-nodes-langchain.agent": {
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 1.7,
        "isTrigger": False,
    },
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": {
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
        "typeVersion": 1,
        "isTrigger": False,
    },
}

REGISTRY = FakeRegistry(SCHEMAS)


def _node(name, node_type, **kw):
    node = {"name": name, "type": node_type, "parameters": kw.pop("parameters", {})}
    node.update(kw)
    return node


def _all_main_targets(connections):
    targets = []
    for value in connections.values():
        for group in value.get("main", []):
            for conn in group:
                targets.append(conn["node"])
    return targets


# --------------------------------------------------------------------------
# Stage 1 — boilerplate fill
# --------------------------------------------------------------------------


def test_boilerplate_id_typeversion_position_filled():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Code", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
    ]
    repaired, _conns, repairs = repair_workflow(
        nodes,
        {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}},
        registry=REGISTRY,
    )
    for node in repaired:
        assert node.get("id")
        assert isinstance(node["position"], list) and len(node["position"]) == 2
    code = next(n for n in repaired if n["name"] == "Code")
    assert code["typeVersion"] == 2
    webhook = next(n for n in repaired if n["name"] == "Webhook")
    assert webhook.get("webhookId")
    assert repairs  # at least one repair recorded


# --------------------------------------------------------------------------
# Stage 2 — linear connection inference
# --------------------------------------------------------------------------


def test_linear_connections_inferred_when_missing():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Code", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
        _node(
            "Gmail", "n8n-nodes-base.gmail", parameters={"resource": "message", "operation": "send"}
        ),
    ]
    repaired, conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    assert conns["Webhook"]["main"][0][0]["node"] == "Code"
    assert conns["Code"]["main"][0][0]["node"] == "Gmail"


# --------------------------------------------------------------------------
# Stage 3 — sub-node port repair
# --------------------------------------------------------------------------


def test_chat_model_wired_into_main_moved_to_ai_port():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("OpenAI Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi"),
        _node("AI Agent", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "hi"}),
        _node(
            "Gmail", "n8n-nodes-base.gmail", parameters={"resource": "message", "operation": "send"}
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "AI Agent": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
    }
    _repaired, conns, repairs = repair_workflow(nodes, connections, registry=REGISTRY)

    # Chat model no longer feeds the main flow anywhere
    assert "OpenAI Chat Model" not in _all_main_targets(conns)
    assert "main" not in conns.get("OpenAI Chat Model", {})
    # It is attached to the agent through the ai_languageModel port
    ai = conns["OpenAI Chat Model"]["ai_languageModel"]
    assert ai[0][0]["node"] == "AI Agent"
    assert ai[0][0]["type"] == "ai_languageModel"
    assert any("ai_languageModel" in r or "sub-node" in r.lower() for r in repairs)


def test_chat_model_left_alone_when_multiple_agents():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Chat", "@n8n/n8n-nodes-langchain.lmChatOpenAi"),
        _node("Agent A", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "a"}),
        _node("Agent B", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "b"}),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "Agent A", "type": "main", "index": 0}]]},
        "Chat": {"main": [[{"node": "Agent A", "type": "main", "index": 0}]]},
    }
    _repaired, conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    # Ambiguous: repair declines, leaves it wired in main for validate to reject.
    assert "main" in conns["Chat"]
    assert "ai_languageModel" not in conns["Chat"]


# --------------------------------------------------------------------------
# Stage 4 — expression repair
# --------------------------------------------------------------------------


def test_bare_input_expression_rewritten_to_trigger_body():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "AI Agent",
            "@n8n/n8n-nodes-langchain.agent",
            parameters={"text": "Write a proposal for {{input.company}}"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    agent = next(n for n in repaired if n["name"] == "AI Agent")
    text = agent["parameters"]["text"]
    assert "input.company" not in text
    assert "$('Webhook').first().json.body.company" in text


def test_bare_json_field_rewritten_to_body_for_trigger_fed_node():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const c = $json.company; return [{json:{c}}];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert "$json.body.company" in code["parameters"]["jsCode"]
    assert "$json.company" not in code["parameters"]["jsCode"]


def test_template_field_gets_equals_prefix():
    # A field with {{ }} but no leading '=' is sent literally by n8n; repair must
    # turn it into an expression.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "AI Agent",
            "@n8n/n8n-nodes-langchain.agent",
            parameters={"text": "Teklif: {{ $json.body.company }}"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"company"}, trigger_name="Webhook", registry=REGISTRY
    )
    agent = next(n for n in repaired if n["name"] == "AI Agent")
    assert agent["parameters"]["text"].startswith("=")


def test_non_trigger_fed_node_qualifies_webhook_reference():
    # Gmail is fed by AI Agent, not the webhook, so $json.body.email is undefined
    # there; it must be qualified to $('Webhook').first().json.body.email.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("AI Agent", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "hi"}),
        _node(
            "Gmail",
            "n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": "={{ $json.body.email }}",
                "message": "={{ $('AI Agent').first().json.output }}",
            },
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "AI Agent": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
    }
    repaired, _conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"email"}, trigger_name="Webhook", registry=REGISTRY
    )
    gmail = next(n for n in repaired if n["name"] == "Gmail")
    assert gmail["parameters"]["sendTo"] == "={{ $('Webhook').first().json.body.email }}"
    # The agent-output reference is already qualified and must be left intact.
    assert gmail["parameters"]["message"] == "={{ $('AI Agent').first().json.output }}"


def test_code_node_jscode_not_prefixed_with_equals():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const c = $json.company; return [{json:{c}}];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"company"}, trigger_name="Webhook", registry=REGISTRY
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert not code["parameters"]["jsCode"].startswith("=")
    assert "$json.body.company" in code["parameters"]["jsCode"]


def test_body_path_not_rewritten_when_field_not_declared():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const x = $json.other; return [];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert "$json.other" in code["parameters"]["jsCode"]


def test_body_path_idempotent_when_already_body():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const c = $json.body.company; return [];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert code["parameters"]["jsCode"].count("body.company") == 1
    assert "body.body" not in code["parameters"]["jsCode"]


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_repair_is_idempotent():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("OpenAI Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi"),
        _node(
            "AI Agent", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "{{input.company}}"}
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
    }
    once_nodes, once_conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"company"}, trigger_name="Webhook", registry=REGISTRY
    )
    twice_nodes, twice_conns, _ = repair_workflow(
        once_nodes,
        once_conns,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    assert once_conns == twice_conns
    assert once_nodes == twice_nodes
