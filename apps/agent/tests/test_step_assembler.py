from src.agent.step_assembler import StepAssembler, build_steps


def test_text_activity_text_alternation():
    s = StepAssembler()
    s.add("token", {"text": "Önce kontrol edeyim."})
    s.add("tool_call", {"tool": "list_credentials"})
    s.add("token", {"text": "Hazır."})
    assert s.steps() == [
        {"kind": "text", "text": "Önce kontrol edeyim."},
        {"kind": "activity", "actions": ["list_credentials"]},
        {"kind": "text", "text": "Hazır."},
    ]


def test_token_deltas_merge_into_one_text_step():
    s = StepAssembler()
    s.add("token", {"text": "Workflow "})
    s.add("token", {"text": "created."})
    assert s.steps() == [{"kind": "text", "text": "Workflow created."}]


def test_parallel_tools_collapse_into_one_activity():
    s = StepAssembler()
    s.add("token", {"text": "Bakıyorum."})
    s.add("tool_call", {"tool": "list_credentials"})
    s.add("tool_call", {"tool": "get_node_schema"})
    s.add("tool_call", {"tool": "get_node_schema"})
    assert s.steps()[-1] == {
        "kind": "activity",
        "actions": ["list_credentials", "get_node_schema", "get_node_schema"],
    }


def test_text_only_run():
    s = StepAssembler()
    s.add("token", {"text": "Tek cevap."})
    assert s.steps() == [{"kind": "text", "text": "Tek cevap."}]


def test_tools_only_run():
    s = StepAssembler()
    s.add("tool_call", {"tool": "create_workflow"})
    assert s.steps() == [{"kind": "activity", "actions": ["create_workflow"]}]


def test_thinking_attachment_and_empty_token_ignored():
    s = StepAssembler()
    s.add("thinking", {"text": "reasoning"})
    s.add("token", {"text": ""})
    s.add("attachment", {"type": "workflow_preview"})
    assert s.steps() == []


def test_build_steps_from_event_list_preserves_order():
    events = [
        ("token", {"text": "A."}),
        ("attachment", {"type": "workflow_preview"}),
        ("tool_call", {"tool": "create_workflow"}),
        ("token", {"text": "B."}),
    ]
    assert build_steps(events) == [
        {"kind": "text", "text": "A."},
        {"kind": "activity", "actions": ["create_workflow"]},
        {"kind": "text", "text": "B."},
    ]
