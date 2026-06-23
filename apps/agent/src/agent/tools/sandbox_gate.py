"""Run the sandbox test after a build and drive the bounded self-repair loop."""

from typing import Any

import structlog
from pydantic_ai import ModelRetry, RunContext

from src import store
from src.agent.sandbox import SandboxTestResult, run_sandbox_test
from src.agent.schemas import AgentDeps
from src.agent.tools.runtime_inputs import _workflow_input_schema_from_metadata

log = structlog.get_logger()

_MAX_TEST_REPAIRS = 2


def _repair_instruction(workflow_id: str, result: SandboxTestResult) -> str:
    findings = "\n".join(f"- {item}" for item in result.findings) or "- Unknown issue."
    return (
        "The workflow was built, but a sandbox test run (no real email/message was sent) "
        "found a problem before it would reach the action step:\n"
        f"{findings}\n\n"
        f"Fix workflow {workflow_id} with update_workflow (same id, full structure) so the data "
        "reaching the action step is complete and correct. Common causes: an upstream node "
        "produces an empty field; an expression like $json.x does not resolve (use $json.body.x "
        "for webhook inputs, or the correct upstream field name); or an array/object mismatch "
        "(e.g. $json[0].x where the item is already $json.x). If the fix needs information the "
        "user did not provide, call request_user_input with one concise question instead."
    )


def _needs_attention_instruction() -> str:
    return (
        "The sandbox test still found a problem after repair attempts. Do NOT claim the workflow "
        "works. Tell the user, in their language and without technical jargon, what would not work "
        "(e.g. the email body would be empty) and ask how they would like to proceed. The workflow "
        "is saved but marked as needing attention."
    )


async def _test_and_gate(
    ctx: RunContext[AgentDeps], workflow: dict[str, Any], name: str, base_result: dict[str, Any]
) -> dict[str, Any]:
    """Sandbox-test a freshly built workflow; loop the model to fix failures.

    Returns ``base_result`` on pass/skip; raises ``ModelRetry`` to drive a fix
    while within budget; returns a ``needs_attention`` result once the budget is
    spent. A harness error never blocks the build.
    """

    workflow_id = str(workflow.get("id") or "")
    await ctx.deps.emit_tool_call("test_workflow")
    try:
        metadata = await store.get_workflow_metadata(ctx.deps.user_id, workflow_id)
        input_schema = _workflow_input_schema_from_metadata(metadata)
        result = await run_sandbox_test(
            workflow, user_id=ctx.deps.user_id, input_schema=input_schema, intent=name
        )
    except Exception as exc:  # noqa: BLE001 - the test must never block a build
        log.warning("sandbox_test_skipped_on_error", workflow_id=workflow_id, error=str(exc))
        return base_result

    if result.skipped:
        await store.save_workflow_test_status(
            ctx.deps.user_id, workflow_id, status="skipped", findings=result.findings
        )
        return base_result

    if result.passed:
        await store.save_workflow_test_status(
            ctx.deps.user_id, workflow_id, status="passed", findings=[]
        )
        return base_result

    attempts = ctx.deps.workflow_test_attempts.get(workflow_id, 0)
    if attempts < _MAX_TEST_REPAIRS:
        ctx.deps.workflow_test_attempts[workflow_id] = attempts + 1
        log.info("sandbox_test_failed_retry", workflow_id=workflow_id, attempt=attempts + 1)
        raise ModelRetry(_repair_instruction(workflow_id, result))

    await store.save_workflow_test_status(
        ctx.deps.user_id, workflow_id, status="needs_attention", findings=result.findings
    )
    out = dict(base_result)
    out["test_status"] = "needs_attention"
    out["test_findings"] = result.findings
    out["instruction"] = _needs_attention_instruction()
    log.info("sandbox_test_needs_attention", workflow_id=workflow_id, findings=result.findings)
    return out
