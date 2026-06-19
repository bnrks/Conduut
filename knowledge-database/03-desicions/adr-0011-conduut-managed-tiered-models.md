# ADR-0011: Conduut-yönetimli 3-kademe model + routing

Durum: Kabul edildi (2026-06-18). Uygulandı (backend + frontend); escalation Faz 2.

## Bağlam

Önceki mimaride kullanıcı kendi LLM provider'ını bağlıyordu (BYO-provider):
API key Firestore'da, chat'te provider+model+reasoning seçici. Bu hem maliyet/
operasyon kontrolünü kullanıcıya bırakıyordu hem de tutarsızdı (kullanıcı zayıf/
yanlış model seçebiliyor). Ayrıca 2026-06-18 canlı testinde gpt-5'in basit bir
görevde aşırı düşünüp ~716 sn yakması, thinking'in **görev zorluğuna göre**
ayarlanması gerektiğini gösterdi. `repair.py`+`validate_workflow_payload`
formatı deterministik garantilediği için (bkz. [[adr-0010-json-surface-repair-normalizer]])
modelin "frontier reasoning devı" olması gerekmiyor; kademeler hız/maliyet/
tool-calling dengesine göre seçilebilir.

## Karar

BYO-provider **kaldırıldı**. Modeller Conduut'un kendi anahtarlarıyla merkezi
yönetilir. Bir **router** isteği kademeye sınıflandırır; her kademe sabit bir
model + thinking ayarı kullanır. Tercih kullanıcının değil, Conduut'un.

**Profiller** (`CONDUUT_MODEL_PROFILE` = `default` | `gpt`):

| Rol | default | thinking | 2. tercih (GPT) |
|---|---|---|---|
| Router | gpt-5-mini | off (`reasoning:minimal`) | — |
| Basit | claude-haiku-4-5-20251001 | off (`{type:disabled}`) | gpt-5-mini (minimal) |
| Orta | claude-sonnet-4-6 | adaptive + effort=medium | gpt-5.4 (medium) |
| Zor | gemini-3.1-pro-preview | `thinking_level:HIGH` | gpt-5.4 (high) |

> Model id'leri canlı `/models` + generateContent ile doğrulandı (2026-06-19):
> `gemini-3-pro`→`claude-haiku-4-5`→`claude-haiku-4-5-20251001`. **Gemini preview
> id'leri oynak:** `gemini-3-pro-preview` listede görünmesine rağmen Google'ın
> generateContent'inde 404 ("no longer available") verdi → HARD `gemini-3.1-pro-preview`
> olarak güncellendi. Preview rotasyonuna karşı stabil GPT 2.tercihi (gpt-5.4) yedek;
> id ölürse generateContent-probe ile yenisini bul, tek satır registry swap.

- **Her kademe 2. tercihi GPT** (native OpenAI, OpenRouter yok) — kullanıcının
  "tool-calling'de GPT en iyi" deneyimi + full-GPT'ye doğal geçiş. `gpt` profili
  tüm kademeleri OpenAI yapar (tek-switch escape hatch).
- Model id'leri ve provider-bazlı thinking dict'leri `model_registry.py`'de
  **model-başına sabit**; asla runtime'da model adından türetilmez (yanlış shape
  → provider 400; `test_thinking_builder` tam dict'i assert eder).
- **Routing ilkesi:** belirsizlik/router hatası → MEDIUM (workhorse default).
- **Escalation (Faz 2):** repair/validate reddi (`UnexpectedModelBehavior`) ya da
  request-limit (`UsageLimitExceeded`) → önce effort yükselt → GPT 2.tercih →
  üst tier. Runner event_queue'yu canlı stream ettiği ve tool'lar gerçek n8n
  yan etkisi yarattığı için (workflow create/update) yeniden çalıştırma event/
  workflow çoğaltır → bayrak (`CONDUUT_ENABLE_TIER_ESCALATION`) arkasında,
  buffered (yalnız ilk başarılı deneme flush) eklenecek.

## Uygulama

- **Yeni:** `agent/model_registry.py`, `agent/router.py`.
- **Değişti:** `provider_factory.build_model_settings` → provider-aware thinking
  (`ThinkingSpec`); `build_model` korundu (Conduut key). `runner.run` → tier
  routing + per-tier limit. `routes/chat.py` → `ChatRequest(extra=ignore)`.
  `config.py` → `model_profile` + `*_api_key` + `key_for_provider`.
- **Silindi:** `routes/settings.py`, `routes/favorites.py`; store `LLMSettings`/
  `ProviderConnection` + get/save_llm_settings/providers/favorites; provider_factory
  reasoning-effort helper'ları. Frontend: provider/model seçici, `use-model-selector`,
  settings "Assistant Connections" tab'ı, `/api/settings/llm`+`favorites` BFF.
- **Doğrulanan teknik temel:** pydantic-ai 1.88.0 — `anthropic_thinking`/
  `anthropic_effort`, `google_thinking_config` (`thinking_level` gemini-3 /
  `thinking_budget` gemini-2.5), `openai_reasoning_effort`.
- **Test:** backend 207 passed + ruff temiz; frontend tsc temiz + eslint 0 hata.

## Sonuçlar

- (+) Maliyet/operasyon Conduut'ta; tutarlı tool-calling; thinking görev
  zorluğuna göre (gpt-5 aşırı-düşünme sorunu çözülür); 2 sağlayıcı = doğal
  yedek + fiyat hedge'i; tek-switch GPT profili.
- (−) Conduut anahtar/billing yükü; tek paylaşılan key → kullanıcılar arası rate
  limit riski (GPT 2.tercihleri dağıtır); model id churn (canlı doğrulama gerek).
- **Bekleyen:** `.env` anahtarları; canlı model-id doğrulaması + 5-kademe
  bake-off + profil flip; escalation Faz 2.

İlgili: [[adr-0010-json-surface-repair-normalizer]], [[adr-0006-platform-capability-layer]],
[[agent-service]], [[known-issues]].
