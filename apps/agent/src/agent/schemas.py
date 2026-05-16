"""Typed data structures used by the Pydantic AI agent runtime."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()


class WorkflowNode(BaseModel):
    """Minimal n8n node shape required before writing a workflow."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: str
    typeVersion: int | float
    position: list[int | float] = Field(min_length=2, max_length=2)
    parameters: dict[str, Any]


class WorkflowPreviewData(BaseModel):
    id: str | None = None
    name: str
    nodeCount: int
    status: Literal["active", "inactive"]


class WorkflowPreviewAttachment(BaseModel):
    type: Literal["workflow_preview"] = "workflow_preview"
    data: WorkflowPreviewData


class WorkflowInputField(BaseModel):
    name: str
    label: str
    type: Literal["string", "email", "textarea"] = "string"
    required: bool = True
    placeholder: str | None = None


class WorkflowTriggerSpec(BaseModel):
    """Small workflow intent trigger representation compiled into n8n JSON."""

    kind: Literal["on_demand", "schedule"]
    frequency: Literal["daily"] = "daily"
    time: str | None = None


class WorkflowStepSpec(BaseModel):
    """Small workflow intent step representation compiled into n8n JSON."""

    id: str | None = None
    capability: Literal["send_email", "read_sheet_rows", "filter_items"]
    service: Literal["gmail", "google_sheets", "core"]
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowSpec(BaseModel):
    """Workflow IR used before deterministic n8n JSON compilation."""

    trigger: WorkflowTriggerSpec
    steps: list[WorkflowStepSpec] = Field(min_length=1)


class CredentialField(BaseModel):
    name: str
    label: str
    type: str = "string"
    required: bool = False


class CredentialRequestData(BaseModel):
    workflowId: str
    workflowName: str | None = None
    nodeName: str
    service: str
    credentialType: str
    credentialName: str
    fields: list[CredentialField]
    submitPath: str
    description: str


class CredentialRequestAttachment(BaseModel):
    type: Literal["credential_request"] = "credential_request"
    data: CredentialRequestData


class OAuthPromptData(BaseModel):
    service: str
    description: str
    authorizePath: str = "/api/oauth/google/authorize?service=gmail"
    returnTo: str = "/dashboard/connections"
    iconUrl: str | None = None


class OAuthPromptAttachment(BaseModel):
    type: Literal["oauth_prompt"] = "oauth_prompt"
    data: OAuthPromptData


class UserInputChoice(BaseModel):
    label: str
    value: str | None = None


class UserInputRequestData(BaseModel):
    question: str
    missingFields: list[str] = Field(default_factory=list)
    choices: list[UserInputChoice] = Field(default_factory=list)
    allowSkip: bool = False
    reason: str | None = None


class UserInputRequestAttachment(BaseModel):
    type: Literal["user_input_request"] = "user_input_request"
    data: UserInputRequestData


class WorkflowRunResultData(BaseModel):
    workflowId: str
    executionId: str | None = None
    status: str
    summary: str
    failedNode: str | None = None
    error: str | None = None
    response: dict[str, Any] | None = None
    outputs: list[dict[str, Any]] = Field(default_factory=list)


AgentAttachment = (
    WorkflowPreviewAttachment
    | CredentialRequestAttachment
    | OAuthPromptAttachment
    | UserInputRequestAttachment
)


AgentEvent = tuple[str, dict[str, Any]]


@dataclass
class AgentDeps:
    """Runtime-only dependencies passed to Pydantic AI tools."""

    user_id: str
    conversation_id: str
    event_queue: asyncio.Queue[AgentEvent]
    attachments: list[dict[str, Any]] = field(default_factory=list)
    awaiting_user_input: bool = False

    async def emit_tool_call(self, tool: str) -> None:
        log.info(
            "agent_tool_call_started",
            tool=tool,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
        )
        await self.event_queue.put(
            ("tool_call", {"tool": tool, "conversation_id": self.conversation_id})
        )

    async def emit_attachment(self, attachment: AgentAttachment) -> None:
        payload = attachment.model_dump(exclude_none=True)
        if payload in self.attachments:
            return
        self.attachments.append(payload)
        log.info(
            "agent_attachment_emitted",
            attachment_type=payload["type"],
            user_id=self.user_id,
            conversation_id=self.conversation_id,
        )
        await self.event_queue.put(
            (
                "attachment",
                {
                    "conversation_id": self.conversation_id,
                    "type": payload["type"],
                    "data": payload["data"],
                },
            )
        )


def dump_workflow_nodes(nodes: list[WorkflowNode]) -> list[dict[str, Any]]:
    """Convert typed workflow nodes back to n8n-compatible dictionaries."""

    return [node.model_dump(exclude_none=True) for node in nodes]
