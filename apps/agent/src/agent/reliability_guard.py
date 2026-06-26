"""Detect DeepSeek #1244 failures: a tool call emitted as plain text, or a
degenerate runaway loop, in a completed run's visible text.

The model occasionally writes `execute_workflow {...}` into the message instead
of issuing a structured tool call (deepseek-ai/DeepSeek-V3#1244). This module
provides a pure detector the runner uses to decide whether to retry the run.
"""

import re

MAX_MESSAGE_CHARS = 8000
RUNAWAY_CHARS = 12000
MAX_ATTEMPTS = 3
REPEAT_WINDOW = 20
REPEAT_COUNT = 4
REPLAY_CHUNK = 24
REPLAY_DELAY = 0.02

# The agent's registered tool names (factory.py). A user-facing message never
# contains `<snake_case_tool>(` or `"<tool>":` — only a leaked tool call does.
CONDUUT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_n8n_nodes",
        "get_node_schema",
        "find_workflow_template",
        "create_workflow",
        "update_workflow",
        "get_workflow",
        "execute_workflow",
        "activate_workflow",
        "deactivate_workflow",
        "list_executions",
        "inspect_execution",
        "analyze_workflow_readiness",
        "request_user_input",
        "run_platform_action",
        "list_credentials",
        "attach_credential",
        "prepare_api_credential",
    }
)


def _has_excessive_repetition(content: str) -> bool:
    """True when a REPEAT_WINDOW-char window repeats REPEAT_COUNT+ times."""

    if len(content) < REPEAT_WINDOW * REPEAT_COUNT:
        return False
    seen: dict[str, int] = {}
    for index in range(len(content) - REPEAT_WINDOW + 1):
        window = content[index : index + REPEAT_WINDOW]
        count = seen.get(window, 0) + 1
        if count >= REPEAT_COUNT:
            return True
        seen[window] = count
    return False


def looks_like_garbage(content: str, tool_names: frozenset[str] = CONDUUT_TOOL_NAMES) -> str | None:
    """Return a short reason if ``content`` looks like a #1244 failure, else None."""

    if len(content) > MAX_MESSAGE_CHARS:
        return "runaway-length"
    for name in tool_names:
        esc = re.escape(name)
        if re.search(rf"\b{esc}\s*[(\[{{]", content) or re.search(rf'"{esc}"\s*[:,]', content):
            return f"tool-call-as-text:{name}"
    if _has_excessive_repetition(content):
        return "repetition"
    return None
