"""Stable execution-history service boundary.

The MVP resolves every user to the shared n8n client. Keeping ``user_id`` in
this public contract makes the later per-user n8n provider switch local to this
module instead of leaking infrastructure details into routes, chat, or tools.
"""

from __future__ import annotations

import re
from datetime import datetime

import structlog
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent.schemas import WorkflowRunResultData
from src.agent.tools.execution import _summarize_execution, execution_evidence_envelope
from src.agent.tools.read_after_write import verify_sheets_read_after_write

log = structlog.get_logger()

_MAX_PUBLIC_TEXT = 500
_MAX_NODE_NAME = 160
_SECRET_HEADER_PATTERN = re.compile(
    r"(?i)\b((?:authorization|proxy-authorization|x-api-key|api-key|apikey)"
    r"\s*[:=]\s*)([^\r\n,;—]+)"
)
_COOKIE_HEADER_PATTERN = re.compile(r"(?i)\b((?:cookie|set-cookie)\s*[:=]\s*)([^\r\n,—]+)")
_AUTH_SCHEME_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[^\s,;]+")
_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"token|secret|password)=)([^&#\s]+)"
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|authorization|client[_-]?secret|password|"
    r"refresh[_-]?token|access[_-]?token|token|secret)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\"',;\s}\]]+)"
)


class ExecutionNotFoundError(LookupError):
    """The requested execution does not exist in the user's n8n provider."""


class RunListItem(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    status: str
    mode: str | None = None
    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class RunDetail(RunListItem):
    summary: str
    failed_node: str | None = None
    error: str | None = None


class RunPage(BaseModel):
    executions: list[RunListItem]
    next_cursor: str | None = None


def _safe_text(value: object, *, max_chars: int = _MAX_PUBLIC_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    text = _SECRET_VALUE_PATTERN.sub(r"\1[REDACTED]", text)
    text = _SECRET_HEADER_PATTERN.sub(r"\1[REDACTED]", text)
    text = _COOKIE_HEADER_PATTERN.sub(r"\1[REDACTED]", text)
    text = _AUTH_SCHEME_PATTERN.sub(r"\1 [REDACTED]", text)
    text = _SECRET_QUERY_PATTERN.sub(r"\1[REDACTED]", text)
    if len(text) > max_chars:
        text = f"{text[:max_chars]}..."
    return text


def _duration_ms(started_at: str, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((finish - start).total_seconds() * 1000))


def _fallback_workflow_name(workflow_id: str) -> str:
    return f"Workflow {workflow_id}" if workflow_id else "Unknown workflow"


def _normalized_status(value: object) -> str:
    status = str(value or "unknown").lower()
    return "error" if status in {"error", "failed", "crashed"} else status


def _ownership_value(n8n: object) -> str:
    return str(getattr(n8n, "ownership", "shared_dev") or "shared_dev")


async def _owned_workflow_ids(user_id: str) -> set[str]:
    return set((await store.get_all_workflow_metadata(user_id)).keys())


async def _workflow_names(n8n=n8n_client) -> dict[str, str]:
    try:
        workflows = await n8n.list_workflows()
    except n8n_client.N8nApiError as exc:
        # Execution history remains useful if a workflow was deleted between
        # the two reads or the name lookup fails independently.
        log.warning(
            "execution_workflow_names_unavailable",
            status_code=exc.status_code,
            error=exc.message,
        )
        return {}
    return {workflow.id: workflow.name for workflow in workflows}


async def _execution_workflow_context(
    raw: dict[str, object],
    *,
    workflow_id: str,
    n8n=n8n_client,
) -> tuple[dict[str, object] | None, str]:
    workflow_data = raw.get("workflowData")
    if isinstance(workflow_data, dict) and isinstance(workflow_data.get("nodes"), list):
        return workflow_data, "embedded"
    if workflow_id:
        try:
            workflow = await n8n.get_workflow(workflow_id)
        except n8n_client.N8nApiError as exc:
            log.warning(
                "execution_workflow_context_unavailable",
                workflow_id=workflow_id,
                status_code=exc.status_code,
                error=exc.message,
            )
            return None, "missing"
        if isinstance(workflow, dict):
            return workflow, "current"
    return None, "missing"


async def list_runs(
    user_id: str,
    *,
    workflow_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
    n8n=n8n_client,
) -> RunPage:
    """List a sanitized execution page for one user.

    ``user_id`` is intentionally required even though the MVP currently uses a
    shared provider. It becomes the provider-resolution key before production.
    """

    if not user_id:
        raise ValueError("user_id is required")
    owned_ids: set[str] | None = None
    if _ownership_value(n8n) == "shared_dev":
        owned_ids = await _owned_workflow_ids(user_id)
        if workflow_id and workflow_id not in owned_ids:
            return RunPage(executions=[], next_cursor=None)
    names = await _workflow_names(n8n)
    next_cursor = cursor
    collected: list[RunListItem] = []
    while len(collected) < limit:
        page = await n8n.list_executions_page(
            workflow_id=workflow_id,
            status=status,
            cursor=next_cursor,
            limit=limit,
        )
        filtered_on_page = False
        for execution in page.executions:
            if owned_ids is not None and execution.workflow_id not in owned_ids:
                filtered_on_page = True
                continue
            collected.append(
                RunListItem(
                    id=execution.id,
                    workflow_id=execution.workflow_id,
                    workflow_name=names.get(
                        execution.workflow_id,
                        _fallback_workflow_name(execution.workflow_id),
                    ),
                    status=_normalized_status(execution.status),
                    mode=execution.mode,
                    started_at=execution.started_at,
                    finished_at=execution.finished_at,
                    duration_ms=_duration_ms(execution.started_at, execution.finished_at),
                )
            )
            if len(collected) >= limit:
                break
        next_cursor = page.next_cursor
        if owned_ids is None or not filtered_on_page or len(collected) >= limit or not next_cursor:
            break
    return RunPage(executions=collected[:limit], next_cursor=next_cursor)


async def get_run(user_id: str, execution_id: str, *, n8n=n8n_client) -> RunDetail:
    """Return one sanitized execution detail without raw run/output data."""

    # Local import avoids a module cycle when the agent tool factory imports
    # this service to expose inspect/list tools through the same boundary.
    from src.agent.tools.execution import _summarize_execution

    if not user_id:
        raise ValueError("user_id is required")
    try:
        raw = await n8n.get_execution_detail(execution_id)
    except n8n_client.N8nApiError as exc:
        if exc.status_code == 404:
            raise ExecutionNotFoundError(execution_id) from exc
        raise

    workflow_data = raw.get("workflowData")
    workflow_id = str(
        raw.get("workflowId")
        or (workflow_data.get("id") if isinstance(workflow_data, dict) else "")
        or ""
    )
    if _ownership_value(n8n) == "shared_dev" and workflow_id not in await _owned_workflow_ids(
        user_id
    ):
        raise ExecutionNotFoundError(execution_id)
    workflow_name = None
    if isinstance(workflow_data, dict):
        workflow_name = _safe_text(workflow_data.get("name"), max_chars=200)
    if not workflow_name:
        workflow_name = (await _workflow_names(n8n)).get(workflow_id)

    workflow_context, context_source = await _execution_workflow_context(
        raw,
        workflow_id=workflow_id,
        n8n=n8n,
    )
    summary = _summarize_execution(
        raw,
        workflow=workflow_context,
        workflow_context_source=context_source,
    )
    status = _normalized_status(raw.get("status") or summary.status)
    summary_text = summary.summary
    if status == "running":
        summary_text = "Workflow run is running."
    elif status == "waiting":
        summary_text = "Workflow run is waiting."
    elif status in {"canceled", "cancelled"}:
        summary_text = "Workflow run was canceled."
    elif status == "error" and not summary.error:
        summary_text = "Workflow run failed."

    started_at = str(raw.get("startedAt") or "")
    finished_at = raw.get("stoppedAt") or raw.get("finishedAt")
    return RunDetail(
        id=str(raw.get("id") or execution_id),
        workflow_id=workflow_id,
        workflow_name=workflow_name or _fallback_workflow_name(workflow_id),
        status=status,
        mode=str(raw["mode"]) if raw.get("mode") else None,
        started_at=started_at,
        finished_at=str(finished_at) if finished_at else None,
        duration_ms=_duration_ms(started_at, str(finished_at) if finished_at else None),
        summary=_safe_text(summary_text) or "Workflow run status is unavailable.",
        failed_node=_safe_text(summary.failedNode, max_chars=_MAX_NODE_NAME),
        error=_safe_text(summary.error),
    )


async def inspect_run(
    user_id: str,
    execution_id: str,
    *,
    n8n=n8n_client,
) -> WorkflowRunResultData:
    """Return the richer agent-only execution summary behind the same provider boundary.

    Public HTTP routes deliberately use :func:`get_run`; this result may contain
    bounded response/output previews needed by the repair agent and must not be
    exposed as the Runs API DTO.
    """

    if not user_id:
        raise ValueError("user_id is required")
    try:
        raw = await n8n.get_execution_detail(execution_id)
    except n8n_client.N8nApiError as exc:
        if exc.status_code == 404:
            raise ExecutionNotFoundError(execution_id) from exc
        raise
    workflow_data = raw.get("workflowData")
    workflow_id = str(
        raw.get("workflowId")
        or (workflow_data.get("id") if isinstance(workflow_data, dict) else "")
        or ""
    )
    if _ownership_value(n8n) == "shared_dev" and workflow_id not in await _owned_workflow_ids(
        user_id
    ):
        raise ExecutionNotFoundError(execution_id)
    workflow_context, context_source = await _execution_workflow_context(
        raw,
        workflow_id=workflow_id,
        n8n=n8n,
    )
    result = _summarize_execution(
        raw,
        workflow=workflow_context,
        workflow_context_source=context_source,
    )
    result = await verify_sheets_read_after_write(
        user_id,
        workflow=workflow_context,
        execution=raw,
        result=result,
    )
    try:
        await store.save_execution_evidence(
            user_id,
            execution_evidence_envelope(
                result,
                source="execution_inspect",
                instance_id=str(getattr(n8n, "instance_id", "") or "") or None,
            ),
        )
    except Exception as exc:
        log.warning(
            "execution_evidence_persist_error",
            execution_id=execution_id,
            workflow_id=workflow_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
    return result
