# Ucuz Model Alternatifleri Araştırması (2026-06)

> Bağlam: [[adr-0011-conduut-managed-tiered-models]] ile Conduut-yönetimli 3-kademe
> model yapısı kuruldu. Medium tier şu an **Claude Sonnet 4.6** ($3/$15 per 1M) ve
> isteklerin çoğu bu kademeye düşüyor → maliyet yüksek. Bu not, **DeepSeek V4** ve
> **Qwen 3.6/3.7** alternatiflerinin bizim tool-heavy n8n workflow üretimi senaryomuza
> uygunluğunu araştırır. Kaynak: deep-research harness (23 kaynak, 110 iddia, 25
> adversarial doğrulama, 12 onaylandı). Tarih: 2026-06-24.

## ⚠️ Veri güveni notu

- **Fiyat/yetenek** bilgileri first-party dokümanlardan **yüksek güvenle** doğrulandı
  (DeepSeek API docs, Alibaba Model Studio).
- **Tool-calling güvenilirliği** kanıtı **zayıf**: tekil GitHub issue'larına dayanıyor,
  bağımsız standart agentic benchmark (Scale SEAL / SWE-bench Pro) **yok**. Gerçek
  production oranı bilinmiyor → **canlı A/B testi şart**.
- Tüm fiyatlar Haziran 2026 itibarıyladır; karar öncesi tekrar doğrula.

## 1. Fiyat karşılaştırması (per 1M token, cache-miss)

| Model | Input | Output | Sonnet'e göre | Sağlayıcı | Güven |
|---|---|---|---|---|---|
| **Claude Sonnet 4.6** (mevcut medium) | $3.00 | $15.00 | — (baz) | Anthropic | — |
| **DeepSeek V4 Pro** | $0.435 | $0.87 | ~7x / ~17x ↓ | DeepSeek first-party | 🟢 yüksek |
| **DeepSeek V4 Flash** | $0.14 | $0.28 | ~20x / ~50x ↓ | DeepSeek first-party | 🟢 yüksek |
| **qwen-plus** | $0.40 | $1.20 | ~7.5x / ~12x ↓ | Alibaba DashScope | 🟢 yüksek |
| **qwen3.7-plus** | $0.32* | $1.28* | ~9x / ~12x ↓ | DashScope/OpenRouter | 🟡 orta |
| qwen3-max (flagship) | $1.20 | $6.00 | ~2.5x ↓ | DashScope | 🟢 yüksek |

\* qwen3.7-plus fiyatı **%20 promosyonlu**, ~2 Temmuz 2026'da bitiyor → sonrası ~$0.40/$1.60.

**Notlar:**
- **DeepSeek V4 = iki varyant:** `deepseek-v4-flash` (ucuz/hızlı) ve `deepseek-v4-pro`
  (güçlü). İkisi de Tool Calls ✓ + JSON Output ✓ destekler. 1M context.
- Legacy `deepseek-chat` / `deepseek-reasoner` isimleri Flash'ın non-thinking/thinking
  modlarına maplenir → **2026-07-24'te deprecate**. Yeni isimleri kullan.
- **Qwen 3.6:** doğrulanmış per-token fiyatı **bulunamadı** (sadece self-hosted
  Ollama tool-drift issue'su). Qwen tarafında somut adaylar: `qwen-plus`, `qwen3.7-plus`.
- **Prompt caching:** Hem DeepSeek hem Qwen agresif cache indirimi sunuyor (DeepSeek
  cache-hit input **$0.0028**!). Agent her turda büyük system prompt + registry
  gönderdiği için cache kullanımı net tasarrufu ciddi artırabilir.

## 2. Tool-calling güvenilirliği (bizim için EN KRİTİK boyut)

Senaryomuz 12-request / 32-tool-call multi-turn döngü; tek bozuk tool call sistemi çökertir.

- 🔴 **DeepSeek V4 Pro:** GitHub `deepseek-ai/DeepSeek-V3#1244` — model bazen tool call'ı
  `tool_calls` alanı yerine **düz metin (content)** olarak döndürüyor (~%11 / 19'da 2,
  non-deterministik, `finish_reason='stop'`). API formatı uyumlu; bu ayrı bir
  *reliability* sorunu. **Bizim için doğrudan tehdit.** Hafifletme: mevcut
  `repair.py` + `ModelRetry` + sandbox guard'larımız (ADR-0010/0014) kısmen telafi
  edebilir → ama retry maliyeti ucuzluğu eritebilir, **ölçülmeli**.
- 🟡 **Qwen ailesi:** Multi-turn'de `<tool_call>` tag drift (açılış tag atlama, stray
  closing tag). **ÖNEMLİ:** Çoğunlukla **self-hosted** bağlamdan (FP8/GGUF,
  llama.cpp/vLLM/Ollama, default chat template). DashScope **hosted API tool parsing'i
  kendi içinde yapıyor**, bu hatayı gösterdiği kanıtlanmadı → Qwen kullanılacaksa
  **self-host etme, DashScope hosted kullan**.
- ⚠️ **Hiçbiri için bağımsız agentic benchmark yok.**

## 3. OpenRouter dışı sağlayıcılar

| Model | Sağlayıcı | API tipi | Tool calling | Not |
|---|---|---|---|---|
| DeepSeek V4 Pro/Flash | **DeepSeek (first-party)** | OpenAI-uyumlu | ✓ Tool Calls + JSON | **En ucuz**, `base_url=https://api.deepseek.com` |
| DeepSeek V4 Pro | Together AI | OpenAI-uyumlu | ✓ Function Calling + JSON Mode | $1.74/$3.48 (first-party'den pahalı) |
| DeepSeek V4 Pro | Fireworks, DeepInfra, Nebius, SiliconFlow, Novita, Azure, GMI, Lightning | OpenAI-uyumlu | ✓ (çoğu) | Toplam 10+ sağlayıcı, OpenRouter hariç |
| Qwen (plus/max/3.7) | **Alibaba DashScope (first-party)** | OpenAI-uyumlu (`compatible-mode/v1`) | ✓ native, multi-round | `tool_choice` yalnız `auto`/`none` (belirli tool zorlanamaz) |

**Entegrasyon:** DeepSeek de DashScope de OpenAI-uyumlu → mevcut `provider_factory.py`
OpenAI yolundan (`OpenAIChatModel` + `OpenAIProvider(base_url=...)`) eklenir. LiteLLM
ikisini de native destekler (`deepseek`, `dashscope`).

## 4. Net tavsiye

**Birinci aday: DeepSeek V4 Pro (first-party API).** En iyi maliyet/uyumluluk dengesi,
OpenRouter dışı, 1M context. Risk: %11 plain-text-tool-call → canlı izle.
Bütçe-agresif: **DeepSeek V4 Flash** (basit görevler için). İkinci aday: **qwen-plus
(DashScope)** ama `tool_choice` kısıtı + promo-bağımsız fiyat. `qwen3-max` flagship →
medium değil, **HARD tier** (Gemini 3 Pro) alternatifi olabilir.

## 5. Karar öncesi açık sorular

- DeepSeek #1244 hatası first-party hosted API'de mi görülüyor? `repair`/`ModelRetry`
  guard'larımız yeterli mi?
- Gerçek **blended maliyet**: ucuz model daha sık retry/escalate ettirirse net tasarruf
  ne kadar kalır? (ADR-0011 escalation + ADR-0014 sandbox retry dahil ölçülmeli.)
- DashScope `tool_choice` kısıtı forced-tool ihtiyacımızı bozar mı?
- Qwen 3.6 DashScope hosted fiyatı + tool-calling güvenilirliği (doğrulanamadı).

## 6. Uygulama kararı — DeepSeek bake-off branch'i (2026-06-24)

Kullanıcı DeepSeek tarafını canlı denemeye karar verdi. **Branch:** `feature/deepseek-tier-bakeoff`.
- Provider: **deepseek** (first-party, `base_url=https://api.deepseek.com`, OpenAI-uyumlu).
- Yeni `PROFILE_DEEPSEEK` profili (`model_registry.py`), `CONDUUT_MODEL_PROFILE=deepseek`
  ile aktif (bu branch'te default `deepseek`):
  - Router → `deepseek-v4-flash` (cheap classifier, thinking off)
  - **SIMPLE → `deepseek-v4-flash`**
  - **MEDIUM → `deepseek-v4-pro`**
  - **HARD → `deepseek-v4-pro`**
  - Secondary'ler de DeepSeek (saf bake-off; secondary runtime'da henüz kullanılmıyor).
- Thinking: ilk bake-off'ta DeepSeek için **kapalı/gönderilmiyor** (OpenAI-uyumlu
  endpoint `openai_reasoning_effort`'u DeepSeek paramı değil; model adı Pro/Flash
  yeteneği belirler). İleride tune edilebilir.
- **Gereken:** `.env`'e `CONDUUT_DEEPSEEK_API_KEY=...` eklenmeli. Model id'leri
  (`deepseek-v4-flash`/`deepseek-v4-pro`) canlı `https://api.deepseek.com/models` ile
  doğrulanmalı (ADR-0011'deki gibi).
- **Ölçüm araçları (2026-06-24 eklendi):**
  - `runner.py` artık her run sonunda `agent_run_finished`'a token usage ekliyor
    (`input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_write_tokens`/
    `model_requests`/`usage_tool_calls`; `result.usage()`, try/except'li). Bound
    context zaten `provider`/`model`/`tier`/`profile` taşıdığı için maliyet
    modele atfedilebilir.
  - `scripts/analyze_bakeoff_logs.py` — `logs/agent/conduut-agent.jsonl`'i parse
    edip modele göre gruplar: (1) **reliability** = fail rate + fail tipleri
    (`agent_unexpected_model_behavior`=bozuk/eksik tool-call/retry tükendi,
    `agent_usage_limit_exceeded`=bütçede yakınsayamadı, `agent_run_error`),
    (2) **build kalitesi** = `workflow_repaired` (deterministic repair tipleri) +
    sandbox (passed/failed/needs_attention/retry), (3) **maliyet** = token toplamı
    + tahmini USD (DeepSeek/Sonnet fiyat tablosu gömülü). `--since 2026-06-24` ile
    bake-off run'larını izole et; `--model deepseek-v4-pro` ile daralt.
  - **Baz çizgi (mevcut loglardan, Sonnet):** 31 run, **%3.1 fail**, 113 tool call,
    17 run'da 100 deterministic repair (`filled id`=62, email-attribution=16,
    linear-wiring=11, webhook-responseMode=9, resourceLocator=2). DeepSeek bunun
    altında/üstünde mi → kıyas hedefi. (gpt-5 baz: %10.2 fail.)
- **Sonraki adım:** Canlı bake-off — 5-10 gerçek workflow senaryosu (webhook+AI
  Agent+Gmail, Sheets, HTTP+credential), `analyze_bakeoff_logs.py --since <bugün>`
  ile ölç: (a) tool-call hata/retry oranı, (b) build başarı oranı, (c) gerçek token
  maliyeti. Sonuç iyiyse ADR-0015 olarak kalıcılaştır.

## 7. Canlı bulgular (2026-06-24, ilk koşu)

İlk SIMPLE görevler `deepseek-v4-pro`'ya gitti (flash'a değil) → kök neden bulundu ve düzeltildi:

- 🔴 **DeepSeek V4 thinking modu forced tool_choice'u reddediyor.** `deepseek-v4-flash`/
  `deepseek-v4-pro` **varsayılan thinking ON**; router `output_type=TierDecision`
  (structured output → forced tool_choice) kullanınca DeepSeek `400 "Thinking mode does
  not support this tool_choice"` döndürüyor → `classify_tier` her seferinde MEDIUM'a
  fallback → her şey pro'ya gidiyordu. **Fix:** `build_model_settings` deepseek için
  `{"extra_body": {"thinking": {"type": "disabled"}}}` gönderiyor
  (https://api-docs.deepseek.com/guides/thinking_mode). **Canlı kanıt:** forced
  tool_choice çağrısı extra_body'siz `400`, extra_body ile `200`+tool_call. Ana agent
  (auto tool_choice) thinking ON'da bile çalışıyordu; yalnız forced-tool yolu kırılıyordu.
- 🟡 **402 Insufficient Balance** (ilk istekte) — DeepSeek hesap bakiyesi; sonraki
  istekler 402 almadı, muhtemelen çözüldü ama bake-off sırasında bakiyeyi takip et.
- 🔧 **Log redaction bug'ı (Conduut tarafı):** token alanları `[REDACTED]` çıkıyordu —
  `_SECRET_KEY_PARTS` "token" substring'ini secret sayıyor. Usage alanları
  `tok_in`/`tok_out`/`tok_cache_read`/`tok_cache_write` olarak yeniden adlandırıldı;
  `analyze_bakeoff_logs.py` yeni adları okur ve redacted/eski satırları güvenle atlar.
- 🟢 **Thinking display fix → kural: flash OFF, pro ON.** İlk bake-off thinking'i
  TÜM tier'larda kapatmıştı. Ama thinking kapalıyken DeepSeek-pro reasoning'i **normal
  mesaj `content`'i olarak yazıyor** ("Let me search the nodes…") → chat balonuna sızıyor
  (Sonnet'te thinking ON olduğu için panel'e gidiyordu). Canlı kanıt (runner streaming
  replikası): thinking OFF → ThinkingPart=0, TOKEN=1016 (hepsi mesajda); thinking ON →
  ThinkingPart=1906 (panel'e gider), TOKEN=1576. pydantic-ai DeepSeek `reasoning_content`'i
  ThinkingPart'a mapliyor → mevcut `ThinkingPanel` plumbing'i çalışıyor. **Karar:**
  router + SIMPLE = flash, thinking OFF (router forced tool_choice; SIMPLE hızlı);
  MEDIUM + HARD = pro, **thinking ON** (`create_agent` `output_type=str` → auto
  tool_choice, ON güvenli; 19:48 runs ON'ken çalışmıştı). Maliyet: pro'ya reasoning
  output token'ı ekler (DeepSeek output $0.87/M, küçük) ama retry'ı azaltıp kaliteyi
  artırabilir → §8 cost rakamları thinking-OFF baseline'ıdır, yeni run'lar ON.

## 7b. Robustness fix — execute thrash + trigger koruması (2026-06-25)

Canlı bir MEDIUM senaryosunda (dummyjson→Sheets) bulgu: workflow build oldu, sandbox
geçti (Sheets aksiyon node'u disabled → kör nokta, gerçek exec Sheets'te patladı),
ama agent hatayı **teşhis edemeyince thrash etti**: `execute_workflow`'u tekrar tekrar
denedi, bir update'te **kendi trigger'ını sildi** (Webhook→Manual → n8n 400 "no node to
start"), ve **request_limit (20)'i tüketti** → kullanıcıya generic error. Kök neden:
`execute_workflow`'un gerçek-execution için retry sınırı yoktu (sandbox pretest'in vardı).

**Fix (TDD):** `workflow_runner.execution_retry_guard` (mevcut `workflow_test_attempts`
desenini aynalar) — gerçek-execution başarısızlıklarını workflow başına sayar; 1.
başarısızlıkta model bir kez düzeltebilir, **2. başarısızlıkta dur** ve `stop_retrying=true`
ve talimatla ("tekrar deneme/rebuild etme, kullanıcıya dürüstçe söyle, trigger'ı koru")
döner. `AgentDeps.workflow_execution_failures` eklendi; `execute_workflow` guard'ı çağırır;
`prompt.py`'ye trigger-koruma + over-retry kuralı. **306 passed, ruff temiz.** (Sandbox'ın
aksiyon-node kör noktası ayrı, V1 non-goal — değişmedi.)

## 7c. Conduut catch-22 fix — return-only workflow'lar (2026-06-25)

Credential-free "fetch & return" senaryosu (Webhook→HTTP→Respond to Webhook) **hiç
geçmedi**: DeepSeek doğru yapıyı kurdu ama Conduut iki taraftan bloklıyordu (her model
aynı catch-22'ye düşerdi):
1. **repair `responseMode=lastNode` zorluyordu** → Respond to Webhook node "unused" →
   n8n 500 "Unused Respond to Webhook node found" → sandbox fail.
2. Model Respond node'u kaldırınca → yan-etki aksiyon node'u yok → sandbox **judge'ı**
   boş action listesiyle "No action steps configured" diyor → fail.

Model 3+ dk iki hata arasında thrash etti (tek turda **169.916 input token**). Bu
**DeepSeek değil Conduut** sorunu.

**Fix (TDD, ADR-0010/0014 kapsamı):**
- **repair.py** (`_normalize_webhook_response_mode`): workflow'da `respondToWebhook`
  node'u varsa webhook'a **`responseMode=responseNode`** ata (lastNode değil); yoksa
  eski lastNode davranışı.
- **sandbox.py** (`_evaluate_sandbox_run`): `neutralized` boşsa (return-only/read-only,
  yan-etki yok) judge'ı **atla**, execution başarılıysa **geç** (false "no action steps"
  önlenir).

**Re-run (2026-06-25, conv 9140666d) — başarı + 3. bug:** Workflow build oldu, **çalıştı
(status=success), 9 request, thrash YOK** (önceki 169k-token thrash'e karşı). Fix B çalıştı.
AMA "Unused Respond to Webhook" yine 3x tekrarladı → **3. bug bulundu:** model webhook'a
`responseNode`'u doğru koymuştu ama **`_build_test_clone` clone webhook'una koşulsuz
`responseMode=lastNode` atıyordu** (sandbox.py:66) → clone'da lastNode + Respond node = n8n
"unused" hatası. **Fix:** `_build_test_clone` workflow'da `respondToWebhook` node'u varsa
clone'a `responseNode` atar (yoksa lastNode). +1 sandbox test. **309 passed, ruff temiz.**

**Toplam 308→309 passed, ruff temiz.** Bake-off çıkarımı pekişti: gördüğümüz fail'lerin çoğu
DeepSeek build kalitesi değil, Conduut repair/sandbox bug'larıydı (testlerle yüzeye çıktı).

## 7d. Reliability guard — #1244 buffer+retry (2026-06-25)

Canlı bulgu (conv 979e17c9): IF/branch senaryosunda sandbox geçtikten sonra DeepSeek-pro
`execute_workflow`'u **düz metin olarak** yazıp degenerate loop'a girdi (gerçek tool call
yok, ~7 dk çöp, kullanıcı API'yi durdurdu). Araştırmadaki **#1244 riski canlı gerçekleşti.**

**Çözüm (spec+plan+TDD, 4 task):** DeepSeek provider'ında `runner.run` artık **buffered-retry
guard** kullanıyor (`reliability_guard.py` + `runner._run_buffered_with_retry`):
- Her deneme tüm event'leri **buffer'lar** (canlı stream yerine keep-alive); sonunda
  `looks_like_garbage` ile doğrular (tool-call-as-text / runaway-length / repetition).
- **Temiz** → buffer **simüle-stream** olarak oynatılır (canlı-yazma hissi korunur).
- **Garbage + gerçek aksiyon yok** → baştan **retry** (max 2; `create/update` reuse +
  sandbox self-clean idempotent).
- **Garbage + gerçek aksiyon (`execute`/`platform`) çalıştı** → retry YOK (çift yan etki
  riski); attachment'lar + zarif mesaj. Bayrak: `AgentDeps.real_action_executed`.
- Non-deepseek provider'lar `_run_live` (eski canlı yol) ile değişmeden kalır. Kill switch:
  `config.enable_reliability_guard`.

**UX değişimi:** DeepSeek MEDIUM/HARD run'larında artık build sırasında "çalışıyor"
(keep-alive) görünür, sonra cevap toptan replay edilir (stream hissiyle). **319 passed,
ruff temiz.**

**Canlı doğrulama (2026-06-26, conv b67f6d20):** #5 IF/branch (eski #1244 kaosunun senaryosu)
tertemiz geçti — her iki turda `reliability_guard_clean attempt=1`, garbage yok, false-positive
yok. Buffered+replay normal işleyişi bozmuyor. (#1244 intermittent olduğundan retry bu koşuda
tetiklenmedi.) **Cost-logging fix:** ilk versiyonda buffered yol `usage=None` ile token
loglamıyordu → `_collect_attempt` artık `result.usage()`'ı 4'lü tuple ile geçiriyor →
`_persist_and_done` deepseek maliyetini yine logluyor (bake-off ölçümü korundu).

## 8. İlk bake-off sonuçları (2026-06-24, restart sonrası)

Router fix sonrası 2 SIMPLE + birkaç MEDIUM turu koşuldu. **Sinyal net pozitif.**

- **Routing düzeldi:** SIMPLE → `deepseek-v4-flash`, MEDIUM → `deepseek-v4-pro` (router
  artık `router_classified` üretiyor, fallback yok).
- **Reliability:** restart sonrası **0 hard error**. (Tek `agent_run_error` = restart
  öncesi 402 Insufficient Balance, bakiye; kod/model değil.)
- **Build kalitesi:** pro, quote→email'i kurarken **2 sandbox self-repair turu** istedi
  (Get Quote fail → boş çıktı → PASSED). Self-repair döngüsü (ADR-0014) doğru çalıştı,
  `needs_attention=0`. Sonnet baz çizgisi genelde tek seferde kurar — **build kalitesi
  Sonnet'in biraz altında ama self-repair kapatıyor**. Kullanıcı kararı: tek/çok-tur
  önemli değil, kendi içinde düzeltiyor → temel maliyete bak.
- **Maliyet (gözlemlenen, adil kıyas):**
  - flash SIMPLE: ~$0.0006/run (avg tok_in 10.5k / out 293)
  - pro MEDIUM: **~$0.0024/run** (avg tok_in 56k / out 1.1k; cache hit ~%95, 319k/336k)
  - Sonnet (aynı token): cache'siz ~$0.185, cache'li ~$0.041/run
  - **Fark: cache'siz ~7x (taban garanti), cache'li like-for-like ~17x ucuz.** Önceki
    "~75x" iyimserdi (DeepSeek-cached vs Sonnet-uncached); doğru aralık **7–17x**.
  - DeepSeek cache-read $0.0028/M (Sonnet $0.30/M) → agent'ın büyük system prompt +
    registry'si DeepSeek'te neredeyse bedava → cache avantajı çok büyük.
- **Hız:** thinking kapalı + DeepSeek hızı → düşük latency, kullanıcı "baya hızlı" dedi.
- **Bilinen sınır (yeni değil):** sandbox action node'unu `disabled` ettiği için
  Gmail/OAuth gibi action-node auth hatasını yakalayamaz (V1 non-goal). Bir MEDIUM'da
  gerçek execution **expired Gmail token** ile patladı — model/kod değil, credential.

**Sonraki:** credential-free senaryolar (#3 webhook+HTTP, #4 AI özetleme) ile saf model
build reliability'sini birkaç kez daha ölç; istikrarlıysa **ADR-0015** ile kalıcılaştır
(default profili `deepseek`, escalation ihtiyacı gözden geçir).

## Kaynaklar

- DeepSeek pricing/function calling: https://api-docs.deepseek.com/quick_start/pricing ,
  https://api-docs.deepseek.com/guides/function_calling
- DeepSeek V4 Pro sağlayıcılar: https://artificialanalysis.ai/models/deepseek-v4-pro/providers
- DeepSeek tool-call reliability issue: https://github.com/deepseek-ai/DeepSeek-V3/issues/1244
- Alibaba DashScope function calling: https://www.alibabacloud.com/help/en/model-studio/qwen-function-calling
- Alibaba Model Studio pricing: https://www.alibabacloud.com/help/en/model-studio/model-pricing
- Qwen tool-drift issue: https://github.com/QwenLM/Qwen3-Coder/issues/475
