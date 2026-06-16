"""Declarative block registry for the graph compiler.

Each curated workflow node maps a semantic ``kind`` to a concrete n8n node
plus the metadata the compiler needs: the exact n8n type, a fallback
typeVersion (registry is preferred), static parameters, simple semantic→n8n
param rules, branch output ports, AI sub-node ports, and an optional named
``builder`` for parameters too rich for a flat rule (Set assignments, IF/Filter
conditions, HTTP body, AI agent options).

Adding a new common node is a data change here, not new compiler code. Nodes
outside this registry still work through the generic ``n8n:<type>`` fallback in
``graph_compiler``.
"""

from dataclasses import dataclass, field
from typing import Any

# Sentinel so ParamRule can distinguish "no value" from an explicit None.
UNSET: Any = object()

# Default semantic role -> n8n connection port for AI sub-nodes. A Block may
# override via ``sub_ports``; otherwise these apply (also used by the generic
# fallback so attaching a model/tool to any agent-like node wires correctly).
ROLE_PORTS: dict[str, str] = {
    "language_model": "ai_languageModel",
    "model": "ai_languageModel",
    "tool": "ai_tool",
    "memory": "ai_memory",
    "output_parser": "ai_outputParser",
    "embedding": "ai_embedding",
    "vector_store": "ai_vectorStore",
    "document": "ai_document",
    "text_splitter": "ai_textSplitter",
}


@dataclass(frozen=True)
class ParamRule:
    """How one semantic param is placed into n8n ``parameters``.

    ``path`` is a dotted target path. ``source`` is the semantic key (defaults
    to the rule key). ``expr`` wraps the value through the expression engine
    (ref resolution). ``rl_mode`` wraps it as an n8n resourceLocator.
    """

    path: str
    source: str | None = None
    expr: bool = False
    default: Any = UNSET
    const: Any = UNSET
    required: bool = False
    rl_mode: str | None = None
    enum_map: dict[str, str] | None = None


@dataclass(frozen=True)
class Block:
    """Curated mapping from a semantic ``kind`` to an n8n node."""

    kind: str
    n8n_type: str
    is_trigger: bool = False
    base_name: str | None = None
    type_version: int | float | None = None  # fallback when registry lacks it
    static: dict[str, Any] = field(default_factory=dict)
    params: dict[str, ParamRule] = field(default_factory=dict)
    builder: str | None = None
    output_ports: dict[str, int] = field(default_factory=dict)
    sub_ports: dict[str, str] = field(default_factory=dict)
    # AI sub-nodes (chat models, memory, tools) have no usable main I/O; they
    # only work attached_to an agent/chain via an ai_* port. They must never be
    # placed in the main flow or appear in edges.
    sub_only: bool = False


_LANGCHAIN = "@n8n/n8n-nodes-langchain"


BLOCKS: dict[str, Block] = {
    # --- Triggers -------------------------------------------------------
    "manual": Block(
        kind="manual",
        n8n_type="n8n-nodes-base.manualTrigger",
        is_trigger=True,
        base_name="When clicking 'Test workflow'",
        type_version=1,
    ),
    "webhook": Block(
        kind="webhook",
        n8n_type="n8n-nodes-base.webhook",
        is_trigger=True,
        base_name="Webhook",
        type_version=2,
        builder="trigger_webhook",
    ),
    "on_demand": Block(
        kind="on_demand",
        n8n_type="n8n-nodes-base.webhook",
        is_trigger=True,
        base_name="Webhook",
        type_version=2,
        builder="trigger_webhook",
    ),
    "schedule": Block(
        kind="schedule",
        n8n_type="n8n-nodes-base.scheduleTrigger",
        is_trigger=True,
        base_name="Schedule",
        type_version=1.2,
        builder="trigger_schedule",
    ),
    "chat": Block(
        kind="chat",
        n8n_type=f"{_LANGCHAIN}.chatTrigger",
        is_trigger=True,
        base_name="When chat message received",
        type_version=1.1,
        static={"options": {}},
    ),
    # --- Core actions ---------------------------------------------------
    "http_request": Block(
        kind="http_request",
        n8n_type="n8n-nodes-base.httpRequest",
        base_name="HTTP Request",
        type_version=4.2,
        builder="http_request",
    ),
    "set": Block(
        kind="set",
        n8n_type="n8n-nodes-base.set",
        base_name="Edit Fields",
        type_version=3.4,
        builder="set_fields",
    ),
    "edit_fields": Block(
        kind="edit_fields",
        n8n_type="n8n-nodes-base.set",
        base_name="Edit Fields",
        type_version=3.4,
        builder="set_fields",
    ),
    "if": Block(
        kind="if",
        n8n_type="n8n-nodes-base.if",
        base_name="If",
        type_version=2.2,
        builder="if_conditions",
        output_ports={"true": 0, "false": 1},
    ),
    "filter": Block(
        kind="filter",
        n8n_type="n8n-nodes-base.filter",
        base_name="Filter",
        type_version=2.2,
        builder="filter_conditions",
    ),
    "code": Block(
        kind="code",
        n8n_type="n8n-nodes-base.code",
        base_name="Code",
        type_version=2,
        builder="code",
    ),
    "merge": Block(
        kind="merge",
        n8n_type="n8n-nodes-base.merge",
        base_name="Merge",
        type_version=3,
        static={"mode": "combine", "options": {}},
    ),
    "no_op": Block(
        kind="no_op",
        n8n_type="n8n-nodes-base.noOp",
        base_name="No Operation",
        type_version=1,
    ),
    # --- AI -------------------------------------------------------------
    "ai_agent": Block(
        kind="ai_agent",
        n8n_type=f"{_LANGCHAIN}.agent",
        base_name="AI Agent",
        type_version=1.9,
        builder="ai_agent",
    ),
    "openai_chat": Block(
        kind="openai_chat",
        n8n_type=f"{_LANGCHAIN}.lmChatOpenAi",
        base_name="OpenAI Chat Model",
        type_version=1.2,
        builder="chat_model",
        sub_only=True,
    ),
    "anthropic_chat": Block(
        kind="anthropic_chat",
        n8n_type=f"{_LANGCHAIN}.lmChatAnthropic",
        base_name="Anthropic Chat Model",
        type_version=1.3,
        builder="chat_model",
        sub_only=True,
    ),
    "memory_buffer": Block(
        kind="memory_buffer",
        n8n_type=f"{_LANGCHAIN}.memoryBufferWindow",
        base_name="Window Buffer Memory",
        type_version=1.3,
        static={},
        sub_only=True,
    ),
    # --- Integrations (reuse plan compiler builders) --------------------
    "gmail.send": Block(
        kind="gmail.send",
        n8n_type="n8n-nodes-base.gmail",
        base_name="Gmail",
        type_version=2.1,
        builder="gmail_send",
    ),
    "sheets.read_rows": Block(
        kind="sheets.read_rows",
        n8n_type="n8n-nodes-base.googleSheets",
        base_name="Google Sheets",
        type_version=4.7,
        builder="sheets_read",
    ),
    "sheets.row.append": Block(
        kind="sheets.row.append",
        n8n_type="n8n-nodes-base.googleSheets",
        base_name="Google Sheets Append",
        type_version=4.7,
        builder="sheets_append",
    ),
}


def get_block(kind: str) -> Block | None:
    """Return the curated block for a kind, or None when not curated."""

    return BLOCKS.get(kind)


def catalog_lines() -> list[str]:
    """Compact ``kind — n8n node`` lines for the system prompt catalog."""

    return [f"{block.kind} ({block.n8n_type})" for block in BLOCKS.values()]
