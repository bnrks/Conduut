from src.store.workflow_previews import workflow_input_hash


def test_workflow_input_hash_is_canonical():
    assert workflow_input_hash({"b": 2, "a": 1}) == workflow_input_hash({"a": 1, "b": 2})


def test_workflow_input_hash_changes_with_input():
    assert workflow_input_hash({"row": 1}) != workflow_input_hash({"row": 2})
