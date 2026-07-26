# ADR-0021: Chat Bazli Execution Policy

Merkez: [[index]]

## Durum

Kabul edildi ve implemente edildi (2026-07-25). Workflow assurance zincirini
koruyarak kullaniciya chat basinda maliyet/hiz ile runtime dogrulama arasinda
acik bir secim verir. Temel assurance kararlari icin
[[adr-0019-workflow-assurance-v1]] ve
[[adr-0020-workflow-node-cards-assurance-v2]] gecerlidir.

## Baglam

Build sonrasi sandbox ile gercek run ayni workflow'u ve bazi durumlarda ayni
ucretli upstream servisi iki kez calistirabiliyordu. Bu daha guclu runtime
kaniti uretiyor, fakat sure ve maliyet ekliyordu. Her kullanici ve her is icin
tek zorunlu davranis yerine risk seciminin acik ve kalici olmasi istendi.

## Karar

Conversation iki policy'den birini tasir:

- `safe`: Gercek run input'u ile bir adet yan-etkisiz sandbox preview alinir.
  Preview kullaniciya gosterilir; structured onaydan sonra token tuketilir ve
  gercek workflow bir kez calistirilir.
- `fast`: n8n runtime sandbox calistirilmaz. Typed Oracle ve static semantic
  analizden full coverage'li bir contract preview uretilir; kullanici onayindan
  sonra gercek workflow bir kez calistirilir.

Policy yeni chat composer'inda secilir, varsayilan `safe` olur ve ilk mesajla
birlikte conversation'a yazilip kilitlenir. Sonraki mesajlar policy'yi
degistiremez. Eski conversation'lar fail-safe olarak `safe + locked` kabul
edilir. Backend persisted conversation'i otorite sayar; kilitli policy ile
celisen istek `409 execution_policy_locked` doner.

Build-time `create_workflow` ve `update_workflow` artik runtime sandbox
calistirmaz. Native JSON repair, schema validation, readiness, dynamic
credential/header contract ve static semantic guard her iki policy'de de
zorunludur.

Safe preview basarisizsa model workflow'u duzelterek ayni gercek input ile yeni
bir preview isteyebilir. Bu repair butcesi en fazla iki runtime denemesidir;
butce biterse `needs_attention` ile terminal olur. Tek bir deneme icinde ayni
sandbox otomatik tekrarlanmaz. Fast static preview hatasi runtime repair loop'u
baslatmaz ve fail-closed olur.

Preview token'i mevcut workflow fingerprint ve input hash'ine ek olarak
`conversation_id`, `execution_policy` ve `preview_basis` (`safe_sandbox`
veya `fast_static`) alanlarina baglidir. Baska chat/policy/preview turunden
token replay edilemez.

Dashboard manual run, batch run ve activation ilk surumde `safe` kalir. Fast
policy yalniz chat'ten on-demand manual execute yoluna aciktir. Scheduled
workflow, batch ve dashboard davranisi bu kararla gevsetilmez.

## Degismeyen Guvenlik Katmanlari

Her iki policy'de de su katmanlar calisir:

- native JSON repair ve deterministic validation;
- readiness ve credential kontrolleri;
- typed Oracle/static semantic assurance;
- structured preview onayi ve tek kullanimlik token;
- gercek execution assessment, immutable evidence ve claim gate;
- partial side effect sonrasi otomatik real-run tekrarinin engellenmesi.

Fast secimi "kontrolsuz calistir" anlamina gelmez; yalnizca gercek input ile
n8n sandbox preview adimini kaldirir.

## Sonuclar ve Sinirlar

- Safe modda action node'lari neutralize edilse de action oncesindeki ucretli
  read/enrichment servisi sandbox ve real run'da iki kez calisabilir.
- Fast daha kisa ve ucuzdur, fakat runtime dataflow, gercek credential ve
  upstream servis uyumunu real run oncesinde kanitlamaz.
- Fast yalniz full static contract coverage varsa preview uretebilir;
  desteklenmeyen veya partial contract fail-closed olur.
- Safe repair gerektiren hatalarda toplam runtime preview sayisi ikiye kadar
  cikabilir; bunlar ayni denemenin gereksiz tekrarlari degil, modelin workflow
  degisikligi sonrasi yeni kanit denemeleridir.

## Ilgili Kod ve Testler

- `apps/agent/src/agent/runtime_policy.py`
- `apps/agent/src/agent/workflow_preview.py`
- `apps/agent/src/agent/tools/factory.py`
- `apps/agent/src/store/conversations.py`
- `apps/agent/src/store/workflow_previews.py`
- `apps/agent/src/routes/chat.py`
- `apps/web/src/components/chat/chat-input.tsx`
- `apps/web/src/app/(chat)/chat/page.tsx`
- `apps/web/src/app/(chat)/chat/[conversationId]/page.tsx`
- `apps/agent/tests/test_sandbox_gate.py`
- `apps/agent/tests/test_workflow_preview.py`
- `apps/agent/tests/test_chat_route.py`

Akis ozeti icin [[chat-workflow-generation]], servis sinirlari icin
[[agent-service]].
