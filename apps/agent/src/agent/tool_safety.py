"""Replay-safety policy for every public Conduut agent tool.

The DeepSeek reliability guard may restart an attempt from the original user
prompt.  A restart is only safe until a tool capable of changing external
state starts its first mutating call.  Unknown tools deliberately fail closed.
"""

from enum import StrEnum


class ReplaySafety(StrEnum):
    READ_ONLY = "read_only"
    REPLAY_UNSAFE = "replay_unsafe"


TOOL_REPLAY_SAFETY: dict[str, ReplaySafety] = {
    # Registry and n8n reads.
    "search_n8n_nodes": ReplaySafety.READ_ONLY,
    "get_node_schema": ReplaySafety.READ_ONLY,
    "search_workflow_cards": ReplaySafety.READ_ONLY,
    "get_workflow_card": ReplaySafety.READ_ONLY,
    "get_node_contract": ReplaySafety.READ_ONLY,
    "get_automation_server_setup_step": ReplaySafety.READ_ONLY,
    "list_workflows": ReplaySafety.READ_ONLY,
    "get_workflow": ReplaySafety.READ_ONLY,
    "list_executions": ReplaySafety.READ_ONLY,
    "inspect_execution": ReplaySafety.READ_ONLY,
    "list_credentials": ReplaySafety.READ_ONLY,
    # This analysis may attach an unambiguous managed credential while checking
    # readiness, so it is intentionally not classified as a read.
    "analyze_workflow_readiness": ReplaySafety.REPLAY_UNSAFE,
    # Requesting input only emits ephemeral UI state and is safe to replay.
    "request_user_input": ReplaySafety.READ_ONLY,
    "create_workflow": ReplaySafety.REPLAY_UNSAFE,
    "update_workflow": ReplaySafety.REPLAY_UNSAFE,
    "delete_workflow": ReplaySafety.REPLAY_UNSAFE,
    "activate_workflow": ReplaySafety.REPLAY_UNSAFE,
    "deactivate_workflow": ReplaySafety.REPLAY_UNSAFE,
    "execute_workflow": ReplaySafety.REPLAY_UNSAFE,
    "run_platform_action": ReplaySafety.REPLAY_UNSAFE,
    "attach_credential": ReplaySafety.REPLAY_UNSAFE,
    "prepare_api_credential": ReplaySafety.REPLAY_UNSAFE,
    "add_service_credential": ReplaySafety.REPLAY_UNSAFE,
}


def replay_safety(tool: str) -> ReplaySafety:
    """Return a tool's policy, treating unregistered tools as unsafe."""

    return TOOL_REPLAY_SAFETY.get(tool, ReplaySafety.REPLAY_UNSAFE)


CONDUUT_TOOL_NAMES: frozenset[str] = frozenset(TOOL_REPLAY_SAFETY)
