"""Per-conversation dynamic platform state for agent self-awareness: the user's
connected services, saved credentials, and existing automations. Gathered
best-effort (never raises) and rendered into the agent instructions each run."""

import asyncio
from dataclasses import dataclass, field

import structlog

from src import n8n_client, store

log = structlog.get_logger()

_MAX_ITEMS = 10


@dataclass
class ConnectionSummary:
    service: str
    account_email: str
    status: str


@dataclass
class CredentialSummary:
    label: str
    credential_type: str
    host: str
    status: str


@dataclass
class WorkflowSummary:
    name: str
    active: bool
    has_runtime_inputs: bool


@dataclass
class UserPlatformState:
    connections: list[ConnectionSummary] = field(default_factory=list)
    credentials: list[CredentialSummary] = field(default_factory=list)
    workflows: list[WorkflowSummary] = field(default_factory=list)


async def _safe(coro, source: str):
    """Await a state-source coroutine; never raise — log and return None."""
    try:
        return await coro
    except Exception as exc:  # noqa: BLE001 - best-effort, any failure is non-fatal
        log.debug("platform_state_source_failed", source=source, error=str(exc))
        return None


async def gather_user_state(user_id: str) -> UserPlatformState:
    """Gather the user's platform state from all sources in PARALLEL, best-effort.

    Each source is isolated: if one fails the others still populate and this
    function never raises. Returns an empty state if everything fails.
    """
    connections, credentials, workflows, metadata = await asyncio.gather(
        _safe(store.list_connections(user_id), "connections"),
        _safe(store.list_custom_credentials(user_id), "credentials"),
        _safe(n8n_client.list_workflows(), "workflows"),
        _safe(store.get_all_workflow_metadata(user_id), "metadata"),
    )

    state = UserPlatformState()
    if connections:
        state.connections = [
            ConnectionSummary(service=c.service, account_email=c.account_email, status=c.status)
            for c in connections
        ]
    if credentials:
        state.credentials = [
            CredentialSummary(
                label=c.label,
                credential_type=c.credential_type,
                host=c.host,
                status=c.status,
            )
            for c in credentials
        ]
    if workflows:
        # n8n is a shared MVP instance — list_workflows() returns ALL users' workflows
        # (same situation as routes/workflows.py, which carries a per-user-filter TODO
        # on its own list_workflows() call). Intersect with per-user metadata so only
        # THIS user's automations appear in their agent instructions.
        # Fail-closed: if the metadata fetch failed, meta == {} and NO workflows are
        # shown — privacy over completeness; the `metadata or {}` guard above handles
        # the None case.
        meta = metadata or {}
        state.workflows = [
            WorkflowSummary(
                name=w.name,
                active=w.active,
                has_runtime_inputs=bool(meta.get(w.id) and meta[w.id].input_schema),
            )
            for w in workflows
            if w.id in meta  # exclude workflows that belong to other users
        ]
    return state


def render_user_state(state: UserPlatformState) -> str:
    """Render the dynamic user state as a compact, secret-free instructions line."""
    lines: list[str] = []

    if state.connections:
        items = []
        for c in state.connections[:_MAX_ITEMS]:
            label = f"{c.service} ({c.account_email})" if c.account_email else c.service
            if c.status != "connected":
                label += " — needs reconnect"
            items.append(label)
        lines.append("Connected services: " + ", ".join(items) + ".")
    else:
        lines.append("Connected services: none yet.")

    if state.credentials:
        items = []
        for c in state.credentials[:_MAX_ITEMS]:
            label = c.label or c.credential_type
            tag = c.host or c.credential_type
            suffix = " (incomplete)" if c.status == "draft" else ""
            items.append(f"'{label}' [{tag}]{suffix}")
        lines.append("Saved credentials: " + ", ".join(items) + ".")

    if state.workflows:
        items = []
        for w in state.workflows[:_MAX_ITEMS]:
            flags = ["active" if w.active else "inactive"]
            if w.has_runtime_inputs:
                flags.append("takes input")
            items.append(f"'{w.name}' ({', '.join(flags)})")
        lines.append("Automations: " + ", ".join(items) + ".")

    return "Current user state — " + " ".join(lines)


def platform_state_instructions(state: UserPlatformState | None) -> str:
    """Dynamic-instructions body: render state, or '' when none is set."""
    if state is None:
        return ""
    return render_user_state(state)
