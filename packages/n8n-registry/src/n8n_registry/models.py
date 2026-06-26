from dataclasses import dataclass, field


@dataclass
class NodeInfo:
    type_name: str          # "n8n-nodes-base.gmail"
    display_name: str       # "Gmail"
    description: str        # "Send and receive emails..."
    type_version: int       # Latest stable version (e.g. 2)
    credentials: list[str]  # ["gmailOAuth2"]
    category: str           # "Communication"
    is_trigger: bool        # True for trigger nodes
    resources: list[str] = field(default_factory=list)   # ["message", "draft", ...]
    operations: dict[str, list[str]] = field(default_factory=dict)  # {"message": ["send", ...]}
    key_properties: list[dict] = field(default_factory=list)  # condensed top-level params
    search_text: str = ""   # pre-built search string (display_name + description)


@dataclass
class WorkflowTemplate:
    id: int | str
    name: str
    description: str
    categories: list[str] = field(default_factory=list)
    node_types: list[str] = field(default_factory=list)  # used node type strings
    workflow_json: dict = field(default_factory=dict)
    search_text: str = ""   # pre-built search string


@dataclass
class CredentialTypeInfo:
    name: str                       # "anthropicApi"
    display_name: str               # "Anthropic"
    icon_url: str = ""              # "icons/anthropic.svg"
    documentation_url: str = ""
    properties: list[dict] = field(default_factory=list)  # raw n8n INodeProperties
    extends: list[str] = field(default_factory=list)
    generic_auth: bool = False      # n8n genericAuth (httpHeaderAuth etc.)
    is_oauth: bool = False
