from src.agent.runner import _ClaimGatedTextEmitter


def test_stream_claim_gate_holds_partial_sentence_until_evidence_check():
    gate = _ClaimGatedTextEmitter([])

    assert gate.feed("Workflow başarıyla çalış") == ""
    released = gate.feed("tı.")

    assert "doğrulanmış bir çalıştırma kanıtı yok" in released
    assert "başarıyla çalıştı" not in released


def test_stream_claim_gate_allows_verified_sentence():
    gate = _ClaimGatedTextEmitter(
        [
            {
                "outcome": "run_verified",
                "execution_id": "42",
                "effects": ["gmail_message_sent", "sheets_row_updated"],
            }
        ]
    )

    assert gate.feed("Workflow başarıyla çalıştı.") == "Workflow başarıyla çalıştı."


def test_stream_claim_gate_does_not_delay_normal_explanation_after_sentence():
    gate = _ClaimGatedTextEmitter([])

    assert gate.feed("Önce filtre koşulunu kontrol ettim.\n") == (
        "Önce filtre koşulunu kontrol ettim.\n"
    )
    assert gate.finish_model_response() == ""
