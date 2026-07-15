# Execution History (Runs)

Merkez: [[index]]

`/dashboard/runs`, shared n8n'deki gercek workflow execution gecmisini gosteren
Runs V1 ekranidir. Kaynak n8n'dir; Firestore'da ikinci bir execution kopyasi
tutulmaz. Bu nedenle Conduut dashboard'dan baslatilan run'lara ek olarak schedule,
webhook ve diger external trigger run'lari da n8n retention penceresi icinde
gorunur.

## Contract

- `GET /api/executions`: `workflow_id`, `status`, opaque `cursor` ve `limit`
  filtreleriyle liste; `next_cursor` n8n'den aynen tasinir.
- `GET /api/executions/{execution_id}`: status, zamanlama, workflow, kisa ozet,
  `failed_node` ve Authorization/Basic/Bearer/API-key/Cookie/query secret
  bicimlerini kapsayan redakte/kirpilmis hata. `failed`/`crashed` public
  contract'ta canonical `error` status'una cevrilir.
- Raw execution data, output item'lari, binary ve credential payload'lari web
  contract'ina girmez.
- Agent `inspect_execution`, ayni service sinirindaki agent-only bounded
  response/output preview'ini kullanir; bu zengin DTO HTTP route'larina baglanmaz.
- `src/executions.py`, route ve agent tool'larinin ortak siniridir. Public
  fonksiyonlar `user_id` ister; MVP'de shared client'a gider, production oncesi
  per-user n8n resolver burada devreye alinacaktir.

## Dashboard

Runs sayfasi newest-first liste, status/workflow filtresi, cursor pagination,
loading/empty/error durumlari ve detay paneli saglar. Hata detayinda `Fix with
Conduut` aksiyonu vardir. Usage sayfasindaki sahte recent-execution listesi
kaldirildi; Usage yalniz mock plan/usage sayaclarini tasimaya devam eder.

Workflow `Run once` HTTP 200 donse bile payload `success=false` veya
`status=error|failed|crashed` ise artik success toast gostermez. Hata ve failed
step sonuc panelinde gosterilir.

## Fix with Conduut

Web yalniz `execution_id + intent=diagnose_and_fix` structured reference'ini
tek kullanimlik sessionStorage handoff'u ile yeni chat'e tasir. Chat backend'i
execution'i `src/executions.py` uzerinden yeniden okuyup canonical workflow/status
bilgisini user-message `execution_reference` attachment'ina yazar; istemciden
workflow veya hata metni kabul etmez.
User mesajinda bu attachment mesaj balonunun ustunde kompakt bir hata-ikonu
karti olarak render edilir; workflow adi ve `Run #<execution_id>` hem optimistic
ilk mesajda hem reload sonrasinda canonical backend attachment'indan gorunur.

History reconstruction user attachment context'ini son prompt ve onceki user
mesajlarinda korur. Agent once exact `inspect_execution`, sonra ayni workflow'u
okur. Yalniz workflow tanimi kaynakli hatada ayni workflow'u update eder;
credential, quota, external-service veya user-data hatasinda workflow'u degistirmez.

## Retention ve Sinirlar

Docker Compose success/error execution data kaydini, pruning'i, varsayilan 30 gun
(`720` saat) retention'i ve `10000` execution count cap'ini acikca tanimlar.
Runs V1 retry/replay, execution delete, raw JSON download, billing usage ve direct
platform action history'sini kapsamaz.

Karar: [[adr-0018-execution-history-mvp]]. Ilgili: [[dashboard]],
[[agent-service]], [[system-architecture]], [[adr-0001-shared-n8n-mvp]].
