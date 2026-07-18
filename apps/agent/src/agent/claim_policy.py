"""Evidence-gated claim levels for user-visible agent responses."""

import re
from typing import Any

CLAIM_LEVELS = {
    "none": 0,
    "workflow_created": 1,
    "sandbox_passed": 2,
    "no_action": 3,
    "run_verified": 4,
}

_RUN_PATTERNS = (
    re.compile(
        r"\b(?:workflow|otomasyon)\s+(?:başarıyla\s+)?"
        r"(?:çalıştı|çalıştırıldı|tamamlandı)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mail|e-?posta|mesaj)\b[^.\n]{0,80}\b(?:gönderildi|atıldı)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:satır|tablo|sheet|durum)\b[^.\n]{0,80}\b(?:güncellendi|işaretlendi)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:workflow|automation)\s+(?:successfully\s+)?"
        r"(?:ran|executed|completed)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mail|email|message|row|sheet|status)\b[^.\n]{0,80}"
        r"\b(?:sent|updated)\b",
        re.IGNORECASE,
    ),
)
_NO_ACTION_PATTERNS = (
    re.compile(r"\b(?:uygun|işlenecek)\s+(?:kayıt|satır)\s+(?:yok|bulunamadı)\b", re.IGNORECASE),
    re.compile(r"\bno\s+(?:eligible|matching)\s+(?:item|row|record)s?\b", re.IGNORECASE),
)
_SANDBOX_PATTERNS = (
    re.compile(r"\bsandbox(?:\s+testi)?\s+(?:geçti|başarılı)\b", re.IGNORECASE),
    re.compile(r"\bsandbox(?:\s+test)?\s+passed\b", re.IGNORECASE),
)
_CREATED_PATTERNS = (
    re.compile(r"\bworkflow\s+(?:oluşturuldu|hazırlandı|güncellendi)\b", re.IGNORECASE),
    re.compile(r"\bworkflow\s+(?:created|built|updated)\b", re.IGNORECASE),
)


def claimed_outcome(text: str) -> str:
    for pattern in _RUN_PATTERNS:
        if pattern.search(text):
            return "run_verified"
    for pattern in _NO_ACTION_PATTERNS:
        if pattern.search(text):
            return "no_action"
    for pattern in _SANDBOX_PATTERNS:
        if pattern.search(text):
            return "sandbox_passed"
    for pattern in _CREATED_PATTERNS:
        if pattern.search(text):
            return "workflow_created"
    return "none"


def highest_evidence_outcome(evidence: list[dict[str, Any]]) -> str:
    best = "none"
    for item in evidence:
        outcome = str(item.get("outcome") or "none")
        if CLAIM_LEVELS.get(outcome, 0) > CLAIM_LEVELS[best]:
            best = outcome
    return best


def claim_exceeds_evidence(text: str, evidence: list[dict[str, Any]]) -> bool:
    return CLAIM_LEVELS[claimed_outcome(text)] > CLAIM_LEVELS[highest_evidence_outcome(evidence)]


def safe_evidence_summary(evidence: list[dict[str, Any]]) -> str:
    outcome = highest_evidence_outcome(evidence)
    if outcome == "run_verified":
        execution_id = next(
            (
                str(item.get("execution_id"))
                for item in reversed(evidence)
                if item.get("execution_id")
            ),
            "",
        )
        suffix = f" (Run #{execution_id})" if execution_id else ""
        return f"Gerçek çalıştırma ve beklenen sonuçlar doğrulandı{suffix}."
    if outcome == "no_action":
        return "Çalıştırma tamamlandı; işlenecek uygun kayıt bulunmadığı için yan etki oluşmadı."
    if outcome == "sandbox_passed":
        return "Yan etkisiz sandbox testi geçti; gerçek bir gönderim veya güncelleme yapılmadı."
    if outcome == "workflow_created":
        return "Workflow oluşturuldu; gerçek çalıştırmanın sonucu henüz doğrulanmadı."
    return (
        "Bu işlem için doğrulanmış bir çalıştırma kanıtı yok; başarıyla tamamlandığını söyleyemem."
    )
