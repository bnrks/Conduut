from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeContract:
    key: str
    type_name: str
    type_version: int | float
    resource: str | None = None
    operation: str | None = None
    key_properties: list[dict[str, Any]] = field(default_factory=list)
    search_text: str = ""


@dataclass
class NodeCard:
    type_name: str
    display_name: str
    description: str
    type_version: int | float
    category: str
    is_trigger: bool
    credentials: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    contract_keys: list[str] = field(default_factory=list)
    default_contract_key: str | None = None
    search_text: str = ""


@dataclass
class WorkflowCard:
    id: int | str
    name: str
    summary: str
    description: str
    source: str = "n8n_community"
    fetched_at: str = ""
    content_hash: str = ""
    intents: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    node_types: list[str] = field(default_factory=list)
    node_versions: list[dict[str, Any]] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    trigger_types: list[str] = field(default_factory=list)
    topology: dict[str, Any] = field(default_factory=dict)
    node_roles: list[dict[str, str]] = field(default_factory=list)
    credential_requirements: list[str] = field(default_factory=list)
    input_fields: list[str] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)
    identity_strategy: dict[str, Any] = field(default_factory=dict)
    idempotency_strategy: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)
    risk_level: str = "low"
    risk_flags: list[str] = field(default_factory=list)
    cardinality_invariants: list[str] = field(default_factory=list)
    rerun_invariants: list[str] = field(default_factory=list)
    compatibility: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    sandbox: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    node_count: int = 0
    trigger_count: int = 0
    fingerprint: str = ""
    source_url: str = ""
    search_text: str = ""


@dataclass
class NodeInfo:
    type_name: str  # "n8n-nodes-base.gmail"
    display_name: str  # "Gmail"
    description: str  # "Send and receive emails..."
    type_version: int | float  # Latest stable version (e.g. 2, 3.4)
    credentials: list[str]  # ["gmailOAuth2"]
    category: str  # "Communication"
    is_trigger: bool  # True for trigger nodes
    resources: list[str] = field(default_factory=list)  # ["message", "draft", ...]
    operations: dict[str, list[str]] = field(default_factory=dict)  # {"message": ["send", ...]}
    output_types: list[str] = field(default_factory=list)  # ["main", "main", ...]
    output_names: list[str] = field(default_factory=list)  # ["true", "false", ...]
    key_properties: list[dict] = field(default_factory=list)  # condensed top-level params
    contracts: list[NodeContract] = field(default_factory=list)
    card: NodeCard | None = None
    search_text: str = ""  # pre-built search string (display_name + description)


@dataclass
class WorkflowTemplate:
    id: int | str
    name: str
    description: str
    categories: list[str] = field(default_factory=list)
    node_types: list[str] = field(default_factory=list)  # used node type strings
    workflow_json: dict = field(default_factory=dict)
    card: WorkflowCard | None = None
    search_text: str = ""  # pre-built search string


@dataclass
class CredentialTypeInfo:
    name: str  # "anthropicApi"
    display_name: str  # "Anthropic"
    icon_url: str = ""  # "icons/anthropic.svg"
    documentation_url: str = ""
    properties: list[dict] = field(default_factory=list)  # raw n8n INodeProperties
    extends: list[str] = field(default_factory=list)
    generic_auth: bool = False  # n8n genericAuth (httpHeaderAuth etc.)
    is_oauth: bool = False
