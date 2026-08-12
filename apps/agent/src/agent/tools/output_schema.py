"""Output presentation schema helpers for workflow run results.

Mirror of `runtime_inputs._normalized_input_schema`: the agent declares an
`output_schema` at build time; we normalize it deterministically and store it in
workflow metadata `resources.output_schema`, decoupled from the n8n JSON.
"""

from typing import Any

from src import store
from src.agent.schemas import WorkflowOutputField

_OUTPUT_FORMAT_VALUES = {
    "text",
    "longtext",
    "number",
    "currency",
    "datetime",
    "url",
    "email",
    "boolean",
    "list",
}


def _coerce_output_field(raw: WorkflowOutputField | dict[str, Any]) -> WorkflowOutputField | None:
    if isinstance(raw, WorkflowOutputField):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return WorkflowOutputField.model_validate(raw)
    except Exception:
        # Salvage an otherwise-valid field whose only problem is an unknown
        # format by coercing it to "text" (better than dropping the field).
        salvaged = dict(raw)
        salvaged["format"] = "text"
        try:
            return WorkflowOutputField.model_validate(salvaged)
        except Exception:
            return None


def _normalized_output_schema(
    output_schema: list[WorkflowOutputField | dict[str, Any]] | None,
) -> list[WorkflowOutputField]:
    fields: list[WorkflowOutputField] = []
    seen: set[str] = set()
    for raw in output_schema or []:
        field = _coerce_output_field(raw)
        if field is None:
            continue
        name = field.name.strip()
        if not name or name in seen:
            continue
        fmt = field.format if field.format in _OUTPUT_FORMAT_VALUES else "text"
        fields.append(
            WorkflowOutputField(
                name=name,
                label=field.label.strip() or name.replace("_", " ").title(),
                format=fmt,
            )
        )
        seen.add(name)
    return fields


def _output_schema_payload(fields: list[WorkflowOutputField]) -> list[dict[str, Any]]:
    return [field.model_dump(exclude_none=True) for field in fields]


def merge_output_schema_into_resources(
    existing_resources: dict[str, Any] | None,
    payload: list[dict[str, Any]],
) -> dict[str, Any]:
    resources = dict(existing_resources or {})
    if payload:
        resources["output_schema"] = payload
    return resources


async def save_workflow_output_metadata(
    user_id: str,
    workflow_id: str,
    *,
    input_schema_payload: list[dict[str, Any]],
    output_schema: list[WorkflowOutputField | dict[str, Any]] | None,
    instance_id: str | None = None,
) -> None:
    """Persist input + output schema, preserving any existing resources.

    Reads existing metadata so the output schema rides alongside other resource
    keys (e.g. test_status) instead of clobbering them.
    """

    existing = await store.get_workflow_metadata(
        user_id,
        workflow_id,
        instance_id=instance_id,
    )
    payload = _output_schema_payload(_normalized_output_schema(output_schema))
    resources = merge_output_schema_into_resources(existing.resources if existing else {}, payload)
    await store.save_workflow_metadata(
        user_id,
        workflow_id,
        input_schema=input_schema_payload,
        resources=resources,
        instance_id=instance_id,
    )
