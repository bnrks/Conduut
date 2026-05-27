"""User-safe artifact previews for platform and workflow outputs."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from src.agent.schemas import ArtifactPreviewData, ArtifactPreviewMessage, ArtifactPreviewTable
from src.store import WorkflowMetadata

MAX_ARTIFACT_ROWS = 10
MAX_ARTIFACT_COLUMNS = 12
MAX_ARTIFACT_CELL_CHARS = 160

_SECRET_KEY_FRAGMENTS = (
    "access_token",
    "authorization",
    "clientsecret",
    "credential",
    "oauth",
    "password",
    "refresh_token",
    "secret",
    "token",
)


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    compact = normalized.replace("_", "")
    return any(fragment in normalized or fragment in compact for fragment in _SECRET_KEY_FRAGMENTS)


def _sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, dict):
        if depth >= 2:
            return "{...}"
        return {
            str(key): _sanitize_value(item, depth=depth + 1)
            for key, item in value.items()
            if not _is_secret_key(str(key))
        }
    if isinstance(value, list):
        if depth >= 2:
            return "[...]"
        return [_sanitize_value(item, depth=depth + 1) for item in value[:5]]
    return value


def _cell_preview(value: Any) -> str:
    value = _sanitize_value(value)
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, int | float | bool):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if len(text) > MAX_ARTIFACT_CELL_CHARS:
        return f"{text[:MAX_ARTIFACT_CELL_CHARS]}..."
    return text


def _column_label(index: int) -> str:
    return f"Column {index + 1}"


def _unique_columns(labels: list[str]) -> list[str]:
    used: dict[str, int] = {}
    columns: list[str] = []
    for index, label in enumerate(labels):
        column = str(label).strip() or _column_label(index)
        count = used.get(column, 0)
        used[column] = count + 1
        if count:
            column = f"{column} {count + 1}"
        columns.append(column)
    return columns


def _coerce_matrix(values: Any) -> list[list[Any]]:
    if not isinstance(values, list):
        return []
    matrix: list[list[Any]] = []
    for row in values:
        if isinstance(row, list):
            matrix.append(row)
        else:
            matrix.append([row])
    return matrix


def artifact_table_from_rows(rows: list[dict[str, Any]]) -> ArtifactPreviewTable | None:
    if not rows:
        return None

    columns: list[str] = []
    for row in rows:
        for key in row:
            column = str(key)
            if _is_secret_key(column) or column in columns:
                continue
            columns.append(column)
            if len(columns) >= MAX_ARTIFACT_COLUMNS:
                break
        if len(columns) >= MAX_ARTIFACT_COLUMNS:
            break

    if not columns:
        return None

    visible_rows = rows[:MAX_ARTIFACT_ROWS]
    table_rows = [
        {column: _cell_preview(row.get(column)) for column in columns} for row in visible_rows
    ]
    return ArtifactPreviewTable(
        columns=columns,
        rows=table_rows,
        truncated=len(rows) > MAX_ARTIFACT_ROWS
        or any(
            len([key for key in row if not _is_secret_key(str(key))]) > MAX_ARTIFACT_COLUMNS
            for row in rows
        ),
        totalRows=len(rows),
    )


def artifact_table_from_matrix(
    values: Any,
    *,
    first_row_is_header: bool = False,
) -> ArtifactPreviewTable | None:
    matrix = _coerce_matrix(values)
    if not matrix:
        return None

    header: list[Any] | None = matrix[0] if first_row_is_header and len(matrix) > 1 else None
    data_rows = matrix[1:] if header is not None else matrix
    max_columns = max((len(row) for row in matrix), default=0)
    if max_columns <= 0:
        return None

    if header is not None:
        columns = _unique_columns(
            [
                str(item).strip() or _column_label(index)
                for index, item in enumerate(header[:MAX_ARTIFACT_COLUMNS])
            ]
        )
    else:
        columns = [_column_label(index) for index in range(min(max_columns, MAX_ARTIFACT_COLUMNS))]

    visible_rows = data_rows[:MAX_ARTIFACT_ROWS]
    table_rows = [
        {
            column: _cell_preview(row[index] if index < len(row) else "")
            for index, column in enumerate(columns)
        }
        for row in visible_rows
    ]
    return ArtifactPreviewTable(
        columns=columns,
        rows=table_rows,
        truncated=len(data_rows) > MAX_ARTIFACT_ROWS or max_columns > MAX_ARTIFACT_COLUMNS,
        totalRows=len(data_rows),
    )


def _matrix_has_header(values: Any) -> bool:
    matrix = _coerce_matrix(values)
    if len(matrix) < 2 or not matrix[0]:
        return False
    return all(isinstance(item, str) and item.strip() for item in matrix[0])


def _spreadsheet_id(params: dict[str, Any], data: dict[str, Any]) -> str:
    candidates = (
        data.get("spreadsheetId"),
        params.get("spreadsheet_id"),
        params.get("document_id"),
        params.get("spreadsheetId"),
    )
    return next((str(item) for item in candidates if item), "")


def _spreadsheet_url(params: dict[str, Any], data: dict[str, Any]) -> str | None:
    explicit = data.get("spreadsheetUrl") or params.get("spreadsheet_url") or params.get("url")
    if explicit:
        return str(explicit)
    spreadsheet_id = _spreadsheet_id(params, data)
    if spreadsheet_id:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    return None


def _range_label(params: dict[str, Any], data: dict[str, Any]) -> str | None:
    updates = data.get("updates") if isinstance(data.get("updates"), dict) else {}
    value = (
        data.get("updatedRange")
        or updates.get("updatedRange")
        or params.get("range")
        or params.get("sheet_name")
        or params.get("sheet_title")
    )
    return str(value) if value else None


def _source(
    *,
    source_type: str,
    action: str | None = None,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    node_name: str | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or {}
    data = data or {}
    source: dict[str, Any] = {"type": source_type}
    if action:
        source["action"] = action
    if workflow_id:
        source["workflowId"] = workflow_id
    if execution_id:
        source["executionId"] = execution_id
    if node_name:
        source["nodeName"] = node_name
    spreadsheet_id = _spreadsheet_id(params, data)
    if spreadsheet_id:
        source["spreadsheetId"] = spreadsheet_id
    range_label = _range_label(params, data)
    if range_label:
        source["range"] = range_label
    message_id = data.get("id") or params.get("message_id") or params.get("messageId")
    if message_id:
        source["messageId"] = str(message_id)
    thread_id = data.get("threadId") or params.get("thread_id") or params.get("threadId")
    if thread_id:
        source["threadId"] = str(thread_id)
    query = params.get("query")
    if query:
        source["query"] = str(query)
    return source


def _rows_from_action_params(params: dict[str, Any]) -> list[dict[str, Any]] | None:
    row = params.get("row")
    if isinstance(row, dict):
        return [{str(key): value for key, value in row.items()}]
    columns = params.get("columns")
    if isinstance(columns, dict):
        return [{str(key): value for key, value in columns.items()}]
    return None


def build_sheets_action_artifacts(
    *,
    action: str,
    params: dict[str, Any],
    data: dict[str, Any] | None,
) -> list[ArtifactPreviewData]:
    data = data or {}
    if not action.startswith("sheets."):
        return []

    table: ArtifactPreviewTable | None = None
    title = "Google Sheets updated"
    description = "Conduut captured a preview of the Sheets result."

    if action == "sheets.spreadsheet.create":
        title = "Google Sheets spreadsheet created"
        properties = data.get("properties") if isinstance(data.get("properties"), dict) else {}
        table = artifact_table_from_rows(
            [
                {
                    "Spreadsheet ID": _spreadsheet_id(params, data),
                    "Title": properties.get("title") or params.get("title"),
                    "Sheet": params.get("sheet_name") or params.get("sheet_title"),
                }
            ]
        )
    elif action == "sheets.sheet.create":
        title = "Google Sheets tab created"
        table = artifact_table_from_rows(
            [
                {
                    "Spreadsheet ID": _spreadsheet_id(params, data),
                    "Sheet": params.get("title") or params.get("sheet_name"),
                }
            ]
        )
    elif action == "sheets.range.read":
        title = "Google Sheets range read"
        description = "Preview of the rows Conduut read from Google Sheets."
        table = artifact_table_from_matrix(
            data.get("values"),
            first_row_is_header=_matrix_has_header(data.get("values")),
        )
    elif action == "sheets.range.update":
        title = "Google Sheets range updated"
        values = params.get("values")
        if not isinstance(values, list):
            rows = _rows_from_action_params(params)
            table = artifact_table_from_rows(rows) if rows else None
        else:
            table = artifact_table_from_matrix(
                values,
                first_row_is_header=_matrix_has_header(values),
            )
    elif action == "sheets.row.append":
        title = "Google Sheets row added"
        rows = _rows_from_action_params(params)
        table = (
            artifact_table_from_rows(rows)
            if rows
            else artifact_table_from_matrix([params.get("values")])
        )
    else:
        return []

    return [
        ArtifactPreviewData(
            service="google_sheets",
            title=title,
            description=description,
            url=_spreadsheet_url(params, data),
            source=_source(source_type="platform_action", action=action, params=params, data=data),
            table=table,
        )
    ]


def _gmail_url(*, message_id: str | None = None, query: str | None = None) -> str:
    if message_id:
        return f"https://mail.google.com/mail/u/0/#all/{quote(message_id)}"
    if query:
        return f"https://mail.google.com/mail/u/0/#search/{quote(query)}"
    return "https://mail.google.com/mail/u/0/#inbox"


def _split_recipients(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = str(value).replace(";", ",").split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def _gmail_headers(data: dict[str, Any]) -> dict[str, str]:
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    parsed: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name") or "").strip().lower()
        value = str(header.get("value") or "").strip()
        if name and value and not _is_secret_key(name):
            parsed[name] = _cell_preview(value)
    return parsed


def _gmail_message_from_action(
    *,
    action: str,
    params: dict[str, Any],
    data: dict[str, Any],
) -> ArtifactPreviewMessage:
    headers = _gmail_headers(data)
    label_ids = data.get("labelIds") if isinstance(data.get("labelIds"), list) else []
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    result_count = data.get("resultSizeEstimate")
    if result_count is None and action == "gmail.message.search":
        result_count = len(messages)

    return ArtifactPreviewMessage(
        messageId=str(data.get("id") or params.get("message_id") or "") or None,
        threadId=str(data.get("threadId") or params.get("thread_id") or "") or None,
        fromEmail=headers.get("from"),
        to=_split_recipients(params.get("to") or headers.get("to")),
        cc=_split_recipients(headers.get("cc")),
        bcc=_split_recipients(headers.get("bcc")),
        subject=_cell_preview(params.get("subject") or headers.get("subject"))
        if (params.get("subject") or headers.get("subject"))
        else None,
        snippet=_cell_preview(data.get("snippet")) if data.get("snippet") else None,
        bodyPreview=_cell_preview(params.get("message")) if params.get("message") else None,
        labels=[_cell_preview(item) for item in label_ids[:8]],
        query=_cell_preview(params.get("query")) if params.get("query") else None,
        resultCount=int(result_count) if isinstance(result_count, int | float) else None,
    )


def build_gmail_action_artifacts(
    *,
    action: str,
    params: dict[str, Any],
    data: dict[str, Any] | None,
) -> list[ArtifactPreviewData]:
    data = data or {}
    if not action.startswith("gmail."):
        return []

    message = _gmail_message_from_action(action=action, params=params, data=data)
    message_id = message.messageId
    query = message.query
    title = "Gmail message updated"
    description = "Conduut captured a preview of the Gmail result."

    if action == "gmail.message.send":
        title = "Gmail message sent"
        recipient = ", ".join(message.to)
        description = f"Sent to {recipient}." if recipient else "Message sent from Gmail."
    elif action == "gmail.message.search":
        title = "Gmail messages found"
        count = message.resultCount
        description = (
            f"{count} message(s) matched this Gmail search."
            if count is not None
            else "Gmail search completed."
        )
    elif action == "gmail.message.get":
        title = message.subject or "Gmail message"
        description = "Preview of the Gmail message Conduut read."
    elif action == "gmail.message.mark_read":
        title = "Gmail message marked read"
    elif action == "gmail.message.mark_unread":
        title = "Gmail message marked unread"
    elif action == "gmail.message.archive":
        title = "Gmail message archived"
    elif action == "gmail.message.trash":
        title = "Gmail message moved to trash"
    elif action == "gmail.message.label":
        title = "Gmail labels updated"
    else:
        return []

    return [
        ArtifactPreviewData(
            service="gmail",
            title=title,
            description=description,
            url=_gmail_url(message_id=message_id, query=query),
            source=_source(source_type="platform_action", action=action, params=params, data=data),
            message=message,
        )
    ]


def _first_spreadsheet_resource(metadata: WorkflowMetadata | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    for value in metadata.resources.values():
        if isinstance(value, dict) and (
            value.get("spreadsheet_id") or value.get("spreadsheet_url")
        ):
            return value
    return {}


def _rows_from_output_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            rows.append({str(key): value for key, value in item.items()})
    return rows


def build_sheets_workflow_artifacts(
    *,
    workflow_id: str,
    execution_id: str | None,
    outputs: list[dict[str, Any]],
    metadata: WorkflowMetadata | None,
) -> list[ArtifactPreviewData]:
    resource = _first_spreadsheet_resource(metadata)
    resource_params = {
        "spreadsheet_id": resource.get("spreadsheet_id"),
        "spreadsheet_url": resource.get("spreadsheet_url"),
        "sheet_name": resource.get("sheet_name"),
    }

    for output in outputs:
        node_name = str(output.get("nodeName") or "")
        node_key = node_name.lower()
        if "prepare sheets row" not in node_key and "google sheets" not in node_key:
            continue
        rows = _rows_from_output_items(output.get("items"))
        table = artifact_table_from_rows(rows)
        if table is None:
            continue
        title = "Google Sheets rows captured"
        if "append" in node_key or "prepare sheets row" in node_key:
            title = "Google Sheets row added"
        return [
            ArtifactPreviewData(
                service="google_sheets",
                title=title,
                description="Preview of the Sheets data produced by this workflow run.",
                url=_spreadsheet_url(resource_params, {}),
                source=_source(
                    source_type="workflow_run",
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_name=node_name,
                    params=resource_params,
                ),
                table=table,
            )
        ]

    return []


def build_gmail_workflow_artifacts(
    *,
    workflow_id: str,
    execution_id: str | None,
    outputs: list[dict[str, Any]],
) -> list[ArtifactPreviewData]:
    for output in outputs:
        node_name = str(output.get("nodeName") or "")
        if "gmail" not in node_name.lower():
            continue
        rows = _rows_from_output_items(output.get("items"))
        if not rows:
            continue
        first = rows[0]
        message = _gmail_message_from_action(
            action="gmail.message.send",
            params={},
            data=first,
        )
        title = "Gmail message captured"
        description = "Preview of the Gmail result produced by this workflow run."
        if message.messageId:
            title = "Gmail message sent"
        return [
            ArtifactPreviewData(
                service="gmail",
                title=title,
                description=description,
                url=_gmail_url(message_id=message.messageId),
                source=_source(
                    source_type="workflow_run",
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    node_name=node_name,
                    data=first,
                ),
                message=message,
            )
        ]

    return []
