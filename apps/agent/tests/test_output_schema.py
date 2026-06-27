import pytest

from src import store
from src.agent.schemas import WorkflowOutputField
from src.agent.tools.output_schema import (
    _normalized_output_schema,
    _output_schema_payload,
    merge_output_schema_into_resources,
)


def test_normalized_output_schema_trims_dedups_and_humanizes_label():
    fields = _normalized_output_schema(
        [
            {"name": " price ", "label": "", "format": "currency"},
            {"name": "price", "label": "Dup", "format": "text"},  # duplicate name
            {"name": "fetched_at", "label": " When ", "format": "datetime"},
        ]
    )
    assert [f.name for f in fields] == ["price", "fetched_at"]
    assert fields[0].label == "Price"  # blank label humanized from name
    assert fields[0].format == "currency"
    assert fields[1].label == "When"


def test_normalized_output_schema_coerces_unknown_format_to_text():
    fields = _normalized_output_schema([{"name": "x", "label": "X", "format": "bogus"}])
    assert len(fields) == 1
    assert fields[0].format == "text"


def test_normalized_output_schema_skips_unnamed_and_malformed():
    fields = _normalized_output_schema(
        [{"name": "  ", "label": "blank"}, "not-a-dict", {"label": "no-name"}]
    )
    assert fields == []


def test_normalized_output_schema_accepts_model_instances():
    fields = _normalized_output_schema([WorkflowOutputField(name="q", label="Quote")])
    assert fields[0].name == "q"
    assert fields[0].format == "text"


def test_output_schema_payload_round_trips():
    payload = _output_schema_payload(_normalized_output_schema([{"name": "p", "label": "P"}]))
    assert payload == [{"name": "p", "label": "P", "format": "text"}]


def test_merge_output_schema_into_resources_preserves_existing_and_adds_key():
    merged = merge_output_schema_into_resources(
        {"test_status": "passed"}, [{"name": "p", "label": "P", "format": "text"}]
    )
    assert merged["test_status"] == "passed"
    assert merged["output_schema"] == [{"name": "p", "label": "P", "format": "text"}]


def test_merge_output_schema_into_resources_omits_key_when_empty():
    merged = merge_output_schema_into_resources({"test_status": "passed"}, [])
    assert "output_schema" not in merged
    assert merged["test_status"] == "passed"


@pytest.mark.asyncio
async def test_save_workflow_output_metadata_merges_and_preserves(monkeypatch):
    saved: dict = {}

    async def fake_get(_user_id, _workflow_id):
        return store.WorkflowMetadata(
            workflow_id="wf_1",
            input_schema=[],
            created_at="now",
            updated_at="now",
            resources={"test_status": "passed"},
        )

    async def fake_save(user_id, workflow_id, *, input_schema, resources=None):
        saved["input_schema"] = input_schema
        saved["resources"] = resources

    monkeypatch.setattr("src.agent.tools.output_schema.store.get_workflow_metadata", fake_get)
    monkeypatch.setattr("src.agent.tools.output_schema.store.save_workflow_metadata", fake_save)

    from src.agent.tools.output_schema import save_workflow_output_metadata

    await save_workflow_output_metadata(
        "user_1",
        "wf_1",
        input_schema_payload=[{"name": "to", "label": "To", "type": "email", "required": True}],
        output_schema=[{"name": "price", "label": "Fiyat", "format": "currency"}],
    )

    assert saved["input_schema"] == [
        {"name": "to", "label": "To", "type": "email", "required": True}
    ]
    assert saved["resources"]["test_status"] == "passed"
    assert saved["resources"]["output_schema"] == [
        {"name": "price", "label": "Fiyat", "format": "currency"}
    ]


@pytest.mark.asyncio
async def test_save_workflow_output_metadata_omits_empty_schema(monkeypatch):
    saved: dict = {}

    async def fake_get(_user_id, _workflow_id):
        return None

    async def fake_save(user_id, workflow_id, *, input_schema, resources=None):
        saved["resources"] = resources

    monkeypatch.setattr("src.agent.tools.output_schema.store.get_workflow_metadata", fake_get)
    monkeypatch.setattr("src.agent.tools.output_schema.store.save_workflow_metadata", fake_save)

    from src.agent.tools.output_schema import save_workflow_output_metadata

    await save_workflow_output_metadata(
        "user_1", "wf_1", input_schema_payload=[], output_schema=None
    )

    assert "output_schema" not in saved["resources"]
