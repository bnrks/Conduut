# Senaryo Bankası — n8n.io Referans-Güdümlü Test & Düzeltme Döngüsü

Merkez: [[index]]

Bu not, Conduut agent'ının workflow üretimini **gerçek insanların oluşturduğu
n8n.io workflow'ları** üzerinden test etme ve hata bulunca **genel** düzeltme
uygulama sürecinin kanonik tanımıdır. Süreç manuel-yargılı bir döngü + büyüyen
bir senaryo bankasıdır. İlgili: [[adr-0010-json-surface-repair-normalizer]],
[[known-issues]], [[adr-0014-workflow-sandbox-test]], [[chat-workflow-generation]],
[[agent-service]].

## Amaç

n8n.io/workflows halka açık kütüphanesi, gerçek kullanıcıların kurduğu
otomasyonlardan oluşur. Bunları iki amaçla kullanırız:

1. **Görev kaynağı** — gerçek bir workflow'u doğal-dil task'a çevirip agent'a
   veririz.
2. **Doğruluk oracle'ı (referans)** — agent hata yaparsa, aynı işi yapan gerçek
   workflow "doğru n8n şekli"ni gösterir; düzeltmeyi bu delta üzerinden buluruz.

**Temel ilke:** başarı = *fonksiyonel doğruluk*, exact-match DEĞİL. Bir workflow
tek bir şekilde kurulmak zorunda değildir; agent farklı bir yapı üretse de
kullanıcının niyetini karşılıyorsa senaryo **geçer**. Referans JSON yalnızca
hata anında kıyas kaynağıdır (agent onu görmez).

## Döngü

```
n8n.io workflow seç  →  doğal-dil task'a çevir (referans yapıyı sakla)
      →  agent'a gerçek chat'ten ver  →  build + activate + run
      →  logs/agent + çıktı + niyet-eşleşmesini incele
      →  [amaca ulaştı mı?]
            EVET → senaryoyu "geçti" işaretle (regresyon listesine girer)
            HAYIR → agent çıktısı ile referans workflow'un DELTA'sını çıkar
                   → GENEL düzeltmeyi ADR-0010 katmanından uygula
                   → orijinal + KARDEŞ senaryoyu tekrar geçir (genellik kanıtı)
                   → sonucu senaryo notuna işle
```

## Çalıştırma & yargı (success oracle = manuel insan yargısı)

- **Ortam:** gerçek chat UI + local agent stack (`start-local-dev.bat`),
  `logs/agent/conduut-agent.jsonl` diagnostic log akışı.
- **Adımlar:** task'ı chat'e yaz → agent build → activate → `execute_workflow`
  veya dashboard run → insan logu + çıktıyı + niyet-eşleşmesini inceler →
  **geçti/kaldı** kararını verir.
- "Farklı yapı ama amacı karşılıyor" = **geçti**. Runtime crash, boş/yanlış
  çıktı, niyeti karşılamama, ya da build/validation reddi = **kaldı**.
- **Model profili:** koşuları **güvenilir profille** (`default` — Sonnet/Gemini)
  yap, DeepSeek bake-off ile değil. `config.py` default'u `model_profile="deepseek"`
  ve o profil canlıda ~10dk **stall→ReadTimeout** verdi (E1 ilk turu, conv
  `1e2e07e5`); bu, workflow-üretim sinyalini kirletir ("takıldı" sanılır). Bkz.
  [[claude-vs-deepseek-comparison-2026-06]].
- Sheets v4 bug'ı hatırlatması: build+validation'dan geçen bir workflow
  **runtime'da** patlayabilir (bkz. [[known-issues]] madde 1). Bu yüzden "workflow
  oluştu" tek başına geçme kriteri değildir — çalıştırıp görmek gerekir.

> **İleride otomasyon (Opsiyon B, ertelendi):** Banka büyüdükçe her senaryo
> `(task, beklenen capability, referans)` üçlüsüne dönüşür; bu tam olarak
> otomatik eval (mevcut [[adr-0014-workflow-sandbox-test]] sandbox run + yapısal
> diff + LLM-judge) için gereken veridir. Bugün manuel kurulan banka, yarının
> regresyon suiti'nin tohumudur.

## Hata → GENEL düzeltme (çekirdek)

En kritik kural: **düzeltme asla tek use-case'e band-aid olamaz.** Benzer task
geldiğinde hata tekrar etmemeli. Uygulama:

1. **Delta çıkar.** Agent'ın ürettiği JSON ile referans workflow'un farkını bul.
   (Örn. Sheets: agent `resource: spreadsheet` + `spreadsheetId` + `range`
   yazmış; referans `resource: sheet` + `documentId` + `sheetName` kullanıyor.)
2. **Doğru katmandan düzelt** ([[adr-0010-json-surface-repair-normalizer]]
   katman hiyerarşisi — en ucuz *doğru genel* katmandan başla):
   1. `repair.py` (deterministik) — tek doğru yorum varsa. Bedava, tüm modeller.
   2. `validation.py` + ModelRetry — belirsiz ama tespit + tarif edilebilirse
      (fix modelin semantik bilgisini ister). İpucu hedef şekli birebir göstermeli.
   3. `few_shots` (seçmeli enjekte) — desen çok sık ya da 1-2 yetmiyorsa.
   4. Prompt kuralı — son çare, en zayıf sinyal.
3. **Genellik guard'ı (zorunlu kanıt).** Fix node-tipi/desen düzeyinde yazılır,
   task metnine değil. Kanıt için fix sonrası şu ikisi de geçmeli:
   - **Orijinal senaryo** (bug'ı bulan).
   - **En az bir KARDEŞ senaryo** — aynı node/desen, farklı yüzey task, fix
     türetilirken kullanılmamış. İkisi de geçmezse fix yeterince genel değildir,
     katmanı/dokunuşu genişlet.
4. **Kaydet.** Semptom → kök-neden → katman → commit → kardeş-doğrulama, senaryo
   notunun "Sonuç geçmişi"ne yazılır. Kök-neden yeni bir sınıfsa [[known-issues]]
   güncellenir.

## Kapsam & kademeler

Seçim ilkesi: **kapsam-içi + kademeli zorluk.** Böylece alınan her hata gerçek,
genel-düzeltilebilir bir bug'a karşılık gelir; kapsam-dışı servis gürültüsü değil.

- **Kapsam-içi node'lar:** Gmail (send/read/trigger), Google Sheets
  (read/append/update), HTTP Request, Webhook, Schedule Trigger, Set/Edit Fields,
  Code, IF, Filter, Merge. (Egzotik/desteklenmeyen servisli workflow'lar bu tur
  dışında; onlar kapsam genişletme kararıdır, repair bug'ı değil.)
- **Kademeler:**
  - **easy** — 1 trigger + 1-2 node, lineer.
  - **medium** — 3-4 node, expression / filter / runtime input.
  - **hard** — dallanma (IF), çok-node, status write-back, per-row döngü.

## Senaryo not şablonu

Her senaryo `scenarios/` altında ayrı bir markdown notudur. Alanlar:

```markdown
# Senaryo <ID> — <kısa başlık>

Merkez: [[scenario-bank]]

- **Zorluk:** easy | medium | hard
- **Kaynak (n8n.io):** <URL>
- **Capability'ler / node'lar:** <liste>
- **Kardeş senaryo(lar):** [[scenario-...]]  (genellik guard için)
- **Risk noktaları:** <bilinen bug hotspot'ları — Sheets v4, resourceLocator,
  $json.body, sub-node wiring, expression, IF/filter...>

## Task (agent'a verilen doğal-dil)

> <n8n/webhook/node terimi geçmeyen, son-kullanıcı niyeti cümlesi>

## Referans yapı (yalnız bizde; agent görmez)

<gerçek workflow'un anahtar node/connection/parametre özeti. Ham JSON hata
anında URL'den çekilir.>

## Beklenen sonuç (fonksiyonel)

<niyet karşılanırsa neye benzer — "geçti" tanımı>

## Sonuç geçmişi

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
```

## İlk tur (9 senaryo)

Manuel için tractable, katmanları kademeli zorlayan başlangıç seti. Kaynaklar
gerçek n8n.io template'leridir.

| ID | Zorluk | Özet | Kaynak |
|----|--------|------|--------|
| [[scenario-e1-webhook-sheets-append]] | easy | Webhook → Google Sheets satır ekle | n8n.io/workflows/1076 |
| [[scenario-e2-gmail-to-sheets-log]] | easy | Gelen mailleri Google Sheet'e logla | n8n.io/workflows/3319 |
| [[scenario-e3-schedule-gmail-reminder]] | easy | Zamanlı hatırlatma maili gönder | n8n.io/workflows/6338 |
| [[scenario-m1-sheets-filter-email]] | medium | Sheet oku → koşula göre süz → mail at | n8n.io/workflows/6338 |
| [[scenario-m2-schedule-http-digest]] | medium | Zamanlı HTTP/RSS çek → formatla → mail | n8n.io/workflows/6223 |
| [[scenario-m3-webhook-http-sheets]] | medium | Webhook → HTTP → normalize → Sheet'e yaz | n8n.io/workflows/13207 |
| [[scenario-h1-cold-outreach-status]] | hard | Sheet oku → süz → mail → satırı "Sent" yaz | n8n.io/workflows/4214 |
| [[scenario-h2-lead-outreach]] | hard | Lead'leri oku → New süz → kişiselleştir → mail (H1 kardeşi) | n8n.io/workflows/6083 |
| [[scenario-h3-website-monitor-alert]] | hard | Zamanlı site kontrol → koşullu uyarı maili | n8n.io/workflows/5067 |

H1 ↔ H2 bilinçli olarak **kardeş** (aynı read→filter→send→update-status deseni,
farklı yüzey). H1'de bulunan bir Sheets-update/column-map düzeltmesi H2'yi de
geçirmelidir → genellik guard'ının canlı örneği.

## Durum ve sonraki adım

- **2026-07-13 yeniden baseline:** Önceki testler sırasında kullanılan patch'ler
  daha sonra topluca geri alındı. Bu nedenle eski koşular tarihsel bulgu olarak
  senaryo notlarında korunur, fakat mevcut kod tabanı için kabul/regresyon kanıtı
  sayılmaz. **9 senaryonun tamamının güncel durumu: TEST EDİLMEDİ.**
- **E1 — GEÇTİ ✅ (2026-07-13):** Workflow `jnaF9rQvckjOhGcX` aktif;
  `Webhook → Google Sheets → Respond` akışı ve iki gerçek webhook execution'ı
  (`#261`, `#262`) başarılı. Tek kalan bulgu fonksiyonel akışta değil, agent'ın
  kullanıcıya yanlış host'lu POST URL'si vermesi: doğru local URL
  `http://localhost:6180/webhook/contact-form` olmalıydı.
- **SONRAKİ: [[scenario-e2-gmail-to-sheets-log]].**
- Yeniden test sırası: **E1 → E2 → E3 → M1 → M2 → M3 → H1 → H2 → H3**.

## Güncelleme kuralı

Yeni senaryo eklenince buradaki tabloya satır ekle. Bir senaryo çalıştırılıp
sonuç alınınca ilgili notun "Sonuç geçmişi"ni güncelle; yeni bir bug sınıfı
çıkarsa [[known-issues]] ve gerekiyorsa ilgili ADR güncellenir.
