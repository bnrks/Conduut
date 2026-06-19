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
- [[system-architecture]] - MVP mimarisi ve uzun vadeli hedef mimari.
- [[web-app]] - Next.js frontend, route yapisi, auth ve BFF API route'lari.
- [[agent-service]] - FastAPI agent, SSE chat flow, LiteLLM ve Firestore.
- [[n8n-registry]] - n8n node/template bilgisi ve lookup-first workflow uretimi.
- [[chat-workflow-generation]] - chat deneyimi ve workflow olusturma akisi.
- [[artifacts]] - Sheets sonuc onizleme kartlari ve gelecekteki artifact modeli.
- [[feature-backlog]] - ileride eklenecek ozellikler ve kabul kriterleri.
- [[dashboard]] - dashboard sayfalari ve real/mock ayrimi.
- [[agent-instructions]] - Claude, Copilot ve Codex yonerge haritasi.
- [[known-issues]] - bilinen teknik borclar ve dikkat edilmesi gerekenler.
- [[issue-backlog]] - kullanicinin fark ettigi cozulmesi gereken sorunlar ve
  buglar icin triage bekleyen not alani.

## Kararlar

- [[adr-0001-shared-n8n-mvp]] - MVP'de shared n8n instance kullanimi.
- [[adr-0002-firestore-mvp]] - MVP'de Firestore kullanimi.
- [[adr-0003-google-oauth-broker-mvp]] - Gmail Send icin Conduut-managed
  Google OAuth broker karari.
- [[adr-0004-parameterized-workflow-inputs]] - Workflow run sirasinda
  dashboard ve agent'in ortak runtime input contract kullanmasi.
- [[adr-0005-workflow-spec-compiler]] - Fine-tune yerine WorkflowSpec IR ve
  deterministic compiler ile n8n JSON uretimini daraltma karari.
- [[adr-0006-platform-capability-layer]] - Agent'in n8n builder olmaktan
  platform capability/action katmanina evrilmesi ve Google V1 karari.
- [[adr-0007-batch-workflow-runs]] - Runtime input alanli workflow'lari
  Conduut tarafinda dosya satirlariyla batch/loop calistirma karari.
- [[adr-0008-typed-workflow-intent-engine]] - Raw n8n JSON uretimi yerine
  typed intent + profile engine yoluna gecis karari. **DIKKAT (2026-06-07):
  implementasyon geri alindi/park edildi; aktif yol hala WorkflowPlan
  compiler.**
- [[adr-0009-workflow-graph-compiler]] - WorkflowGraph IR + genel graph
  compiler (curated block registry + generic n8n: fallback + rol etiketli
  port cikarimi). **DIKKAT (2026-06-14): [[adr-0010-json-surface-repair-normalizer]]
  ile model yuzeyinden kaldirildi; artik dahili kutuphane.**
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

## Kaynak Dokumanlar

- Root `AGENTS.md` Codex icin guncel calisma rehberi.
- Root `CLAUDE.md` 2026-04-13 itibariyla onceki Claude oturumlarindan gelen
  en guncel proje ozeti.
- `PROJECT.md` uzun vadeli urun ve mimari vizyonu.
- `BRAND.md` marka, renk, logo ve tipografi kararlari.
- `.claude/*` ve `.github/copilot-instructions.md` onceki agent talimatlari;
  bazi kisimlari tarihsel veya stale olabilir.

## Guncelleme Kurali

Onemli feature, bug fix, mimari karar, entegrasyon, test sonucu veya bilinen
sorun degistiginde ilgili notu guncelle. Gerekirse yeni not ac ve buradan linkle.
