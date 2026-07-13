from src.agent.tool_safety import (
    TOOL_REPLAY_SAFETY,
    ReplaySafety,
    replay_safety,
)

PUBLIC_AGENT_TOOLS = {
    "search_n8n_nodes",
    "get_node_schema",
    "find_workflow_template",
    "run_platform_action",
    "request_user_input",
    "list_workflows",
    "get_workflow",
    "create_workflow",
    "update_workflow",
    "activate_workflow",
    "deactivate_workflow",
    "execute_workflow",
    "analyze_workflow_readiness",
    "inspect_execution",
    "list_executions",
    "delete_workflow",
    "list_credentials",
    "attach_credential",
    "prepare_api_credential",
    "add_service_credential",
}


def test_every_public_agent_tool_has_an_explicit_safety_classification():
    assert set(TOOL_REPLAY_SAFETY) == PUBLIC_AGENT_TOOLS


def test_unknown_tools_fail_closed():
    assert replay_safety("future_mutating_tool") is ReplaySafety.REPLAY_UNSAFE


def test_ephemeral_user_input_request_is_safe_to_replay():
    assert replay_safety("request_user_input") is ReplaySafety.READ_ONLY


def test_agent_deps_marks_only_unsafe_tools(make_agent_deps):
    deps = make_agent_deps()
    deps.mark_replay_unsafe("get_workflow")
    assert deps.real_action_executed is False

    deps.mark_replay_unsafe("delete_workflow")
    assert deps.real_action_executed is True
    assert deps.replay_unsafe_tool == "delete_workflow"
