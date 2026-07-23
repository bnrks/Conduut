from types import SimpleNamespace

from src.agent.claim_policy import (
    claim_exceeds_evidence,
    claimed_outcome,
    safe_evidence_summary,
)
from src.agent.tools.factory import _validate_evidence_gated_output


def test_verified_claim_requires_evidence():
    assert claimed_outcome("Mail başarıyla gönderildi ve satır güncellendi.") == "action_verified"
    assert claim_exceeds_evidence("Mail başarıyla gönderildi.", []) is True


def test_sandbox_evidence_cannot_support_real_run_claim():
    evidence = [{"outcome": "sandbox_passed"}]
    assert claim_exceeds_evidence("Workflow başarıyla çalıştı.", evidence) is True


def test_verified_evidence_supports_claim_and_safe_summary():
    evidence = [{"outcome": "run_verified", "execution_id": "327"}]
    assert claim_exceeds_evidence("Workflow başarıyla çalıştı.", evidence) is False
    assert "327" in safe_evidence_summary(evidence)


def test_action_verified_evidence_supports_mail_claim_but_not_whole_run_claim():
    evidence = [
        {
            "outcome": "action_verified",
            "execution_id": "379",
            "effects": ["gmail_message_sent"],
        }
    ]

    assert claim_exceeds_evidence("Mail gönderildi.", evidence) is False
    assert claim_exceeds_evidence("Workflow başarıyla çalıştı.", evidence) is True
    assert "Run #379" in safe_evidence_summary(evidence)
    assert "kısmi" in safe_evidence_summary(evidence)


def test_no_action_and_action_evidence_are_not_interchangeable():
    assert claim_exceeds_evidence("Mail gönderildi.", [{"outcome": "no_action"}]) is True
    assert (
        claim_exceeds_evidence(
            "İşlenecek uygun kayıt bulunamadı.",
            [{"outcome": "action_verified"}],
        )
        is True
    )


def test_whole_run_claim_wins_when_text_also_contains_action_claim():
    evidence = [
        {
            "outcome": "action_verified",
            "execution_id": "379",
            "effects": ["gmail_message_sent"],
        }
    ]

    assert claimed_outcome("Tüm adımlar tamamlandı ve mail gönderildi.") == "run_verified"
    assert claim_exceeds_evidence("Tüm adımlar tamamlandı ve mail gönderildi.", evidence) is True


def test_gmail_effect_does_not_authorize_sheet_update_claim():
    evidence = [
        {
            "outcome": "action_verified",
            "execution_id": "379",
            "effects": ["gmail_message_sent"],
        }
    ]

    assert claim_exceeds_evidence("Satır güncellendi.", evidence) is True
    assert claim_exceeds_evidence("Mail gönderildi ve satır güncellendi.", evidence) is True


def test_claim_authorization_uses_latest_execution_evidence_only():
    evidence = [
        {
            "outcome": "action_verified",
            "execution_id": "379",
            "effects": ["gmail_message_sent"],
        },
        {"outcome": "no_action", "execution_id": "380"},
    ]

    assert claim_exceeds_evidence("Mail gönderildi.", evidence) is True
    assert "uygun kayıt" in safe_evidence_summary(evidence)


def test_run_verified_still_scopes_specific_action_claims_to_verified_effects():
    evidence = [
        {
            "outcome": "run_verified",
            "execution_id": "381",
            "effects": ["gmail_message_sent"],
        }
    ]

    assert claim_exceeds_evidence("Workflow başarıyla çalıştı.", evidence) is False
    assert claim_exceeds_evidence("Mail gönderildi.", evidence) is False
    assert claim_exceeds_evidence("Satır güncellendi.", evidence) is True


def test_negative_statement_is_not_positive_claim():
    assert claimed_outcome("Mail gönderilmedi ve workflow çalışmadı.") == "none"


def test_workflow_updated_is_creation_level_not_real_run():
    assert claimed_outcome("Workflow güncellendi.") == "workflow_created"


def test_activation_is_distinct_from_real_run_evidence():
    evidence = [{"outcome": "workflow_activated", "workflow_id": "wf-1"}]

    assert claimed_outcome("Otomasyon aktif.") == "workflow_activated"
    assert claim_exceeds_evidence("Otomasyon aktif.", evidence) is False
    assert "henüz doğrulanmadı" in safe_evidence_summary(evidence)


def test_activation_does_not_authorize_future_sheet_write_claim():
    evidence = [{"outcome": "workflow_activated", "workflow_id": "wf-1"}]
    text = "Cihazlardan gelen her ölçüm Google Sheet'e kaydedilecek."

    assert claimed_outcome(text) == "action_verified"
    assert claim_exceeds_evidence(text, evidence) is True


def test_waiting_for_approval_does_not_retry_or_overclaim():
    deps = SimpleNamespace(
        claim_evidence=[],
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


def test_generic_clarification_does_not_use_preview_approval_language():
    deps = SimpleNamespace(
        claim_evidence=[],
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


def test_unsupported_final_claim_is_replaced_without_internal_model_retry():
    deps = SimpleNamespace(
        claim_evidence=[],
        awaiting_user_input=False,
        awaiting_user_input_summary=None,
    )

    result = _validate_evidence_gated_output(
        deps,
        "Workflow başarıyla çalıştı ve tüm satırlar güncellendi.",
    )

    assert result == safe_evidence_summary([])
    assert "Haklısınız" not in result
