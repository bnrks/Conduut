"""Typed data structures used by the Pydantic AI agent runtime."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()


class WorkflowNode(BaseModel):
    """Minimal n8n node shape. Boilerplate (id/typeVersion/position) is optional.

    The model writes compact JSON (name/type/parameters) and the repair layer
    (``agent.repair``) fills the rest deterministically before validation.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None
    typeVersion: int | float | None = None
    position: list[int | float] | None = Field(default=None, min_length=2, max_length=2)


class WorkflowPreviewData(BaseModel):
    id: str | None = None
    name: str
    nodeCount: int
    status: Literal["active", "inactive"]


class WorkflowPreviewAttachment(BaseModel):
    type: Literal["workflow_preview"] = "workflow_preview"
    data: WorkflowPreviewData


class ArtifactPreviewTable(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    totalRows: int | None = None


class ArtifactPreviewMessage(BaseModel):
    messageId: str | None = None
    threadId: str | None = None
    fromEmail: str | None = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str | None = None
    snippet: str | None = None
    bodyPreview: str | None = None
    labels: list[str] = Field(default_factory=list)
    query: str | None = None
    resultCount: int | None = None


class ArtifactPreviewData(BaseModel):
    service: Literal["google_sheets", "gmail"]
    title: str
    description: str | None = None
    url: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    table: ArtifactPreviewTable | None = None
    message: ArtifactPreviewMessage | None = None


class ArtifactPreviewAttachment(BaseModel):
    type: Literal["artifact_preview"] = "artifact_preview"
    data: ArtifactPreviewData


class WorkflowInputField(BaseModel):
    name: str
    label: str
    type: Literal["string", "email", "textarea"] = "string"
    required: bool = True
    placeholder: str | None = None


class WorkflowOutputField(BaseModel):
    name: str
    label: str
    format: Literal[
        "text",
        "longtext",
        "number",
        "currency",
        "datetime",
        "url",
        "email",
        "boolean",
        "list",
    ] = "text"


class PlatformActionPlan(BaseModel):
    """Direct platform action request executed through connected app APIs."""

    action: Literal[
        "gmail.message.send",
        "gmail.message.search",
        "gmail.message.get",
        "gmail.message.mark_read",
        "gmail.message.mark_unread",
        "gmail.message.archive",
        "gmail.message.trash",
        "gmail.message.label",
        "sheets.spreadsheet.create",
        "sheets.sheet.create",
        "sheets.sheet.delete",
        "sheets.range.read",
        "sheets.range.update",
        "sheets.range.clear",
        "sheets.row.append",
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class PlatformActionResult(BaseModel):
    """User-safe summary returned after a direct platform action."""

    success: bool
    action: str
    capability: str
    status: str
    targetResource: str | None = None
    data: dict[str, Any] | None = None
    error: str | None = None
    permissionPack: str | None = None
    riskLevel: str | None = None
    artifacts: list[ArtifactPreviewData] = Field(default_factory=list)


class CredentialFieldOption(BaseModel):
    label: str
    value: str


class CredentialFieldCondition(BaseModel):
    field: str
    values: list[Any] = Field(default_factory=list)


class CredentialField(BaseModel):
    name: str
    label: str
    type: str = "string"  # text | password | json | number | boolean | options
    required: bool = False
    default: Any = None
    placeholder: str | None = None
    description: str | None = None
    advanced: bool = False
    options: list[CredentialFieldOption] | None = None
    showWhen: CredentialFieldCondition | None = None


class CredentialTypeOption(BaseModel):
    type: str
    label: str
    fields: list[CredentialField]


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
    # When non-empty, the credential card shows a type picker (generic HTTP
    # auth). host is the URL host extracted from the node, prefilled + editable.
    allowedTypes: list[CredentialTypeOption] = Field(default_factory=list)
    host: str | None = None
    # Draft credential (agent-prepared): the card is secret-only and submits to
    # the finalize endpoint; sourceUrl is the research provenance shown to the user.
    draftId: str | None = None
    sourceUrl: str | None = None
    # "type" -> credential matched/saved by n8n credential type (e.g. openAiApi),
    # not by host. The card hides the host field and submits match_kind="type".
    matchKind: str | None = None
    iconUrl: str | None = None


class CredentialRequestAttachment(BaseModel):
    type: Literal["credential_request"] = "credential_request"
    data: CredentialRequestData


class OAuthPromptData(BaseModel):
    service: str
    description: str
    authorizePath: str = "/api/oauth/google/authorize?service=gmail"
    returnTo: str = "/dashboard/connections"
    iconUrl: str | None = None
    requiredCapabilities: list[str] = Field(default_factory=list)
    permissionPack: str | None = None
    riskLevel: str | None = None


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


class WorkflowResultPresentationField(BaseModel):
    label: str
    format: str = "text"
    value: Any = None


class WorkflowResultPresentation(BaseModel):
    title: str | None = None
    fields: list[WorkflowResultPresentationField] = Field(default_factory=list)


class WorkflowRunResultData(BaseModel):
    workflowId: str
    executionId: str | None = None
    status: str
    summary: str
    failedNode: str | None = None
    error: str | None = None
    response: dict[str, Any] | None = None
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[ArtifactPreviewData] = Field(default_factory=list)
    presentation: WorkflowResultPresentation | None = None


class WorkflowBatchRowResultData(BaseModel):
    rowNumber: int
    status: str
    executionId: str | None = None
    summary: str | None = None
    error: str | None = None
    artifacts: list[ArtifactPreviewData] = Field(default_factory=list)


class WorkflowBatchRunResultData(BaseModel):
    workflowId: str
    batchRunId: str
    status: str
    totalRows: int
    succeeded: int
    failed: int
    skipped: int
    results: list[WorkflowBatchRowResultData] = Field(default_factory=list)


AgentAttachment = (
    WorkflowPreviewAttachment
    | ArtifactPreviewAttachment
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
    platform_resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    awaiting_user_input: bool = False
    # Workflows already created in this conversation (name -> id), rebuilt from
    # history each run. create_workflow reuses these to update instead of
    # creating duplicate workflows when the agent rebuilds the same automation.
    conversation_workflows: dict[str, str] = field(default_factory=dict)
    # Sandbox test repair attempts per workflow id (bounds the self-repair loop).
    workflow_test_attempts: dict[str, int] = field(default_factory=dict)
    # Real-execution failures per workflow id (bounds the execute retry loop so a
    # workflow that keeps failing surfaces to the user instead of thrashing budget).
    workflow_execution_failures: dict[str, int] = field(default_factory=dict)
    # True once a real external action (workflow execution / platform action) has
    # run this attempt — the reliability guard must not retry from scratch then.
    real_action_executed: bool = False
    # Per-conversation platform self-awareness state (connected services, saved
    # credentials, existing automations). Set by runner.run; read by the agent's
    # dynamic @instructions. Typed Any to avoid a schemas<->platform_state import
    # cycle; concretely a platform_state.UserPlatformState | None.
    platform_state: Any = None

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
