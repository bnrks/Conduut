"""Tests for the real-execution anti-thrash guard (execution_retry_guard)."""

from src.agent.schemas import WorkflowRunResultData
from src.agent.tools.workflow_runner import execution_retry_guard


def _ok() -> WorkflowRunResultData:
    return WorkflowRunResultData(
        workflowId="w1",
        status="success",
        summary="done",
        functionalStatus="verified",
        claimableOutcome="run_verified",
    )


def _failed() -> WorkflowRunResultData:
    return WorkflowRunResultData(workflowId="w1", status="error", summary="failed", error="boom")


def test_success_returns_none_and_resets_counter():
    failures = {"w1": 1}
    assert execution_retry_guard(failures, "w1", _ok()) is None
    assert "w1" not in failures


def test_first_failure_allows_one_retry():
    failures: dict[str, int] = {}
    assert execution_retry_guard(failures, "w1", _failed()) is None
    assert failures["w1"] == 1


def test_second_failure_returns_stop_payload():
    failures = {"w1": 1}
    stop = execution_retry_guard(failures, "w1", _failed())
    assert stop is not None
    assert stop["stop_retrying"] is True
    assert stop["success"] is False
    assert stop["workflow_id"] == "w1"
    assert "boom" in stop["error"]
    assert "execute_workflow" in stop["instruction"]
    assert failures["w1"] == 2


def test_error_status_without_status_field_still_counts():
    # A result whose status is not "error"/"failed" but carries an error message
    # must still be treated as a failure (e.g. webhook error with detail).
    result = WorkflowRunResultData(
        workflowId="w1", status="triggered", summary="x", error="late failure"
    )
    failures = {"w1": 1}
    assert execution_retry_guard(failures, "w1", result) is not None


def test_failures_are_isolated_per_workflow():
    failures: dict[str, int] = {}
    assert execution_retry_guard(failures, "wA", _failed()) is None
    assert execution_retry_guard(failures, "wB", _failed()) is None
    assert failures == {"wA": 1, "wB": 1}


def test_partial_functional_result_counts_as_execution_failure():
    result = WorkflowRunResultData(
        workflowId="w1",
        status="success",
        summary="partial",
        functionalStatus="partial",
        claimableOutcome="none",
    )
    failures = {"w1": 1}

    stop = execution_retry_guard(failures, "w1", result)

    assert stop is not None
    assert stop["success"] is False


def test_partial_side_effect_stops_on_first_run_and_requires_reconciliation():
    result = WorkflowRunResultData(
        workflowId="w1",
        status="success",
        summary="partial",
        functionalStatus="partial",
        claimableOutcome="none",
        assessment={"actionCount": 2, "writebackCount": 0, "duplicateRisk": True},
    )
    failures: dict[str, int] = {}

    stop = execution_retry_guard(failures, "w1", result)

    assert stop is not None
    assert stop["stop_retrying"] is True
    assert stop["reconciliation_required"] is True
    assert stop["requires_user_approval"] is True
    assert failures["w1"] == 1
