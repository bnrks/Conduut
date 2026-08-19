# Agent Platform Öz-Farkındalığı

Agent'ın Conduut platformu hakkındaki öz-farkındalığı (ölçüm: ~%53 "kısmi" →
hedef yüksek). İki katman, statik prompt + tool docstring dışında agent'a ilk
kez dinamik bağlam enjekte edilir.

- **Statik öz-bilgi** — `apps/agent/src/agent/platform_profile.py` (TEK KAYNAK):
  `PLATFORM_IDENTITY` + `CAPABILITY_CATALOG` + `BOUNDARIES` +
  `DISCLOSURE_AND_PROACTIVITY`; `render_static_profile()` ile
  `tools/factory.base_instructions()` üzerinden `create_agent` constructor
  instructions'ına gömülür (sabit, cache-dostu önek).
  **Yeni özellik/sınır değişiminde önce burası güncellenir.**
  2026-08-17 itibariyla customer-owned automation server guided setup yetenegi
  ve siniri da buradadir: agent once read-only
  `get_automation_server_setup_step` tool'unu kullanir, tek adim ilerler,
  unsupported OS/architecture'da durur; password, SSH private key, API key,
  encryption key veya token istemez ve pasted terminal output'u untrusted data
  olarak ele alir. Runtime ek olarak setup conversation'ini normal action
  tool'larindan izole eder ve belirgin secret-bearing mesaji persistence/model
  oncesinde reddeder.
- **Dinamik durum** — `apps/agent/src/agent/platform_state.py`: bağlı servisler
  + kayıtlı credential'lar + workflow'lar, `gather_user_state` ile her run
  PARALEL + best-effort toplanır (her kaynak `_safe` ile izole; biri patlarsa
  diğerleri gelir, fonksiyon asla raise etmez), `@agent.instructions`
  (`ctx.deps.platform_state`) ile run-anında `render_user_state` olarak enjekte.

**Wiring:** `runner.run` durumu `classify_tier` ile `asyncio.gather` ile paralel
toplar (ek gecikme ~0) ve `AgentDeps.platform_state`'e koyar (hem live hem
DeepSeek buffered yolu aynı snapshot'ı alır). **`create_agent` imzası
değişmedi** — mevcut test stub'ları korundu (statik=constructor,
dinamik=`@agent.instructions`).

**Disclosure politikası:** içsel sınırlar (shared instance, model tier,
n8n/node jargonu) kullanıcıya SÖYLENMEZ; kullanıcıyı etkileyen sınırlar (yalnız
Google OAuth, batch dashboard'dan, schedule chat'ten test edilemez) SÖYLENİR.
`CAPABILITY_CATALOG` jargonsuz (test'le zorlanır).

**Proaktiflik:** dengeli — doğal bitişte tek ilgili sonraki adım; istenmeden
reklam yok.

**Sonuç:** Backend 400 passed (5 ön-mevcut Windows-tmp, alakasız), ruff temiz.
Her task subagent-driven TDD + per-task review temiz. Final whole-branch review
(opus) 2 Important yakaladı, ikisi de düzeltildi:
- **Cross-user sızıntı (önemli):** `gather_user_state` shared MVP n8n'de
  `list_workflows()` ile TÜM kullanıcıların workflow'larını çekip "senin
  otomasyonların" diye sunuyordu. Fix: per-user metadata ile kesişim
  (`w.id in meta`, fail-closed — metadata yoksa workflow gösterilmez).
  `routes/workflows.py` aynı `list_workflows()` çağrısını TODO ile taşıyor;
  per-user izolasyon gelince ikisi de gerçek user-filtreye dönecek.
- **Seam testi:** `@agent.instructions` decorator'ı gerçek bir agent'a karşı
  test edilmemişti → `FunctionModel` ile gerçek-agent instructions testi eklendi
  (hem statik profil hem dinamik durum modele ulaşıyor mu, falsifiye-edilebilir).
Kalan 2 Minor kozmetik (`tag` boş host+tip → `'label' []`, credential "none"
satırı yok) — bloklamıyor. **Yerel main'e merge edildi (`4f7b1ef`); push
edilmedi (kullanıcı: yerel kalsın).**

İlgili: [[agent-service]], [[adr-0006-platform-capability-layer]],
[[adr-0007-batch-workflow-runs]], [[adr-0011-conduut-managed-tiered-models]].

## Durum
- [x] **Canlı doğrulandı (2026-06-29).** Kullanıcı tüm senaryoları 2 ayrı chat'te
  denedi, sorun görmedi (kimlik/yetenek, sınırlar, dinamik durum, disclosure,
  proaktiflik). Bağımsız log incelemesi (agent bugün 12:03 UTC restart, yeni kod
  canlı): 11 chat → 11 run başladı/bitti/kaydedildi (1:1:1:1), `gather_user_state`
  4 kaynak 11 run'da da başarılı (`platform_state_source_failed`=0), 11
  `reliability_guard_clean`, 0 unhandled hata/usage-limit/retry. Profil DeepSeek —
  öz-farkındalık katmanı DeepSeek tier'ında da sorunsuz. (Disclosure/proaktiflik
  *metni* Firestore mesajlarında kullanıcı tarafından onaylandı; log'lar makineyi
  doğruladı.)
- Feature-dışı gözlem: aynı oturumda 1 `needs_attention` (sandbox gate, ADR-0014
  tasarlanmış dürüst bildirim) + 1 handled `execute_workflow` hatası (gerçek n8n
  çalıştırması başarısız → temiz mesaj). Öz-farkındalık yüzeyinde değil.
