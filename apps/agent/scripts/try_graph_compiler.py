"""Smoke-test the WorkflowGraph compiler against the real node registry.

Compiles a few representative graphs (including the AI Agent + chat model case
that previously crashed) and prints the resulting n8n nodes/connections plus
the validation verdict. No n8n or Firestore needed.

Run:
    cd apps/agent
    python scripts/try_graph_compiler.py            # compile + validate + print
    python scripts/try_graph_compiler.py --import    # also POST to live n8n

The --import flag requires a running n8n reachable via the agent's settings
(N8N_BASE_URL / N8N_API_KEY).
"""

import asyncio
import json
import sys
from pathlib import Path

# Make `src` importable when run from apps/agent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.schemas import GraphEdge, GraphNode, WorkflowGraph  # noqa: E402
from src.agent.tools.graph_compiler import compile_workflow_graph  # noqa: E402
from src.agent.validation import validate_workflow_payload  # noqa: E402
from src.registry import registry  # noqa: E402

_NODES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "packages"
    / "n8n-registry"
    / "data"
    / "nodes.json"
)


def _ai_agent_graph() -> WorkflowGraph:
    """The previously-crashing scenario: chat-triggered AI agent + chat model."""

    return WorkflowGraph(
        trigger=GraphNode(id="trigger", kind="chat"),
        nodes=[
            GraphNode(
                id="agent",
                kind="ai_agent",
                params={
                    "text": {"ref": "item.chatInput"},
                    "system_prompt": "You are a helpful assistant. Answer concisely.",
                },
            ),
            GraphNode(
                id="model",
                kind="openai_chat",
                attached_to="agent",
                role="language_model",
                params={"model": "gpt-4o-mini"},
            ),
            GraphNode(
                id="memory",
                kind="memory_buffer",
                attached_to="agent",
                role="memory",
            ),
        ],
        edges=[GraphEdge(source="trigger", target="agent")],
    )


def _http_if_graph() -> WorkflowGraph:
    """HTTP fetch -> IF branch -> two outcomes; exercises true/false ports."""

    return WorkflowGraph(
        trigger=GraphNode(id="t", kind="schedule", params={"time": "09:00"}),
        nodes=[
            GraphNode(
                id="fetch",
                kind="http_request",
                params={"url": "https://api.github.com/repos/n8n-io/n8n", "method": "GET"},
            ),
            GraphNode(
                id="gate",
                kind="if",
                params={"field": {"ref": "item.stargazers_count"}, "operator": "gt", "value": 1000},
            ),
            GraphNode(
                id="hot",
                kind="set",
                params={"fields": {"status": "popular", "stars": {"ref": "item.stargazers_count"}}},
            ),
            GraphNode(
                id="cold",
                kind="set",
                params={"fields": {"status": "quiet"}},
            ),
        ],
        edges=[
            GraphEdge(source="t", target="fetch"),
            GraphEdge(source="fetch", target="gate"),
            GraphEdge(source="gate", target="hot", on="true"),
            GraphEdge(source="gate", target="cold", on="false"),
        ],
    )


CASES = {
    "ai_agent": _ai_agent_graph,
    "http_if": _http_if_graph,
}


def _run_case(name: str, graph: WorkflowGraph) -> tuple[list, dict]:
    compiled = compile_workflow_graph(name, graph)
    node_dicts = [node.model_dump(exclude_none=True) for node in compiled.nodes]
    errors = validate_workflow_payload(compiled.nodes, compiled.connections)
    print(f"\n{'=' * 70}\nCASE: {name}\n{'=' * 70}")
    print("NODES:")
    for node in node_dicts:
        print(f"  - {node['name']:<28} {node['type']}  v{node['typeVersion']}")
    print("CONNECTIONS:")
    print(json.dumps(compiled.connections, indent=2))
    print(f"INPUT SCHEMA: {[f.name for f in compiled.input_schema]}")
    print(f"VALIDATION: {'OK' if not errors else 'ERRORS -> ' + str(errors)}")
    return node_dicts, compiled.connections


async def _import_to_n8n(name: str, node_dicts: list, connections: dict) -> None:
    from src import n8n_client

    workflow = await n8n_client.create_workflow(
        name=f"[graph-test] {name}", nodes=node_dicts, connections=connections
    )
    print(f"  → imported as n8n workflow id={workflow.id} (active={workflow.active})")


async def main() -> None:
    do_import = "--import" in sys.argv

    if _NODES_PATH.exists():
        registry.load_from_files(_NODES_PATH)
        print(f"registry loaded: {registry.node_count} nodes from {_NODES_PATH.name}")
    else:
        print("registry NOT loaded (nodes.json missing) — using block fallback typeVersions")

    for name, factory in CASES.items():
        node_dicts, connections = _run_case(name, factory())
        if do_import:
            await _import_to_n8n(name, node_dicts, connections)


if __name__ == "__main__":
    asyncio.run(main())
