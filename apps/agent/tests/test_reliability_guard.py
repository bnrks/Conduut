from src.agent.reliability_guard import CONDUUT_TOOL_NAMES, looks_like_garbage


def test_clean_message_passes():
    assert looks_like_garbage("Workflow'unu kurdum ve çalıştırdım, sonuç hazır.") is None


def test_clean_message_mentioning_tool_in_backticks_passes():
    # A normal explanation referencing a tool name must NOT trip the detector.
    assert looks_like_garbage("`create_workflow` ile workflow'u oluşturdum.") is None


def test_tool_call_as_text_function_form_is_garbage():
    reason = looks_like_garbage("execute_workflow({'workflow_id': 'abc'})")
    assert reason is not None
    assert "execute_workflow" in reason


def test_tool_call_as_text_json_form_is_garbage():
    reason = looks_like_garbage('{"name": "create_workflow", "arguments": {}}')
    assert reason is not None
    assert "create_workflow" in reason


def test_runaway_length_is_garbage():
    assert looks_like_garbage("a" * 8001) == "runaway-length"


def test_excessive_repetition_is_garbage():
    reason = looks_like_garbage("execute now please " * 6)
    assert reason is not None


def test_tool_names_include_core_actions():
    assert {"execute_workflow", "create_workflow", "run_platform_action"} <= CONDUUT_TOOL_NAMES
