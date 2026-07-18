"""PII-free regression fixtures derived from n8n executions #320/#323/#327."""

import json
from pathlib import Path

import pytest

from src.agent.assurance import analyze_workflow_semantics
from src.agent.tools.execution import _summarize_execution

_FIXTURE = Path(__file__).parent / "fixtures" / "m1_execution_snapshots.json"


def _items(count: int, *, receipt: bool = False) -> list[dict]:
    key = "id" if receipt else "row"
    return [{"json": {key: f"masked-{index}"}} for index in range(count)]


def _execution(snapshot_id: str, snapshot: dict) -> dict:
    run_data = {}
    for name, node in snapshot["nodes"].items():
        count = node["itemCount"]
        receipt = name == "Send Email"
        run_data[name] = [
            {
                "executionStatus": "success",
                "data": {"main": [_items(count, receipt=receipt)]},
                "hints": ["masked n8n hint"] * node["hintCount"],
            }
        ]
    return {
        "id": snapshot_id,
        "workflowId": "m1-snapshot",
        "status": snapshot["rawStatus"],
        "data": {"resultData": {"runData": run_data}},
    }


def _workflow() -> dict:
    return {
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
            {
                "name": "Update Status",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {"resource": "sheet", "operation": "update"},
            },
        ]
    }


@pytest.mark.parametrize("snapshot_id", ["320", "323", "327"])
def test_m1_execution_snapshot_functional_assessment(snapshot_id: str):
    snapshots = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    snapshot = snapshots[snapshot_id]

    result = _summarize_execution(
        _execution(snapshot_id, snapshot),
        response={"statusCode": snapshot["transportStatus"], "body": {}},
        workflow=_workflow(),
    )

    assert result.functionalStatus == snapshot["expectedFunctionalStatus"]
    assert result.assessment.actionCount == snapshot["nodes"]["Send Email"]["itemCount"]
    assert result.assessment.writebackCount == snapshot["nodes"]["Update Status"]["itemCount"]
    assert (result.functionalStatus in {"verified", "no_action"}) is (
        result.claimableOutcome != "none"
    )


def test_m1_327_snapshot_still_fails_static_action_writeback_order():
    nodes = _workflow()["nodes"]
    connections = {
        "Update Status": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]}
    }

    report = analyze_workflow_semantics(nodes, connections)

    assert "writeback_before_action" in {finding.code for finding in report.findings}
