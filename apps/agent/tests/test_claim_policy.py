from types import SimpleNamespace

from src.agent.claim_policy import (
    claim_exceeds_evidence,
    claimed_outcome,
    safe_evidence_summary,
)
from src.agent.tools.factory import _validate_evidence_gated_output


def test_verified_claim_requires_evidence():
    assert claimed_outcome("Mail başarıyla gönderildi ve satır güncellendi.") == "run_verified"
    assert claim_exceeds_evidence("Mail başarıyla gönderildi.", []) is True


def test_sandbox_evidence_cannot_support_real_run_claim():
    evidence = [{"outcome": "sandbox_passed"}]
    assert claim_exceeds_evidence("Workflow başarıyla çalıştı.", evidence) is True


def test_verified_evidence_supports_claim_and_safe_summary():
    evidence = [{"outcome": "run_verified", "execution_id": "327"}]
    assert claim_exceeds_evidence("Workflow başarıyla çalıştı.", evidence) is False
    assert "327" in safe_evidence_summary(evidence)


def test_negative_statement_is_not_positive_claim():
    assert claimed_outcome("Mail gönderilmedi ve workflow çalışmadı.") == "none"


def test_workflow_updated_is_creation_level_not_real_run():
    assert claimed_outcome("Workflow güncellendi.") == "workflow_created"


def test_waiting_for_approval_does_not_retry_or_overclaim():
    deps = SimpleNamespace(
        claim_evidence=[],
        claim_validation_failures=0,
        awaiting_user_input=True,
        awaiting_user_input_summary=(
            "Önizleme hazır. Henüz gerçek bir gönderim veya güncelleme yapılmadı."
        ),
    )

    result = _validate_evidence_gated_output(
        deps,
        "Workflow başarıyla çalıştı ve mail gönderildi.",
    )

    assert "Önizleme hazır" in result
    assert "Henüz gerçek bir gönderim" in result
    assert deps.claim_validation_failures == 0


def test_generic_clarification_does_not_use_preview_approval_language():
    deps = SimpleNamespace(
        claim_evidence=[],
        claim_validation_failures=0,
        awaiting_user_input=True,
        awaiting_user_input_summary=None,
    )

    result = _validate_evidence_gated_output(
        deps,
        "Workflow başarıyla çalıştı ve mail gönderildi.",
    )

    assert "kullanıcı girdisi bekliyor" in result
    assert "Önizleme hazır" not in result
    assert "onay seçeneklerini" not in result
