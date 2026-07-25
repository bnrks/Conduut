"""Evidence-gated claim levels for user-visible agent responses."""

import re
from typing import Any

CLAIM_LEVELS = {
    "none": 0,
    "workflow_created": 1,
    "workflow_activated": 2,
    "sandbox_passed": 3,
    "action_verified": 4,
    "no_action": 5,
    "run_verified": 6,
}

# Evidence outcomes are not a single monotonic ladder: ``no_action`` must never
# authorize an action claim, and ``action_verified`` must never authorize a
# whole-workflow success claim. Keep priority only for choosing a safe summary;
# use this explicit compatibility matrix for claim authorization.
_SUPPORTED_CLAIMS = {
    "none": {"none"},
    "workflow_created": {"none", "workflow_created"},
    "workflow_activated": {"none", "workflow_created", "workflow_activated"},
    "sandbox_passed": {"none", "workflow_created", "sandbox_passed"},
    "action_verified": {"none", "workflow_created", "action_verified"},
    "no_action": {"none", "workflow_created", "no_action"},
    "run_verified": {"none", "workflow_created", "run_verified"},
}

_RUN_PATTERNS = (
    re.compile(
        r"\b(?:workflow|otomasyon)\s+(?:başarıyla\s+)?"
        r"(?:çalıştı|çalıştırıldı|tamamlandı)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:workflow|automation)\s+(?:successfully\s+)?"
        r"(?:ran|executed|completed)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:all\s+steps|tüm\s+adımlar)\b[^.\n]{0,80}"
        r"\b(?:completed|succeeded|tamamlandı|başarıyla\s+çalıştı)\b",
        re.IGNORECASE,
    ),
)
_MAIL_ACTION_PATTERNS = (
    re.compile(
        r"\b(?:mail|e-?posta|mesaj)\b[^.\n]{0,80}\b(?:gönderildi|atıldı)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:mail|email|message)\b[^.\n]{0,80}\b(?:sent)\b",
        re.IGNORECASE,
    ),
)
_ROW_ACTION_PATTERNS = (
    re.compile(
        r"\b(?:satır|tablo|sheet|durum)\b[^.\n]{0,80}\b(?:güncellendi|işaretlendi)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:row|sheet|status)\b[^.\n]{0,80}\b(?:updated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ölçüm|veri|kayıt|satır)\b[^.\n]{0,100}"
        r"\b(?:kaydedilecek|kaydedilir|kaydediyor|eklenecek|yazılacak)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:measurement|data|record|row)s?\b[^.\n]{0,100}"
        r"\b(?:will be saved|will be added|will be written|is saved|is added)\b",
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
    re.compile(r"\btest(?:\s+run'?u)?\s+(?:geçti|başarılı)\b", re.IGNORECASE),
    re.compile(r"\btest(?:\s+run)?\s+passed\b", re.IGNORECASE),
    re.compile(
        r"\b(?:hazır|ready)\b[^.\n]{0,80}\b(?:aktif(?:leş)?tir(?:meye)?|activate|run)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bher\s+şey\s+hazır\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:everything|all(?:\s+set)?)\s+(?:is\s+)?ready\b",
        re.IGNORECASE,
    ),
)
_CREATED_PATTERNS = (
    re.compile(r"\bworkflow\s+(?:oluşturuldu|hazırlandı|güncellendi)\b", re.IGNORECASE),
    re.compile(r"\bworkflow\s+(?:created|built|updated)\b", re.IGNORECASE),
)
_ACTIVATED_PATTERNS = (
    re.compile(r"\b(?:workflow|otomasyon)\b[^.\n]{0,40}\baktif\b", re.IGNORECASE),
    re.compile(r"\b(?:workflow|automation)\b[^.\n]{0,40}\bactivated\b", re.IGNORECASE),
)


def claimed_outcome(text: str) -> str:
    for pattern in _RUN_PATTERNS:
        if pattern.search(text):
            return "run_verified"
    if claimed_action_effects(text):
        return "action_verified"
    for pattern in _NO_ACTION_PATTERNS:
        if pattern.search(text):
            return "no_action"
    for pattern in _SANDBOX_PATTERNS:
        if pattern.search(text):
            return "sandbox_passed"
    for pattern in _ACTIVATED_PATTERNS:
        if pattern.search(text):
            return "workflow_activated"
    for pattern in _CREATED_PATTERNS:
        if pattern.search(text):
            return "workflow_created"
    return "none"


def claimed_action_effects(text: str) -> set[str]:
    effects: set[str] = set()
    if any(pattern.search(text) for pattern in _MAIL_ACTION_PATTERNS):
        effects.add("gmail_message_sent")
    if any(pattern.search(text) for pattern in _ROW_ACTION_PATTERNS):
        effects.add("sheets_row_updated")
    return effects


def highest_evidence_outcome(evidence: list[dict[str, Any]]) -> str:
    best = "none"
    for item in evidence:
        outcome = str(item.get("outcome") or "none")
        if CLAIM_LEVELS.get(outcome, 0) > CLAIM_LEVELS[best]:
            best = outcome
    return best


def claim_exceeds_evidence(text: str, evidence: list[dict[str, Any]]) -> bool:
    claim = claimed_outcome(text)
    if claim == "none":
        return False
    latest = evidence[-1] if evidence else {"outcome": "none"}
    outcome = str(latest.get("outcome") or "none")
    if claim == "action_verified":
        required_effects = claimed_action_effects(text)
        verified_effects = {
            str(effect) for effect in (latest.get("effects") or []) if str(effect).strip()
        }
        return not (
            outcome in {"action_verified", "run_verified"}
            and bool(required_effects)
            and required_effects.issubset(verified_effects)
        )
    return claim not in _SUPPORTED_CLAIMS.get(outcome, {"none"})


def safe_evidence_summary(evidence: list[dict[str, Any]]) -> str:
    latest = evidence[-1] if evidence else {"outcome": "none"}
    outcome = str(latest.get("outcome") or "none")
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
    if outcome == "action_verified":
        execution_id = next(
            (
                str(item.get("execution_id"))
                for item in reversed(evidence)
                if item.get("execution_id")
            ),
            "",
        )
        suffix = f" (Run #{execution_id})" if execution_id else ""
        effects = {str(effect) for effect in (latest.get("effects") or [])}
        action = "Mail gönderimi" if "gmail_message_sent" in effects else "Dış aksiyon"
        return (
            f"{action} n8n execution kanıtıyla doğrulandı"
            f"{suffix}; ancak workflow'un uçtan uca sözleşme doğrulaması hâlâ kısmi."
        )
    if outcome == "no_action":
        return "Çalıştırma tamamlandı; işlenecek uygun kayıt bulunmadığı için yan etki oluşmadı."
    if outcome == "sandbox_passed":
        return "Yan etkisiz sandbox testi geçti; gerçek bir gönderim veya güncelleme yapılmadı."
    if outcome == "workflow_activated":
        return "Workflow aktif; gerçek bir gönderim veya veri yazma işlemi henüz doğrulanmadı."
    if outcome == "workflow_created":
        return "Workflow oluşturuldu; gerçek çalıştırmanın sonucu henüz doğrulanmadı."
    return (
        "Bu işlem için doğrulanmış bir çalıştırma kanıtı yok; başarıyla tamamlandığını söyleyemem."
    )
