"""Capability and permission-pack registry for connected platforms."""

from __future__ import annotations

from dataclasses import dataclass

GOOGLE_PROFILE_SCOPES = ("openid", "email", "profile")

SCOPE_GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
SCOPE_GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
SCOPE_GMAIL_FULL = "https://mail.google.com/"
SCOPE_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
SCOPE_DRIVE_METADATA = "https://www.googleapis.com/auth/drive.metadata"
SCOPE_SHEETS = "https://www.googleapis.com/auth/spreadsheets"
SCOPE_SHEETS_READONLY = "https://www.googleapis.com/auth/spreadsheets.readonly"

LEGACY_CAPABILITY_ALIASES = {
    "google.gmail.send": "gmail.message.send",
    "google.gmail.read": "gmail.message.read",
    "google.sheets.read": "sheets.range.read",
    "google.sheets.write": "sheets.row.append",
}


@dataclass(frozen=True)
class PlatformCapability:
    id: str
    service: str
    label: str
    scopes: tuple[str, ...]
    risk: str = "low"
    direct_supported: bool = True
    workflow_supported: bool = False
    confirmation_required: bool = False
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionPack:
    id: str
    service: str
    label: str
    description: str
    capabilities: tuple[str, ...]
    scopes: tuple[str, ...]
    risk: str = "low"
    recommended: bool = False


CAPABILITIES: dict[str, PlatformCapability] = {
    "gmail.message.send": PlatformCapability(
        id="gmail.message.send",
        service="gmail",
        label="Send Gmail messages",
        scopes=(SCOPE_GMAIL_SEND,),
        workflow_supported=True,
        aliases=("google.gmail.send",),
    ),
    "gmail.message.read": PlatformCapability(
        id="gmail.message.read",
        service="gmail",
        label="Read Gmail messages",
        scopes=(SCOPE_GMAIL_READONLY,),
        risk="medium",
        aliases=("google.gmail.read",),
    ),
    "gmail.message.modify": PlatformCapability(
        id="gmail.message.modify",
        service="gmail",
        label="Organize Gmail messages",
        scopes=(SCOPE_GMAIL_MODIFY,),
        risk="medium",
    ),
    "gmail.message.trash": PlatformCapability(
        id="gmail.message.trash",
        service="gmail",
        label="Move Gmail messages to trash",
        scopes=(SCOPE_GMAIL_MODIFY,),
        risk="high",
        confirmation_required=True,
    ),
    "gmail.message.delete_permanently": PlatformCapability(
        id="gmail.message.delete_permanently",
        service="gmail",
        label="Permanently delete Gmail messages",
        scopes=(SCOPE_GMAIL_FULL,),
        risk="destructive",
        confirmation_required=True,
    ),
    "sheets.spreadsheet.create": PlatformCapability(
        id="sheets.spreadsheet.create",
        service="sheets",
        label="Create spreadsheets",
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="medium",
        workflow_supported=True,
    ),
    "sheets.sheet.manage": PlatformCapability(
        id="sheets.sheet.manage",
        service="sheets",
        label="Manage sheets/tabs",
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="medium",
    ),
    "sheets.range.read": PlatformCapability(
        id="sheets.range.read",
        service="sheets",
        label="Read spreadsheet ranges",
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        aliases=("google.sheets.read",),
    ),
    "sheets.range.update": PlatformCapability(
        id="sheets.range.update",
        service="sheets",
        label="Update spreadsheet ranges",
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="medium",
    ),
    "sheets.range.clear": PlatformCapability(
        id="sheets.range.clear",
        service="sheets",
        label="Clear spreadsheet ranges",
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="high",
        confirmation_required=True,
    ),
    "sheets.row.append": PlatformCapability(
        id="sheets.row.append",
        service="sheets",
        label="Append spreadsheet rows",
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="medium",
        workflow_supported=True,
        aliases=("google.sheets.write",),
    ),
}

PERMISSION_PACKS: dict[str, PermissionPack] = {
    "gmail.basic": PermissionPack(
        id="gmail.basic",
        service="gmail",
        label="Gmail Basic",
        description="Read and send Gmail messages for existing MVP workflows.",
        capabilities=("gmail.message.send", "gmail.message.read"),
        scopes=(SCOPE_GMAIL_SEND, SCOPE_GMAIL_READONLY),
        recommended=True,
    ),
    "gmail.send": PermissionPack(
        id="gmail.send",
        service="gmail",
        label="Gmail Send",
        description="Send email from the connected Gmail account.",
        capabilities=("gmail.message.send",),
        scopes=(SCOPE_GMAIL_SEND,),
        recommended=True,
    ),
    "gmail.read": PermissionPack(
        id="gmail.read",
        service="gmail",
        label="Gmail Read",
        description="Read messages, threads, and labels.",
        capabilities=("gmail.message.read",),
        scopes=(SCOPE_GMAIL_READONLY,),
        risk="medium",
    ),
    "gmail.organize": PermissionPack(
        id="gmail.organize",
        service="gmail",
        label="Gmail Organize",
        description=(
            "Read and organize messages, including read/unread, archive, labels, and trash."
        ),
        capabilities=(
            "gmail.message.read",
            "gmail.message.modify",
            "gmail.message.trash",
        ),
        scopes=(SCOPE_GMAIL_MODIFY,),
        risk="high",
    ),
    "gmail.full_control": PermissionPack(
        id="gmail.full_control",
        service="gmail",
        label="Gmail Full Control",
        description="Full mailbox access, including permanent deletion.",
        capabilities=(
            "gmail.message.send",
            "gmail.message.read",
            "gmail.message.modify",
            "gmail.message.trash",
            "gmail.message.delete_permanently",
        ),
        scopes=(SCOPE_GMAIL_FULL,),
        risk="destructive",
    ),
    "sheets.app_files": PermissionPack(
        id="sheets.app_files",
        service="sheets",
        label="Sheets App Files",
        description=(
            "Create and manage spreadsheets Conduut creates or the user opens with Conduut."
        ),
        capabilities=(
            "sheets.spreadsheet.create",
            "sheets.sheet.manage",
            "sheets.range.read",
            "sheets.range.update",
            "sheets.range.clear",
            "sheets.row.append",
        ),
        scopes=(SCOPE_DRIVE_FILE, SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="medium",
        recommended=True,
    ),
    "sheets.full_access": PermissionPack(
        id="sheets.full_access",
        service="sheets",
        label="Sheets Full Spreadsheet Access",
        description="Read and edit spreadsheets available to the connected account.",
        capabilities=(
            "sheets.spreadsheet.create",
            "sheets.sheet.manage",
            "sheets.range.read",
            "sheets.range.update",
            "sheets.range.clear",
            "sheets.row.append",
        ),
        scopes=(SCOPE_SHEETS, SCOPE_DRIVE_METADATA),
        risk="high",
    ),
}

DEFAULT_PERMISSION_PACK_BY_SERVICE = {
    "gmail": "gmail.basic",
    "sheets": "sheets.app_files",
}


def canonical_capability_id(capability_id: str) -> str:
    return LEGACY_CAPABILITY_ALIASES.get(capability_id, capability_id)


def canonical_capability_ids(capability_ids: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for capability_id in capability_ids:
        canonical = canonical_capability_id(str(capability_id))
        if canonical in CAPABILITIES and canonical not in seen:
            result.append(canonical)
            seen.add(canonical)
    return result


def service_for_capabilities(capability_ids: list[str]) -> str | None:
    services = {
        CAPABILITIES[capability_id].service
        for capability_id in canonical_capability_ids(capability_ids)
    }
    return services.pop() if len(services) == 1 else None


def capabilities_for_permission_pack(pack_id: str) -> list[str]:
    pack = PERMISSION_PACKS.get(pack_id)
    return list(pack.capabilities) if pack else []


def scopes_for_capabilities(capability_ids: list[str]) -> list[str]:
    scopes = list(GOOGLE_PROFILE_SCOPES)
    for capability_id in canonical_capability_ids(capability_ids):
        capability = CAPABILITIES[capability_id]
        for scope in capability.scopes:
            if scope not in scopes:
                scopes.append(scope)
    return scopes


def scopes_for_permission_pack(pack_id: str) -> list[str]:
    pack = PERMISSION_PACKS.get(pack_id)
    if not pack:
        return list(GOOGLE_PROFILE_SCOPES)
    scopes = list(GOOGLE_PROFILE_SCOPES)
    for scope in pack.scopes:
        if scope not in scopes:
            scopes.append(scope)
    return scopes


def default_permission_pack(service: str) -> str:
    return DEFAULT_PERMISSION_PACK_BY_SERVICE.get(service, "")


def resolve_permission_request(
    service: str,
    *,
    permission_pack: str | None = None,
    requested_capabilities: list[str] | None = None,
) -> tuple[list[str], list[str], str | None]:
    pack_id = permission_pack or default_permission_pack(service)
    capabilities = (
        canonical_capability_ids(requested_capabilities or [])
        if requested_capabilities
        else capabilities_for_permission_pack(pack_id)
    )
    capability_service = service_for_capabilities(capabilities) if capabilities else service
    if capability_service and capability_service != service:
        return [], [], None
    scopes = (
        scopes_for_capabilities(capabilities)
        if requested_capabilities
        else scopes_for_permission_pack(pack_id)
    )
    return scopes, capabilities, pack_id if pack_id in PERMISSION_PACKS else None


def capabilities_for_scopes(scopes: list[str]) -> list[str]:
    scope_set = set(scopes)
    capabilities: set[str] = set()

    if SCOPE_GMAIL_FULL in scope_set:
        capabilities.update(
            capability_id
            for capability_id, capability in CAPABILITIES.items()
            if capability.service == "gmail"
        )
    if SCOPE_GMAIL_SEND in scope_set:
        capabilities.add("gmail.message.send")
    if SCOPE_GMAIL_READONLY in scope_set:
        capabilities.add("gmail.message.read")
    if SCOPE_GMAIL_MODIFY in scope_set:
        capabilities.update({"gmail.message.read", "gmail.message.modify", "gmail.message.trash"})
    if SCOPE_DRIVE_FILE in scope_set or SCOPE_SHEETS in scope_set:
        capabilities.update(
            capability_id
            for capability_id, capability in CAPABILITIES.items()
            if capability.service == "sheets"
        )
    if SCOPE_SHEETS_READONLY in scope_set:
        capabilities.add("sheets.range.read")

    return [capability_id for capability_id in CAPABILITIES if capability_id in capabilities]


def permission_packs_for_scopes(scopes: list[str]) -> list[str]:
    scope_set = set(scopes)
    result: list[str] = []
    for pack_id, pack in PERMISSION_PACKS.items():
        if all(scope in scope_set for scope in pack.scopes):
            result.append(pack_id)
    return result


def permission_pack_for_capability(capability_id: str) -> str:
    capability_id = canonical_capability_id(capability_id)
    for pack in PERMISSION_PACKS.values():
        if capability_id in pack.capabilities and pack.recommended:
            return pack.id
    for pack in PERMISSION_PACKS.values():
        if capability_id in pack.capabilities:
            return pack.id
    return ""


def capability_risk(capability_id: str) -> str:
    capability = CAPABILITIES.get(canonical_capability_id(capability_id))
    return capability.risk if capability else "medium"


def capability_requires_confirmation(capability_id: str) -> bool:
    capability = CAPABILITIES.get(canonical_capability_id(capability_id))
    return bool(capability and capability.confirmation_required)


def connection_has_capability(granted: list[str], required: str) -> bool:
    canonical_granted = set(canonical_capability_ids(granted))
    canonical_required = canonical_capability_id(required)
    return canonical_required in canonical_granted
