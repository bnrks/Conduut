"""Agent-facing direct platform actions."""

from __future__ import annotations

import re
from typing import Any

from src import store
from src.agent.artifacts import build_gmail_action_artifacts, build_sheets_action_artifacts
from src.agent.schemas import (
    AgentDeps,
    ArtifactPreviewAttachment,
    OAuthPromptAttachment,
    OAuthPromptData,
    PlatformActionPlan,
    PlatformActionResult,
)
from src.platforms.capabilities import (
    CAPABILITIES,
    capability_risk,
    permission_pack_for_capability,
)
from src.platforms.google_clients import (
    GmailClient,
    MissingPlatformPermission,
    PlatformActionError,
    PlatformConfirmationRequired,
    SheetsClient,
)

_ACTION_CAPABILITIES = {
    "gmail.message.send": "gmail.message.send",
    "gmail.message.search": "gmail.message.read",
    "gmail.message.get": "gmail.message.read",
    "gmail.message.mark_read": "gmail.message.modify",
    "gmail.message.mark_unread": "gmail.message.modify",
    "gmail.message.archive": "gmail.message.modify",
    "gmail.message.trash": "gmail.message.trash",
    "gmail.message.label": "gmail.message.modify",
    "sheets.spreadsheet.create": "sheets.spreadsheet.create",
    "sheets.sheet.create": "sheets.sheet.manage",
    "sheets.sheet.delete": "sheets.range.clear",
    "sheets.range.read": "sheets.range.read",
    "sheets.range.update": "sheets.range.update",
    "sheets.range.clear": "sheets.range.clear",
    "sheets.row.append": "sheets.row.append",
}

_A1_RANGE_RE = re.compile(
    r"^(\$?[A-Z]+\$?\d+(:\$?[A-Z]+\$?\d+)?|\$?[A-Z]+:\$?[A-Z]+|\d+:\d+)$",
    re.IGNORECASE,
)


def required_capability_for_action(action: str) -> str:
    capability = _ACTION_CAPABILITIES.get(action)
    if not capability:
        raise PlatformActionError(f"Unsupported platform action: {action}")
    return capability


async def _emit_oauth_prompt(deps: AgentDeps, capability: str) -> None:
    capability_meta = CAPABILITIES.get(capability)
    service = capability_meta.service if capability_meta else "gmail"
    pack = permission_pack_for_capability(capability)
    await deps.emit_attachment(
        OAuthPromptAttachment(
            data=OAuthPromptData(
                service="Google Gmail" if service == "gmail" else "Google Sheets",
                description=f"Grant {capability} so Conduut can manage this platform.",
                authorizePath=f"/api/oauth/google/authorize?service={service}",
                returnTo="/dashboard/connections",
                requiredCapabilities=[capability],
                permissionPack=pack or None,
                riskLevel=capability_risk(capability),
            )
        )
    )
    deps.awaiting_user_input = True


async def _audit(
    deps: AgentDeps,
    *,
    action: str,
    capability: str,
    status: str,
    target_resource: str | None = None,
    error: str | None = None,
) -> None:
    await store.save_platform_action_audit(
        deps.user_id,
        conversation_id=deps.conversation_id,
        service=CAPABILITIES.get(capability).service if capability in CAPABILITIES else "",
        action=action,
        capability=capability,
        status=status,
        target_resource=target_resource,
        error=error,
    )


def _values_from_params(params: dict[str, Any]) -> list[Any]:
    values = params.get("values")
    if isinstance(values, list):
        return values
    row = params.get("row")
    if isinstance(row, dict):
        return list(row.values())
    raise PlatformActionError("Missing required values for Sheets append/update.")


def _quote_sheet_title(title: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", title):
        return title
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def _unquote_sheet_title(title: str) -> str:
    text = title.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def _sheet_title_from_range(range_label: str) -> str | None:
    text = range_label.strip()
    if not text:
        return None
    if "!" in text:
        return _unquote_sheet_title(text.split("!", 1)[0])
    if _A1_RANGE_RE.fullmatch(text):
        return None
    return _unquote_sheet_title(text)


def _sheet_title_for_params(params: dict[str, Any], range_label: str) -> str | None:
    explicit = params.get("sheet_name") or params.get("sheet_title") or params.get("sheet")
    if explicit:
        return str(explicit)
    return _sheet_title_from_range(range_label)


def _range_from_params(params: dict[str, Any], *, default_sheet: str = "Sheet1") -> str:
    explicit_range = params.get("range")
    if explicit_range:
        range_label = str(explicit_range)
        sheet_title = params.get("sheet_name") or params.get("sheet_title") or params.get("sheet")
        if sheet_title and "!" not in range_label:
            return f"{_quote_sheet_title(str(sheet_title))}!{range_label}"
        return range_label
    sheet_title = str(
        params.get("sheet_name")
        or params.get("sheet_title")
        or params.get("sheet")
        or default_sheet
    )
    return f"{_quote_sheet_title(sheet_title)}!A1"


def _sheets_resource(deps: AgentDeps) -> dict[str, Any]:
    return deps.platform_resources.setdefault("google_sheets", {})


def _gmail_resource(deps: AgentDeps) -> dict[str, Any]:
    return deps.platform_resources.setdefault("gmail", {})


def _spreadsheet_id_from_params(params: dict[str, Any]) -> str:
    return str(
        params.get("spreadsheet_id")
        or params.get("document_id")
        or params.get("spreadsheetId")
        or ""
    )


def _apply_sheets_resource_defaults(
    deps: AgentDeps,
    *,
    action: str,
    params: dict[str, Any],
) -> None:
    if not action.startswith("sheets.") or action == "sheets.spreadsheet.create":
        return
    resource = _sheets_resource(deps)
    if not _spreadsheet_id_from_params(params) and resource.get("spreadsheet_id"):
        params["spreadsheet_id"] = resource["spreadsheet_id"]
    if not params.get("spreadsheet_url") and resource.get("spreadsheet_url"):
        params["spreadsheet_url"] = resource["spreadsheet_url"]
    if (
        action in {"sheets.range.update", "sheets.row.append"}
        and not (params.get("sheet_name") or params.get("sheet_title") or params.get("sheet"))
        and resource.get("sheet_name")
    ):
        params["sheet_name"] = resource["sheet_name"]


def _remember_sheets_resource(
    deps: AgentDeps,
    *,
    params: dict[str, Any],
    data: dict[str, Any],
) -> None:
    spreadsheet_id = str(data.get("spreadsheetId") or _spreadsheet_id_from_params(params))
    if not spreadsheet_id:
        return
    resource = _sheets_resource(deps)
    resource["spreadsheet_id"] = spreadsheet_id
    spreadsheet_url = data.get("spreadsheetUrl") or params.get("spreadsheet_url")
    if spreadsheet_url:
        resource["spreadsheet_url"] = str(spreadsheet_url)
    sheet_name = params.get("sheet_name") or params.get("sheet_title") or params.get("sheet")
    if not sheet_name:
        range_label = params.get("range")
        if range_label:
            sheet_name = _sheet_title_from_range(str(range_label))
    if sheet_name:
        resource["sheet_name"] = str(sheet_name)


def _require_spreadsheet_id(action: str, params: dict[str, Any]) -> str:
    spreadsheet_id = _spreadsheet_id_from_params(params)
    if not spreadsheet_id:
        raise PlatformActionError(
            f"Missing required spreadsheet_id for {action}.",
            status="missing_input",
        )
    return spreadsheet_id


def _message_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("message_id") or params.get("messageId") or "")


def _apply_gmail_resource_defaults(
    deps: AgentDeps,
    *,
    action: str,
    params: dict[str, Any],
) -> None:
    if not action.startswith("gmail.") or action == "gmail.message.search":
        return
    resource = _gmail_resource(deps)
    if not _message_id_from_params(params) and resource.get("message_id"):
        params["message_id"] = resource["message_id"]
    if not params.get("thread_id") and resource.get("thread_id"):
        params["thread_id"] = resource["thread_id"]


def _remember_gmail_resource(
    deps: AgentDeps,
    *,
    params: dict[str, Any],
    data: dict[str, Any],
) -> None:
    message_id = str(data.get("id") or _message_id_from_params(params))
    thread_id = str(data.get("threadId") or params.get("thread_id") or params.get("threadId") or "")
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    if not message_id and messages:
        first = messages[0] if isinstance(messages[0], dict) else {}
        message_id = str(first.get("id") or "")
        thread_id = str(first.get("threadId") or thread_id or "")
    if not message_id:
        return
    resource = _gmail_resource(deps)
    resource["message_id"] = message_id
    if thread_id:
        resource["thread_id"] = thread_id


def _require_message_id(action: str, params: dict[str, Any]) -> str:
    message_id = _message_id_from_params(params)
    if not message_id:
        raise PlatformActionError(
            f"Missing required message_id for {action}.",
            status="missing_input",
        )
    return message_id


async def run_platform_action_payload(
    deps: AgentDeps,
    plan: PlatformActionPlan,
) -> PlatformActionResult:
    action = plan.action
    params = dict(plan.params)
    capability = required_capability_for_action(action)
    _apply_gmail_resource_defaults(deps, action=action, params=params)
    _apply_sheets_resource_defaults(deps, action=action, params=params)
    try:
        if action == "gmail.message.send":
            data = await GmailClient(deps.user_id).send(
                to=str(params.get("to") or ""),
                subject=str(params.get("subject") or ""),
                message=str(params.get("message") or ""),
            )
            target = str(data.get("id") or "")
        elif action == "gmail.message.search":
            data = await GmailClient(deps.user_id).search(
                query=str(params.get("query") or ""),
                limit=int(params.get("limit") or 10),
            )
            target = None
        elif action == "gmail.message.get":
            target = _require_message_id(action, params)
            data = await GmailClient(deps.user_id).get(
                message_id=target,
                format=str(params.get("format") or "metadata"),
            )
        elif action == "gmail.message.mark_read":
            target = _require_message_id(action, params)
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                remove_labels=["UNREAD"],
            )
        elif action == "gmail.message.mark_unread":
            target = _require_message_id(action, params)
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                add_labels=["UNREAD"],
            )
        elif action == "gmail.message.archive":
            target = _require_message_id(action, params)
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                remove_labels=["INBOX"],
            )
        elif action == "gmail.message.trash":
            target = _require_message_id(action, params)
            data = await GmailClient(deps.user_id).trash(
                message_id=target,
                confirmed=plan.confirmed,
            )
        elif action == "gmail.message.label":
            target = _require_message_id(action, params)
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                add_labels=[str(item) for item in params.get("add_labels") or []],
                remove_labels=[str(item) for item in params.get("remove_labels") or []],
            )
        elif action == "sheets.spreadsheet.create":
            data = await SheetsClient(deps.user_id).create_spreadsheet(
                title=str(params.get("title") or "Conduut Spreadsheet"),
                sheet_title=str(params.get("sheet_name") or params.get("sheet_title") or "")
                or None,
            )
            target = str(data.get("spreadsheetId") or "")
        elif action == "sheets.sheet.create":
            target = _require_spreadsheet_id(action, params)
            data = await SheetsClient(deps.user_id).ensure_sheet(
                spreadsheet_id=target,
                title=str(params.get("title") or params.get("sheet_name") or "Sheet"),
            )
        elif action == "sheets.sheet.delete":
            target = _require_spreadsheet_id(action, params)
            data = await SheetsClient(deps.user_id).delete_sheet(
                spreadsheet_id=target,
                sheet_id=int(params.get("sheet_id")),
                confirmed=plan.confirmed,
            )
        elif action == "sheets.range.read":
            target = _require_spreadsheet_id(action, params)
            data = await SheetsClient(deps.user_id).read_range(
                spreadsheet_id=target,
                range=str(params.get("range") or params.get("sheet_name") or "Sheet1"),
            )
        elif action == "sheets.range.update":
            target = _require_spreadsheet_id(action, params)
            client = SheetsClient(deps.user_id)
            range_label = _range_from_params(params)
            sheet_title = _sheet_title_for_params(params, range_label)
            if sheet_title:
                await client.ensure_sheet(spreadsheet_id=target, title=sheet_title)
            data = await client.update_range(
                spreadsheet_id=target,
                range=range_label,
                values=[
                    list(row)
                    for row in (
                        params.get("values")
                        if isinstance(params.get("values"), list)
                        else [_values_from_params(params)]
                    )
                ],
            )
        elif action == "sheets.range.clear":
            target = _require_spreadsheet_id(action, params)
            data = await SheetsClient(deps.user_id).clear_range(
                spreadsheet_id=target,
                range=str(params.get("range") or params.get("sheet_name") or "Sheet1"),
                confirmed=plan.confirmed,
            )
        elif action == "sheets.row.append":
            target = _require_spreadsheet_id(action, params)
            client = SheetsClient(deps.user_id)
            range_label = _range_from_params(params)
            sheet_title = _sheet_title_for_params(params, range_label)
            if sheet_title:
                await client.ensure_sheet(spreadsheet_id=target, title=sheet_title)
            data = await client.append_row(
                spreadsheet_id=target,
                range=range_label,
                values=_values_from_params(params),
            )
        else:
            raise PlatformActionError(f"Unsupported platform action: {action}")
    except (MissingPlatformPermission, PlatformConfirmationRequired) as exc:
        if isinstance(exc, MissingPlatformPermission):
            await _emit_oauth_prompt(deps, capability)
        await _audit(
            deps,
            action=action,
            capability=capability,
            status=exc.status,
            error=exc.message,
        )
        return PlatformActionResult(
            success=False,
            action=action,
            capability=capability,
            status=exc.status,
            error=exc.message,
            permissionPack=exc.permission_pack,
            riskLevel=exc.risk,
        )
    except PlatformActionError as exc:
        if exc.status in {"authorization_required", "reconnect_required"} and exc.capability:
            await _emit_oauth_prompt(deps, exc.capability)
        await _audit(
            deps,
            action=action,
            capability=capability,
            status=exc.status,
            error=exc.message,
        )
        return PlatformActionResult(
            success=False,
            action=action,
            capability=capability,
            status=exc.status,
            error=exc.message,
            permissionPack=exc.permission_pack,
            riskLevel=exc.risk or capability_risk(capability),
        )
    except Exception as exc:
        await _audit(
            deps,
            action=action,
            capability=capability,
            status="error",
            error=str(exc),
        )
        return PlatformActionResult(
            success=False,
            action=action,
            capability=capability,
            status="error",
            error=str(exc),
            riskLevel=capability_risk(capability),
        )

    artifacts = [
        *build_gmail_action_artifacts(action=action, params=params, data=data),
        *build_sheets_action_artifacts(action=action, params=params, data=data),
    ]
    if action.startswith("gmail."):
        _remember_gmail_resource(deps, params=params, data=data)
    if action.startswith("sheets."):
        _remember_sheets_resource(deps, params=params, data=data)
    for artifact in artifacts:
        await deps.emit_attachment(ArtifactPreviewAttachment(data=artifact))

    await _audit(
        deps,
        action=action,
        capability=capability,
        status="success",
        target_resource=target,
    )
    return PlatformActionResult(
        success=True,
        action=action,
        capability=capability,
        status="success",
        targetResource=target,
        data=data,
        riskLevel=capability_risk(capability),
        artifacts=artifacts,
    )


async def provision_spreadsheet_for_workflow(
    deps: AgentDeps,
    *,
    title: str,
    sheet_name: str | None,
    action_id: str,
) -> dict[str, Any]:
    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.spreadsheet.create",
            params={"title": title, "sheet_name": sheet_name},
        ),
    )
    if not result.success:
        raise PlatformActionError(result.error or "Could not create Google Sheet.")
    spreadsheet_id = str((result.data or {}).get("spreadsheetId") or "")
    if not spreadsheet_id:
        raise PlatformActionError("Google Sheets create did not return a spreadsheet id.")
    return {
        "action_id": action_id,
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": (result.data or {}).get("spreadsheetUrl"),
        "title": title,
        "sheet_name": sheet_name,
    }
