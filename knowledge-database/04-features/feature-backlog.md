# Feature Backlog

Merkez: [[index]]

Bu not, Conduut'a ileride eklenecek urun/teknik ozellikleri takip etmek icin
kullanilir. Bug ve regresyonlar [[issue-backlog]] icinde, mimari kararlar ise
[[adr-0010-json-surface-repair-normalizer]] gibi ADR notlarinda tutulur.

## Kullanim

Her feature maddesi su bilgileri tasimaya calismali:

- `Durum`: fikir, planlandi, uygulanacak, uygulaniyor, tamamlandi, ertelendi.
- `Alan`: agent, web, n8n-registry, oauth, infra, product.
- `Motivasyon`: kullanici problemi veya teknik gerekce.
- `Kabul kriteri`: feature'in bitti sayilmasi icin gozlenebilir davranis.
- `Ilgili notlar`: Obsidian linkleri.

## Aday Ozellikler

### Workflow Action Registry / Platform Action Pack Refactor

- `Durum`: ertelendi; ilk yeni platform/action eklenirken yeniden
  degerlendirilecek.
- `Alan`: agent, n8n-registry
- `Not (2026-06-30)`: Bu maddenin eski dayanagi olan `WorkflowPlan` action graph
  IR + `spec_compiler.py` derleyicisi **kaldirildi**
  ([[adr-0010-json-surface-repair-normalizer]], [[workspace-refactor]] Faz 3).
  Aktif yol artik tek native n8n JSON yuzeyi + `agent/repair.py`. Dolayisiyla
  bu refactor "compiler factory'lerini registry'ye tasimak" degil; **native-JSON
  uzeyi uzerine** reusable semantic action-pack katmani tanimlamak anlamina gelir
  (yeniden kapsam tanimi gerekir).
- `Motivasyon`: Her workflow shape'ini prompt/repair ile tek tek ele almak yeni
  platformlar arttikca olceklenmez; desteklenen platformlarin reusable semantic
  action'larini (or. `slack.message.send`) tanimlayan bir katman bakimi
  kolaylastirir.
- `Kabul kriteri`: yeni bir platform eklendiginde semantic action'lar
  workflow-shape case'i yazmadan native JSON uretimine compose edilebilir.
- `Ilgili notlar`: [[adr-0010-json-surface-repair-normalizer]]
  (ADR-0005/0008/0009 superseded), [[chat-workflow-generation]],
  [[agent-service]], [[n8n-registry]]

### WorkflowSpec Compiler Genisletmeleri (SUPERSEDED)

- `Durum`: superseded; ADR-0010 ile cozuldu.
- `Alan`: agent, n8n-registry
- `Motivasyon`: LLM'in uzun n8n JSON uretme hatalarini azaltmak.
- `Not (2026-06-30)`: Bu maddenin onerdigi "compact spec + compiler" yaklasimi
  ([[adr-0005-workflow-spec-compiler]]) **terk edildi**. Ayni problem (uzun-JSON
  hatalari) artik tek native-JSON yuzeyi + deterministik `agent/repair.py`
  normalizer'i ile cozuluyor ([[adr-0010-json-surface-repair-normalizer]]).
  WorkflowSpec/Plan IR'lari ve compiler'lar silindi.
- `Ilgili notlar`: [[chat-workflow-generation]], [[n8n-registry]],
  [[adr-0010-json-surface-repair-normalizer]]

### Google Sheets Append/Upsert Reusable Workflow

- `Durum`: fikir
- `Alan`: agent, oauth
- `Motivasyon`: Kullanici runtime input verdiginde bu datayi Google Sheets'e
  kaydeden tekrar kullanilabilir workflow'lar olusturmak.
- `Kabul kriteri`: Agent kullanicidan sheet/dosya/kolon bilgilerini bir defada
  ister, Webhook runtime input alanlarini kaydeder ve Google Sheets append node'u
  native JSON + `repair.py` ile guvenilir uretilir.
- `Not`: Eski baslik "WorkflowSpec" idi; compiler yolu kaldirildigi icin (ADR-0010)
  hedef artik native-JSON uretiminin bu akista saglam calismasi.
- `Ilgili notlar`: [[agent-service]], [[chat-workflow-generation]],
  [[web-app]]

### Clarification Hafizasi ve Tekrar Soru Azaltma

- `Durum`: uygulaniyor
- `Alan`: agent, web
- `Motivasyon`: Agent eksik bilgi sordugunda kullanici hangi sorularin
  soruldugunu gormeli ve ayni soru tekrar tekrar sorulmamali.
- `Kabul kriteri`: Gecmis clarification'lar kompakt gorunur; runner onceki
  cevaplari modele task context'i olarak verir; agent cevaplanmis alanlari tekrar
  istemez.
- `Ilgili notlar`: [[chat-workflow-generation]], [[web-app]]

### Artifacts V2 / Artifact Gallery

- `Durum`: fikir
- `Alan`: agent, web, product
- `Motivasyon`: V1 [[artifacts]] modeli Google Sheets preview snapshot'ini chat
  ve dashboard run sonucunda gosterir. Daha sonra kullanicinin tum artifact
  gecmisini arayabilmesi, silebilmesi ve farkli platform artifact tiplerini
  gorebilmesi gerekebilir.
- `Kabul kriteri`: Ayri artifact storage/API, dashboard gallery, retention ve
  silme politikasi, Gmail/file/report artifact tipleri ve platform adapter
  modeli tanimlanir.
- `Ilgili notlar`: [[artifacts]], [[agent-service]], [[web-app]],
  [[dashboard]]

### NVIDIAnın ücretsiz apisini ekleyerek developmentda token masrafını azaltma.
- `Durum`: planlandı.
- `Alan`: agent, web
- `Motivasyon`: geliştirme aşamasında 
- `Kabul kriteri`: feature'in bitti sayilmasi icin gozlenebilir davranis.
- `Ilgili notlar`: Obsidian linkleri.

## Tamamlanan veya Tasindi

Tamamlanan maddeler ilgili feature/ADR notuna tasinmali veya burada durum
`tamamlandi` yapilip kisa sonuc linki eklenmelidir.
