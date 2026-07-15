# Senaryo E2 — Gelen mailleri Google Sheet'e logla

Merkez: [[scenario-bank]]

- **Zorluk:** easy
- **Kaynak (n8n.io):** https://n8n.io/workflows/3319-add-new-incoming-emails-to-a-google-sheets-spreadsheet-as-a-new-row
- **Capability'ler / node'lar:** Gmail Trigger, Google Sheets (`sheets.row.append`)
- **Kardeş senaryo(lar):** [[scenario-e1-webhook-sheets-append]] (aynı "trigger → sheet append")
- **Risk noktaları:** external trigger (n8n UI manuel çalıştırabilir; Conduut chat
  runner şu anda yalnız webhook çalıştırabildiği için bu ayrımı doğru anlatmalı),
  Gmail çıktısı → Sheet sütun map'i, Sheets v4 append şeması.

## Task (agent'a verilen doğal-dil)

> Gelen kutuma düşen her yeni e-postanın gönderenini, konusunu ve tarihini bir
> Google Sheet'e otomatik kaydet.

## Referans yapı (yalnız bizde; agent görmez)

- **Gmail Trigger**: yeni mail polling.
- **Google Sheets**: `resource: sheet`, `operation: append`, sütunlar
  `From`, `Subject`, `Date` (Gmail node çıktısındaki `$json.from`, `$json.subject`,
  `$json.date` benzeri alanlardan).
- Bağlantı: Gmail Trigger → Google Sheets.

## Beklenen sonuç (fonksiyonel)

Yeni bir mail geldiğinde Sheet'e gönderen/konu/tarih içeren satır eklenir. Gmail
Trigger external event olduğu için manuel testte yapı doğruluğu + credential
readiness'i yargılanır. n8n UI'daki manuel execution da kabul kanıtı olabilir;
agent gerçek event veya manuel execution sonucu olmadan "çalıştı" iddiasında
bulunmamalı.

## Sonuç geçmişi

**Güncel durum (2026-07-15): GEÇTİ ✅.** Workflow ilk üretimde semantik sütun
eşlemesini yanlış kurdu, fakat kullanıcı yalnızca "otomasyonda bir hata var"
dediğinde agent execution geçmişini inceleyerek hatayı kendisi buldu ve mevcut
workflow'u düzeltti. Bu self-debug akışı, planlanan Executions yüzeyinin agent
tarafından hata ayıklama amacıyla kullanılacağı ürün davranışıyla uyumlu kabul
edildi.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-15 (baştan tekrar) | Geçti ✅ | Conversation `4123f8fb-fa07-4710-af76-da35a6fa5664`, workflow `5aKgzNuxkv1F85yn`. Gmail ve Sheets credential'ları otomatik bağlandı; Sheets v4 yapısal normalizer devreye girdi. İlk workflow'da Sheet başlıkları `Gönderen/Konu/Tarih` iken mapping anahtarları `from/subject/date` kaldığı için manuel execution hata verdi. Kullanıcı hata ayrıntısını vermeden yalnızca hata olduğunu söyledi; agent `list_executions` → `inspect_execution` ile son çalıştırmayı okuyup sütun adı uyuşmazlığını teşhis etti ve `update_workflow` ile mapping'i düzeltti. Tekil bir Sheet'in doğal-dil başlıklarını hard-code eden ek repair/prompt değişikliği yapılmadı: mevcut execution-temelli self-debug beklenen ürün akışını yerine getirdi. Run kanıtları: `4b3fa921`, `f01fd777`, `b2a60c01`. |
| 2026-07-14 (düzeltme) | Tekrar test bekliyor | Repair artık `mappingMode="define"` değerini `defineBelow` olarak canonicalize edip düz `columns.value` map'inden `columns.schema` ve `matchingColumns` sentezliyor. Validator append için desteklenmeyen mode ile eksik `value/schema` şeklini n8n'e ulaşmadan reddediyor. Execution özeti `extra.parameterName` bilgisini hata metnine ekliyor. n8n internal manual-run API'si session cookie + editor push bağlantısı istediği ve public API olmadığı için backend entegrasyonu eklenmedi; Conduut artık sınırı n8n imkânsızlığı gibi sunmak yerine chat'in external trigger'ı manuel başlatamadığını ve editördeki Execute workflow alternatifini açıkça söylüyor. Odaklı toplam `93 passed`; canlı E2 kabul koşusu bekleniyor. |
| 2026-07-14 (tekrar) | Kaldı | İlk workflow `P0d1o2ayQpTxdY49` birkaç update sonrası silindi; `N3MD03PpRP66J9zF` yeniden oluşturulup aktive edildi. OAuth düzeltmesi doğrulandı: Gmail `adWnA5cuE9cHJqr8`, Sheets `zF82n2U62E4RmF6r` bağlı. Ancak Sheets node'u `columns.mappingMode="define"` + `value={from,subject,date}` üretip zorunlu `columns.schema` alanını yazmadı. Execution `265` (`mode=manual`) ve `266` (`mode=trigger`) Gmail Trigger ve Set adımlarını başarıyla geçti, yalnız Google Sheets'te `Could not get parameter`, `parameterName=columns.schema` ile kaldı. Repair yalnız `defineBelow` modunda schema sentezlediği için `define` aliasını kaçırdı; validator append mapping şeklini denetlemiyor. Agent hatayı önce field mapping, sonra credential diye yanlış teşhis edip workflow'u gereksiz sildi/yeniden kurdu. Execution `265`, n8n'in Gmail Trigger workflow'unu manuel çalıştırabildiğini kanıtlıyor; Conduut runner ise webhook yoksa `workflow_run_not_testable` dönüyor. |
| 2026-07-14 | Kaldı; tekrar test bekliyor | Workflow `vBK95qx4vkNPqsbb` için `Gmail Trigger → Set → Google Sheets` yapısı doğru, Sheets credential'i bağlı; Gmail Trigger credential'i boş ve execution yok. Kök neden: readiness yalnız `n8n-nodes-base.gmail` tipini managed Gmail OAuth sayıyor, `n8n-nodes-base.gmailTrigger` tipini dışlıyordu. Bu nedenle mevcut `google_gmail` connection bulunamadı ve fallback canlı n8n OAuth şemasını genel credential kartına çevirerek `serverUrl`/client alanlarını gösterdi. `readiness.py` Gmail Trigger'ı `gmail.message.read` ile managed akışa aldı; tanınmayan OAuth tiplerinin genel secret formuna düşmesi engellendi. Odaklı regresyon testleri eklendi; kabul için E2 canlı yeniden koşulmalı. |
