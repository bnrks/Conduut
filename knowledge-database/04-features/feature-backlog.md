# Feature Backlog

Merkez: [[index]]

Bu not, Conduut'a ileride eklenecek urun/teknik ozellikleri takip etmek icin
kullanilir. Bug ve regresyonlar [[issue-backlog]] icinde, mimari kararlar ise
[[adr-0005-workflow-spec-compiler]] gibi ADR notlarinda tutulur.

## Kullanim

Her feature maddesi su bilgileri tasimaya calismali:

- `Durum`: fikir, planlandi, uygulanacak, uygulaniyor, tamamlandi, ertelendi.
- `Alan`: agent, web, n8n-registry, oauth, infra, product.
- `Motivasyon`: kullanici problemi veya teknik gerekce.
- `Kabul kriteri`: feature'in bitti sayilmasi icin gozlenebilir davranis.
- `Ilgili notlar`: Obsidian linkleri.

## Aday Ozellikler

### Workflow Action Registry / Platform Action Pack Refactor

- `Durum`: ertelendi; ilk yeni platform/action eklenirken uygulanacak.
- `Alan`: agent, n8n-registry
- `Motivasyon`: Mevcut `WorkflowPlan` action graph dogru yonde calisiyor; fakat
  action factory'ler `spec_compiler.py` icinde buyumeye baslarsa bakimi
  zorlasir. Her workflow shape'ini tek tek tanimlamak yerine desteklenen
  platformlarin reusable semantic action'larini tanimlayan bir Action Registry
  gerekir.
- `Kabul kriteri`: `gmail.send`, `sheets.row.append`, `core.filter` gibi
  action'lar registry/action pack yapisina tasinir; yeni bir platform
  eklendiginde ornegin `slack.message.send` action'i workflow-shape case'i
  yazmadan diger action'larla compose edilebilir. Action factory'ler tek node
  veya `Prepare Sheets Row -> Google Sheets Append` gibi subgraph uretebilir.
- `Not`: Bu refactor mevcut Gmail/Sheets bugfix'i icin acil degil. Slack,
  Calendar veya benzeri ilk yeni platform/action eklenirken yapilmasi en
  dogru zaman.
- `Ilgili notlar`: [[adr-0005-workflow-spec-compiler]],
  [[chat-workflow-generation]], [[agent-service]], [[n8n-registry]]

### WorkflowSpec Compiler Genisletmeleri

- `Durum`: fikir
- `Alan`: agent, n8n-registry
- `Motivasyon`: LLM'in uzun n8n JSON uretme hatalarini azaltmak.
- `Kabul kriteri`: yeni workflow ailesi compact spec ile olusur, compiler side
  effect yapmadan hata dondurur ve raw `create_workflow` fallback'i korunur.
- `Ilgili notlar`: [[chat-workflow-generation]], [[n8n-registry]],
  [[adr-0005-workflow-spec-compiler]]

### Google Sheets Append/Upsert WorkflowSpec

- `Durum`: fikir
- `Alan`: agent, oauth
- `Motivasyon`: Kullanici runtime input verdiginde bu datayi Google Sheets'e
  kaydeden tekrar kullanilabilir workflow'lar olusturmak.
- `Kabul kriteri`: Agent kullanicidan sheet/dosya/kolon bilgilerini bir defada
  ister, Webhook runtime input alanlarini kaydeder ve Google Sheets append node'u
  deterministic compile edilir.
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
