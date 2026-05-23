"""Agent-facing direct platform actions."""

from __future__ import annotations

from typing import Any

from src import store
from src.agent.schemas import (
    AgentDeps,
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


async def run_platform_action_payload(
    deps: AgentDeps,
    plan: PlatformActionPlan,
) -> PlatformActionResult:
    action = plan.action
    params = plan.params
    capability = required_capability_for_action(action)
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
            target = str(params.get("message_id") or "")
            data = await GmailClient(deps.user_id).get(
                message_id=target,
                format=str(params.get("format") or "metadata"),
            )
        elif action == "gmail.message.mark_read":
            target = str(params.get("message_id") or "")
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                remove_labels=["UNREAD"],
            )
        elif action == "gmail.message.mark_unread":
            target = str(params.get("message_id") or "")
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                add_labels=["UNREAD"],
            )
        elif action == "gmail.message.archive":
            target = str(params.get("message_id") or "")
            data = await GmailClient(deps.user_id).modify(
                message_id=target,
                remove_labels=["INBOX"],
            )
        elif action == "gmail.message.trash":
            target = str(params.get("message_id") or "")
            data = await GmailClient(deps.user_id).trash(
                message_id=target,
                confirmed=plan.confirmed,
            )
        elif action == "gmail.message.label":
            target = str(params.get("message_id") or "")
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
            target = str(params.get("spreadsheet_id") or "")
            data = await SheetsClient(deps.user_id).add_sheet(
                spreadsheet_id=target,
                title=str(params.get("title") or params.get("sheet_name") or "Sheet"),
            )
        elif action == "sheets.sheet.delete":
            target = str(params.get("spreadsheet_id") or "")
            data = await SheetsClient(deps.user_id).delete_sheet(
                spreadsheet_id=target,
                sheet_id=int(params.get("sheet_id")),
                confirmed=plan.confirmed,
            )
        elif action == "sheets.range.read":
            target = str(params.get("spreadsheet_id") or "")
            data = await SheetsClient(deps.user_id).read_range(
                spreadsheet_id=target,
                range=str(params.get("range") or params.get("sheet_name") or "Sheet1"),
            )
        elif action == "sheets.range.update":
            target = str(params.get("spreadsheet_id") or "")
            data = await SheetsClient(deps.user_id).update_range(
                spreadsheet_id=target,
                range=str(params.get("range") or params.get("sheet_name") or "Sheet1"),
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
            target = str(params.get("spreadsheet_id") or "")
            data = await SheetsClient(deps.user_id).clear_range(
                spreadsheet_id=target,
                range=str(params.get("range") or params.get("sheet_name") or "Sheet1"),
                confirmed=plan.confirmed,
            )
        elif action == "sheets.row.append":
            target = str(params.get("spreadsheet_id") or "")
            data = await SheetsClient(deps.user_id).append_row(
                spreadsheet_id=target,
                range=str(params.get("range") or params.get("sheet_name") or "Sheet1"),
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
