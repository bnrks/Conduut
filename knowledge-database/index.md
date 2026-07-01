---
aliases:
  - Conduut Hub
  - Project Center
  - Home
tags:
  - hub
  - project-center
---

# Conduut Knowledge Database

Bu vault'un merkezi notu burasidir. Conduut projesi icin kalici proje hafizasi
olarak kullanilir. Yeni bir sohbette once buradan basla, sonra sadece gerekli
kod/dokuman kisimlarini ac.

Butun ana proje notlari bu sayfaya geri link verir; Obsidian graph'ta
`index.md` projenin hub node'u olacak sekilde tasarlanmistir.

## Ana Harita

- [[project-overview]] - urun fikri, hedef kitle, deger onerisi.
- [[current-state]] - mevcut repo gercegi, calisan ve eksik kisimlar.
- [[workspace-refactor]] - disardan-ice workspace refactor/temizlik turlari ve
  ertelenen kalemler (Faz 1: root dizin temizligi).
- [[system-architecture]] - MVP mimarisi ve uzun vadeli hedef mimari.
- [[web-app]] - Next.js frontend, route yapisi, auth ve BFF API route'lari.
- [[agent-service]] - FastAPI agent, SSE chat flow, Pydantic AI ve Firestore.
- [[agent-platform-self-awareness]] - agent'in platform oz-farkindaligi: statik
  oz-bilgi profili (platform_profile.py) + dinamik kullanici durumu
  (platform_state.py) + disclosure/proaktiflik politikasi.
- [[n8n-registry]] - n8n node/template bilgisi ve lookup-first workflow uretimi.
- [[chat-workflow-generation]] - chat deneyimi ve workflow olusturma akisi.
- [[artifacts]] - Sheets sonuc onizleme kartlari ve gelecekteki artifact modeli.
- [[feature-backlog]] - ileride eklenecek ozellikler ve kabul kriterleri.
- [[dashboard]] - dashboard sayfalari ve real/mock ayrimi.
- [[agent-instructions]] - Claude Code ve Codex yonerge haritasi (kanonik: `AGENTS.md`).
- [[known-issues]] - bilinen teknik borclar ve dikkat edilmesi gerekenler.
- [[issue-backlog]] - kullanicinin fark ettigi cozulmesi gereken sorunlar ve
  buglar icin triage bekleyen not alani.

## Arastirma

- [[model-cost-research-2026-06]] - Ucuz medium-tier model alternatifleri (DeepSeek V4,
  Qwen 3.6/3.7) fiyat/tool-calling/saglayici karsilastirmasi + DeepSeek bake-off branch
  karari. [[adr-0011-conduut-managed-tiered-models]] ile iliskili.
- [[claude-vs-deepseek-comparison-2026-06]] - Sonnet 4.6 -> DeepSeek V4 gecisinin her
  boyutta karsilastirmasi (maliyet/guvenilirlik/build/UX/operasyonel) + verdict.

## Kararlar

- [[adr-0001-shared-n8n-mvp]] - MVP'de shared n8n instance kullanimi.
- [[adr-0002-firestore-mvp]] - MVP'de Firestore kullanimi.
- [[adr-0003-google-oauth-broker-mvp]] - Gmail Send icin Conduut-managed
  Google OAuth broker karari.
- [[adr-0004-parameterized-workflow-inputs]] - Workflow run sirasinda
  dashboard ve agent'in ortak runtime input contract kullanmasi.
- [[adr-0005-workflow-spec-compiler]] - Fine-tune yerine WorkflowSpec IR ve
  deterministic compiler ile n8n JSON uretimini daraltma karari. **SUPERSEDED
  ([[adr-0010-json-surface-repair-normalizer]]); kod Faz 3'te silindi.**
- [[adr-0006-platform-capability-layer]] - Agent'in n8n builder olmaktan
  platform capability/action katmanina evrilmesi ve Google V1 karari.
- [[adr-0007-batch-workflow-runs]] - Runtime input alanli workflow'lari
  Conduut tarafinda dosya satirlariyla batch/loop calistirma karari.
- [[adr-0008-typed-workflow-intent-engine]] - Raw n8n JSON uretimi yerine
  typed intent + profile engine yoluna gecis karari. **SUPERSEDED: park edildi
  (2026-06-07); aktif yol tek-JSON yuzeyi
  [[adr-0010-json-surface-repair-normalizer]], IR kodu Faz 3'te silindi.**
- [[adr-0009-workflow-graph-compiler]] - WorkflowGraph IR + genel graph
  compiler (curated block registry + generic n8n: fallback + rol etiketli
  port cikarimi). **SUPERSEDED ([[adr-0010-json-surface-repair-normalizer]],
  2026-06-14); kod Faz 3'te (2026-06-30) tamamen silindi.**
- [[adr-0010-json-surface-repair-normalizer]] - Tek JSON yuzeyi (kompakt n8n
  JSON) + onarici normalizer (`repair.py`). Model IR yerine native JSON yazar;
  uc klasik ham-yol bug'i (sub-node main wiring, `{{input.x}}`, `$json.body`
  atlama) deterministik onarilir. IR tool'lari kaldirildi.
- [[adr-0011-conduut-managed-tiered-models]] - BYO-provider kaldirildi;
  Conduut-yonetimli 3-kademe model (basit/orta/zor) + router. Her kademe sabit
  model + thinking; her kademe 2.tercih=GPT; `CONDUUT_MODEL_PROFILE`=default|gpt
  (tek-switch full-GPT). Yeni `model_registry.py` + `router.py`.
- [[adr-0012-custom-http-credentials]] - Custom (HTTP) credential kutuphanesi:
  Header/Basic/Query/Custom Auth, secret n8n'de + metadata Firestore'da, host'a
  gore deterministik eslestirme, onay-once baglama (`attach_credential`),
  dashboard + chat-ici yonetim. Yeni `credential_types.py` + `tools/credentials.py`.
- [[adr-0013-agent-managed-credentials]] - Agent API auth'unu Gemini grounding
  ile arastirir (provider-bagimsiz, decoupled), secret'siz taslak credential
  olusturur; kullanici secret'i chat/dashboard'da sonra doldurur (finalize → n8n
  create + attach). Paylasimli `api_auth_cache`. Yeni `research.py` +
  `prepare_api_credential`. Detay: [[agent-managed-credentials-design]].
- [[adr-0014-workflow-sandbox-test]] - Build sonrasi yan-etkisiz sandbox test
  (aksiyon node'larini nötralize et / disabled) + 3 katmanli gecme kriteri
  (hata / bos cikti / LLM yargisi) + 2 denemeye kadar self-repair (ModelRetry
  dongusu); basarisizsa workflow "needs_attention". Yeni `sandbox.py` +
  `sandbox_nodes.py` + `tools/sandbox_gate.py`.
- [[adr-0015-predefined-credential-library]] - n8n hazir (predefined) credential
  tipleri (openAiApi vb.) birlesik Credentials kutuphanesine type-matched alt-tur
  olarak; dinamik katalog (registry + OAuth ayiklama) + alanlar n8n semasindan;
  `add_service_credential` tool + dashboard servis secici. Connections = servise
  n8n-disi direkt erisim (degismez).
- [[adr-0016-segmented-agent-messages]] - Agent run'inin cok-turlu narrasyonu tek
  balona yapistirilmiyor; her tur ayri balon + aralarinda tek satir aktivite
  (interleaved, ChatGPT/Claude gibi). `token<->tool_call` cikariminla `steps`
  (text/activity), `content` history icin korunur, `len>1` esigi, geriye uyumlu.
  Yeni `step_assembler.py` + internal-context echo leak fix (`strip_internal_context`).
- [[adr-0017-workflow-result-presentation]] - Dashboard workflow run sonucu ham JSON
  yerine anlamli kart. Agent build-time `output_schema` bildirir (input_schema aynasi),
  `resources.output_schema`'ya yazilir, run'da webhook govdesi semaya gore deterministik
  `presentation`'a cozulur (isimli-alan eslemesi, tek-item, non-error; tam govdeden,
  preview-kirpmasi degil). Frontend format-duyarli `WorkflowResultView`; ham JSON
  `<details>` fallback. Yeni `tools/output_schema.py` + `workflow-result-view.tsx`.

## Kaynak Dokumanlar

- Root `AGENTS.md` — **tum coding agent'lar icin kanonik** calisma rehberi.
- Root `CLAUDE.md` — ince pointer (AGENTS.md + bu vault'a yonlendirir; eski
  "son oturum ozeti" gunlugu `99-archive/claude-md-snapshot-2026-06-29.md`'de).
- `PROJECT.md` uzun vadeli urun ve mimari vizyonu.
- `BRAND.md` marka, renk, logo ve tipografi kararlari.
- `.claude/*` Claude Code tooling'i (subagent'lar, skills). Copilot talimat
  dosyalari Faz 2'de kaldirildi.

## Guncelleme Kurali

Onemli feature, bug fix, mimari karar, entegrasyon, test sonucu veya bilinen
sorun degistiginde ilgili notu guncelle. Gerekirse yeni not ac ve buradan linkle.
