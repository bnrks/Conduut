"""Conversation-history reconstruction for the agent runner.

Pure functions that turn stored conversation messages into Pydantic AI message
history and rebuild per-conversation context (workflows, platform resources,
user-input answers) from prior assistant attachments. Extracted from
``runner.py`` and re-imported there so ``runner.<name>`` access (and the tests
that patch it) keep working unchanged.
"""

import re

from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)


def _history_from_store_messages(messages: list[dict]) -> tuple[str, list[ModelMessage]]:
    if not messages:
        return "", []

    latest_message = {
        **messages[-1],
        "content": _content_with_attachment_context(messages[-1]),
    }
    user_prompt = _content_with_user_input_answer_context(
        latest_message,
        _user_input_request_context(messages[-2]) if len(messages) > 1 else None,
    )
    prior_messages = messages[:-1]
    if not prior_messages:
        return user_prompt, []

    history: list[ModelMessage] = []
    pending_user_input_request: str | None = None

    for message in prior_messages:
        role = message.get("role")
        content = _content_with_attachment_context(message)
        if role == "user":
            content = _content_with_user_input_answer_context(
                {**message, "content": content},
                pending_user_input_request,
            )
            pending_user_input_request = None
        if not content:
            continue
        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role in ("assistant", "agent"):
            history.append(ModelResponse(parts=[TextPart(content=content)]))
            pending_user_input_request = _user_input_request_context(message)

    return user_prompt, history


def _conversation_workflows_from_messages(messages: list[dict]) -> dict[str, str]:
    """Map workflow name -> id from prior workflow_preview attachments so the
    agent reuses (updates) the same workflow instead of creating duplicates."""

    workflows: dict[str, str] = {}
    for message in messages:
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict) or attachment.get("type") != "workflow_preview":
                continue
            data = attachment.get("data")
            if not isinstance(data, dict):
                continue
            name = data.get("name")
            workflow_id = data.get("id")
            if name and workflow_id:
                workflows[str(name)] = str(workflow_id)
    return workflows


def _platform_resources_from_messages(messages: list[dict]) -> dict[str, dict[str, str]]:
    resources: dict[str, dict[str, str]] = {}
    for message in messages:
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict) or attachment.get("type") != "artifact_preview":
                continue
            data = attachment.get("data")
            if not isinstance(data, dict) or data.get("service") != "google_sheets":
                continue
            source = data.get("source") if isinstance(data.get("source"), dict) else {}
            spreadsheet_id = source.get("spreadsheetId")
            if not spreadsheet_id:
                continue
            resource = resources.setdefault("google_sheets", {})
            resource["spreadsheet_id"] = str(spreadsheet_id)
            if data.get("url"):
                resource["spreadsheet_url"] = str(data["url"])
            range_label = source.get("range")
            if range_label:
                resource["sheet_name"] = str(range_label).split("!", 1)[0].strip("'")
    return resources


def _user_input_request_context(message: dict | None) -> str | None:
    if not message or message.get("role") not in ("assistant", "agent"):
        return None
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "user_input_request":
            continue
        data = attachment.get("data")
        if not isinstance(data, dict):
            continue
        question = data.get("question")
        missing_fields = data.get("missingFields")
        return f"user_input_request question={question} missingFields={missing_fields}"
    return None


def _content_with_user_input_answer_context(
    message: dict,
    pending_request_context: str | None,
) -> str:
    content = str(message.get("content") or "")
    if not content or not pending_request_context:
        return content
    return (
        f"{content}\n\n"
        "[Conduut internal context: this user message answers the previous "
        f"{pending_request_context}. Treat this answer as accumulated task information and "
        "do not ask for the same missing field again unless the answer is ambiguous.]"
    )


def _content_with_attachment_context(message: dict) -> str:
    content = str(message.get("content") or "")
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return content

    context_items: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        data = attachment.get("data")
        if not isinstance(data, dict):
            continue
        attachment_type = attachment.get("type")
        if attachment_type == "workflow_preview":
            workflow_id = data.get("id")
            name = data.get("name")
            status = data.get("status")
            if workflow_id:
                context_items.append(
                    f"workflow_preview id={workflow_id} name={name} status={status}"
                )
        elif attachment_type == "workflow_run_result":
            workflow_id = data.get("workflowId")
            execution_id = data.get("executionId")
            status = data.get("status")
            if workflow_id:
                context_items.append(
                    "workflow_run "
                    f"workflowId={workflow_id} "
                    f"executionId={execution_id} "
                    f"status={status}"
                )
        elif attachment_type == "execution_reference":
            execution_id = data.get("executionId")
            workflow_id = data.get("workflowId")
            status = data.get("status")
            intent = data.get("intent")
            if execution_id:
                context_items.append(
                    "execution_reference "
                    f"executionId={execution_id} "
                    f"workflowId={workflow_id} "
                    f"status={status} "
                    f"intent={intent}. "
                    "Inspect this exact execution before changing anything. Read the same "
                    "workflow and update that workflow only when the failure is caused by its "
                    "definition; credential, quota, external-service, or user-data failures "
                    "must be explained without changing the workflow"
                )
        elif attachment_type == "artifact_preview":
            title = data.get("title")
            service = data.get("service")
            source = data.get("source")
            if title:
                context_items.append(
                    f"artifact_preview service={service} title={title} source={source}"
                )
        elif attachment_type == "user_input_request":
            question = data.get("question")
            missing_fields = data.get("missingFields")
            if question:
                context_items.append(
                    f"user_input_request question={question} missingFields={missing_fields}"
                )

    if not context_items:
        return content

    return (
        f"{content}\n\n"
        "[Conduut internal context for future tool calls: " + "; ".join(context_items) + "]"
    )


# `_content_with_*_context` appends "[Conduut internal context ...]" to prior
# messages as model INPUT. The model sometimes imitates that pattern and emits it
# as visible text; it is scaffolding and must never reach the user, so we strip it
# (and anything after it — it is always appended at the message tail) from any
# content we display or persist. See strip_internal_context usage in the replay
# and persist paths.
_INTERNAL_CONTEXT_RE = re.compile(r"\s*\[Conduut internal context.*", re.DOTALL)


def strip_internal_context(text: str) -> str:
    """Remove an echoed internal-context annotation from model-visible output."""

    return _INTERNAL_CONTEXT_RE.sub("", text)
