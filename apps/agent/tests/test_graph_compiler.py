"""Golden tests for the WorkflowGraph compiler."""

import pytest

from src.agent.schemas import GraphEdge, GraphNode, WorkflowGraph
from src.agent.tools.graph_compiler import (
    WorkflowGraphCompileError,
    compile_workflow_graph,
)

# Registry schemas the compiler/validator consult. Types absent here fall back
# to the block's declared typeVersion (still a valid n8n prefix).
SCHEMAS = {
    "n8n-nodes-base.manualTrigger": {"type": "n8n-nodes-base.manualTrigger", "typeVersion": 1},
    "n8n-nodes-base.webhook": {"type": "n8n-nodes-base.webhook", "typeVersion": 2},
    "n8n-nodes-base.httpRequest": {"type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2},
    "n8n-nodes-base.if": {"type": "n8n-nodes-base.if", "typeVersion": 2.2},
    "n8n-nodes-base.set": {"type": "n8n-nodes-base.set", "typeVersion": 3.4},
    "n8n-nodes-base.gmail": {"type": "n8n-nodes-base.gmail", "typeVersion": 2.1},
    "n8n-nodes-base.slack": {"type": "n8n-nodes-base.slack", "typeVersion": 2.3},
    "@n8n/n8n-nodes-langchain.agent": {
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 1.9,
    },
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": {
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
        "typeVersion": 1.2,
    },
}


@pytest.fixture(autouse=True)
def _patch_registry(monkeypatch):
    monkeypatch.setattr(
        "src.registry.registry.get_node_schema",
        lambda node_type: SCHEMAS.get(node_type),
    )


def _node_by_id(compiled, node_id):
    return next(node for node in compiled.nodes if node.id == node_id)


def test_http_request_linear_workflow():
    compiled = compile_workflow_graph(
        "Fetch and store",
        WorkflowGraph(
            trigger=GraphNode(id="t", kind="manual"),
            nodes=[
                GraphNode(
                    id="fetch",
                    kind="http_request",
                    params={"url": "https://api.example.com/users", "method": "get"},
                ),
            ],
            edges=[GraphEdge(source="t", target="fetch")],
        ),
    )

    trigger = _node_by_id(compiled, "t")
    fetch = _node_by_id(compiled, "fetch")
    assert trigger.type == "n8n-nodes-base.manualTrigger"
    assert fetch.type == "n8n-nodes-base.httpRequest"
    assert fetch.typeVersion == 4.2
    assert fetch.parameters["url"] == "https://api.example.com/users"
    assert fetch.parameters["method"] == "GET"
    assert compiled.connections == {
        trigger.name: {"main": [[{"node": "HTTP Request", "type": "main", "index": 0}]]}
    }


def test_if_branch_creates_true_false_outputs():
    compiled = compile_workflow_graph(
        "Route by status",
        WorkflowGraph(
            trigger=GraphNode(id="t", kind="webhook"),
            nodes=[
                GraphNode(
                    id="gate",
                    kind="if",
                    params={"field": "status", "operator": "equals", "value": "active"},
                ),
                GraphNode(
                    id="yes",
                    kind="gmail.send",
                    params={"to": "ops@acme.co", "subject": "Active", "message": "ok"},
                ),
                GraphNode(
                    id="no",
                    kind="gmail.send",
                    params={"to": "ops@acme.co", "subject": "Inactive", "message": "stop"},
                ),
            ],
            edges=[
                GraphEdge(source="t", target="gate"),
                GraphEdge(source="gate", target="yes", on="true"),
                GraphEdge(source="gate", target="no", on="false"),
            ],
        ),
    )

    gate = _node_by_id(compiled, "gate")
    condition = gate.parameters["conditions"]["conditions"][0]
    assert condition["leftValue"] == '={{$json["status"]}}'
    assert condition["rightValue"] == "active"
    assert condition["operator"] == {"type": "string", "operation": "equals"}

    gate_main = compiled.connections["If"]["main"]
    assert gate_main[0] == [{"node": "Gmail", "type": "main", "index": 0}]
    assert gate_main[1] == [{"node": "Gmail 2", "type": "main", "index": 0}]


def test_ai_agent_sub_node_wired_on_reversed_language_model_port():
    compiled = compile_workflow_graph(
        "Chat agent",
        WorkflowGraph(
            trigger=GraphNode(id="t", kind="manual"),
            nodes=[
                GraphNode(
                    id="agent",
                    kind="ai_agent",
                    params={"text": {"ref": "item.question"}, "system_prompt": "Be brief."},
                ),
                GraphNode(
                    id="llm",
                    kind="openai_chat",
                    attached_to="agent",
                    role="language_model",
                    params={"model": "gpt-4o-mini"},
                ),
            ],
            edges=[GraphEdge(source="t", target="agent")],
        ),
    )

    agent = _node_by_id(compiled, "agent")
    assert agent.type == "@n8n/n8n-nodes-langchain.agent"
    assert agent.parameters["promptType"] == "define"
    assert agent.parameters["text"] == '={{$json["question"]}}'
    assert agent.parameters["options"]["systemMessage"] == "Be brief."

    llm = _node_by_id(compiled, "llm")
    assert llm.type == "@n8n/n8n-nodes-langchain.lmChatOpenAi"
    assert llm.parameters["model"] == {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}

    # Trigger -> agent on main; model -> agent on the reversed ai_languageModel port.
    assert agent.name not in compiled.connections  # agent has no outgoing edge
    trigger = _node_by_id(compiled, "t")
    assert compiled.connections[trigger.name]["main"] == [
        [{"node": "AI Agent", "type": "main", "index": 0}]
    ]
    assert compiled.connections["OpenAI Chat Model"]["ai_languageModel"] == [
        [{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]
    ]


def test_set_fields_builds_assignments():
    compiled = compile_workflow_graph(
        "Shape data",
        WorkflowGraph(
            trigger=GraphNode(id="t", kind="manual"),
            nodes=[
                GraphNode(
                    id="shape",
                    kind="set",
                    params={
                        "fields": {
                            "name": {"ref": "item.full_name"},
                            "count": 3,
                            "active": True,
                        }
                    },
                ),
            ],
            edges=[GraphEdge(source="t", target="shape")],
        ),
    )

    shape = _node_by_id(compiled, "shape")
    assignments = shape.parameters["assignments"]["assignments"]
    by_name = {item["name"]: item for item in assignments}
    assert by_name["name"]["value"] == '={{$json["full_name"]}}'
    assert by_name["name"]["type"] == "string"
    assert by_name["count"] == {"id": "count", "name": "count", "type": "number", "value": 3}
    assert by_name["active"]["type"] == "boolean"


def test_generic_fallback_uses_registry_type_version():
    compiled = compile_workflow_graph(
        "Notify slack",
        WorkflowGraph(
            trigger=GraphNode(id="t", kind="manual"),
            nodes=[
                GraphNode(
                    id="msg",
                    kind="n8n:n8n-nodes-base.slack",
                    params={"text": "deploy done", "channel": "#ops"},
                ),
            ],
            edges=[GraphEdge(source="t", target="msg")],
        ),
    )

    msg = _node_by_id(compiled, "msg")
    assert msg.type == "n8n-nodes-base.slack"
    assert msg.typeVersion == 2.3
    assert msg.parameters == {"text": "deploy done", "channel": "#ops"}


def test_node_reference_resolves_to_source_node_expression():
    compiled = compile_workflow_graph(
        "Chain nodes",
        WorkflowGraph(
            trigger=GraphNode(id="t", kind="manual"),
            nodes=[
                GraphNode(
                    id="fetch",
                    kind="http_request",
                    params={"url": "https://api.example.com"},
                ),
                GraphNode(
                    id="shape",
                    kind="set",
                    params={"fields": {"token": {"ref": "node.fetch.access_token"}}},
                ),
            ],
            edges=[
                GraphEdge(source="t", target="fetch"),
                GraphEdge(source="fetch", target="shape"),
            ],
        ),
    )

    shape = _node_by_id(compiled, "shape")
    value = shape.parameters["assignments"]["assignments"][0]["value"]
    assert value == "={{$('HTTP Request').first().json[\"access_token\"]}}"


def test_unknown_kind_raises_compile_error():
    with pytest.raises(WorkflowGraphCompileError):
        compile_workflow_graph(
            "Bad",
            WorkflowGraph(
                trigger=GraphNode(id="t", kind="manual"),
                nodes=[GraphNode(id="x", kind="totally_unknown")],
                edges=[GraphEdge(source="t", target="x")],
            ),
        )


def test_chat_model_as_main_node_is_rejected():
    """A chat model must attach to an ai_agent, never stand alone in main flow."""
    with pytest.raises(WorkflowGraphCompileError, match="sub-node"):
        compile_workflow_graph(
            "Bad AI",
            WorkflowGraph(
                trigger=GraphNode(id="t", kind="webhook"),
                nodes=[
                    GraphNode(id="llm", kind="openai_chat", params={"model": "gpt-4o-mini"}),
                    GraphNode(
                        id="mail",
                        kind="gmail.send",
                        params={"to": "a@b.co", "subject": "x", "message": "y"},
                    ),
                ],
                edges=[
                    GraphEdge(source="t", target="llm"),
                    GraphEdge(source="llm", target="mail"),
                ],
            ),
        )


def test_edge_to_sub_node_is_rejected():
    with pytest.raises(WorkflowGraphCompileError):
        compile_workflow_graph(
            "Bad",
            WorkflowGraph(
                trigger=GraphNode(id="t", kind="manual"),
                nodes=[
                    GraphNode(id="agent", kind="ai_agent"),
                    GraphNode(
                        id="llm",
                        kind="openai_chat",
                        attached_to="agent",
                        role="language_model",
                    ),
                ],
                edges=[
                    GraphEdge(source="t", target="agent"),
                    GraphEdge(source="agent", target="llm"),
                ],
            ),
        )
