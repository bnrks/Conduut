# Chat Workflow Generation

Merkez: [[index]]

Chat, Conduut MVP'nin ana urun akisi.

## Kullanici Akisi

1. Kullanici Firebase ile giris yapar.
2. Settings altinda LLM provider API key'i ekler.
3. `/chat` ekraninda provider ve model secer.
4. Mesaj gonderir.
5. Web app `POST /api/chat/send` route'una Firebase token ile istek atar.
6. Next route FastAPI agent'a proxy eder.
7. Agent Pydantic AI ile tool calling dongusu calistirir.
8. Agent n8n REST API uzerinden workflow olusturur/gunceller.
9. Frontend SSE token'lari ve attachment event'lerini render eder.

## Yeni Conversation

`/chat` sayfasi provider/model secimini acik tutar. Ilk mesajdan sonra agent
conversation id dondurur. Web app `conversation-cache` ile yeni mesajlari
gecici tutar ve `/chat/[conversationId]` sayfasina gecer.

## Devam Conversation

`/chat/[conversationId]` sayfasi conversation detayini yukler. Provider ve model
conversation metadata'sindan kilitlenir. Kullanici ayni conversation icinde
model degistirmez.

## SSE Event'leri

- `token`: assistant cevabinin text parcasini ekler.
- `tool_call`: tool calistigini UI'a bildirir. Web UI bunu teknik tool adini
  gostermeden "Checking available n8n steps", "Creating the workflow",
  "Running the workflow" gibi yuksek seviye durum metinlerine cevirir.
- `attachment`: `workflow_preview` gibi ekleri mesaja ekler.
- `done`: conversation, provider ve model bilgisini tamamlar.
- `error`: toast ile hata gosterir.

## Workflow Preview

`create_workflow` ve `update_workflow` basarili olursa agent attachment olarak
`workflow_preview` dondurur. Frontend `WorkflowPreview` component'i bunu
assistant mesajinin altinda gosterir.

Workflow n8n'e yazilmadan once Pydantic model validation ve
[[n8n-registry]] destekli yapisal kontrollerden gecer. Hata varsa agent
Pydantic AI `ModelRetry` ile workflow JSON'unu duzeltmeye zorlanir ve n8n'e
side effect yapilmaz. n8n registry `Edit Fields (Set)` gibi node'larda
decimal `typeVersion` (`3.4` vb.) dondurebildigi icin workflow validator
numeric `int | float` kabul eder. Registry'nin cozebildigi kisa node type'lari
canonical type ve registry typeVersion'a normalize edilir; bu, modelin `set`
gibi kisa ad uretmesi halinde gereksiz retry dongusunu azaltir. Agent ayrica
connection referanslarini node `name` formatina normalize eder; model `1`/`2`
veya `node1`/`node2` gibi id/sira alias'lari uretirse bunlar n8n'e yazilmadan
once ilgili node adlarina cevrilir.

## Credential ve Run Capability

Agent workflow olusturduktan veya guncelledikten sonra readiness analizi yapar:

- Credential isteyen node'larda eksik credential varsa chat'e
  `credential_request` attachment gelir.
- Webhook gibi credential'i opsiyonel olan node'larda registry schema'da
  credential type listelenmesi tek basina yeterli sayilmaz. Agent actual node
  `parameters.authentication` ve schema default degerini kontrol eder; default
  `none` ise credential istemez.
- Kullanici credential'i Conduut chat formundan girer; Next BFF
  `/api/credentials` uzerinden agent'a proxy eder.
- Agent credential'i n8n'e kaydeder, workflow node'una attach eder ve
  Firestore'a credential metadata yazar.
- `execute_workflow` ilk fazda sadece webhook-triggered workflow'lari
  Conduut'tan calistirir ve n8n execution detayini agent icinde kanit olarak
  kontrol eder. Chat'e artik ayri `workflow_run_result` attachment/kart
  gonderilmez; agent dogrulamayi kendi yapar ve kullaniciya yalnizca sade
  metin cevabi verir.
- n8n production webhook registration icin Webhook node'larinda `webhookId`
  bulunmali. Agent validator/normalizer eksikse otomatik UUID uretir.
- Webhook node'u `Respond to Webhook` node'una bagliyse `responseMode`
  otomatik `responseNode` yapilir; aksi halde n8n `Unused Respond to Webhook
  node found in the workflow` hatasi verir.
- Conversation history modele verilirken assistant attachment'larindan gizli
  workflow context uretilir. Boylece kullanici "run the workflow" gibi takip
  mesaji yazdiginda model onceki `workflow_preview.id` degerini kullanabilir ve
  `workflow_id=1` gibi uydurma id'lere dusmez.
- Acuity/Gmail/Slack gibi external event trigger'lari icin credential ve
  readiness saglanir; gercek external event gelmeden agent calistirdim demez.

Set/Edit Fields node icin ek davranis: agent prompt'u ve registry schema
ornekleri `parameters.assignments.assignments` formatini gosterir. Validator
bos Set node'u kabul etmez; boylece UI'da gorunen ama output'u bos olan
workflowlar n8n'e yazilmadan once ModelRetry'a duser.

## Agent Davranis Kurallari

Agent prompt'u onay sormadan aksiyon almayi ister. Yeni workflow icin
`create_workflow`, mevcut workflow icin `get_workflow` sonra `update_workflow`
kullanmalidir. Bilinmeyen node type'lar asla tahmin edilmemeli; once
[[n8n-registry]] tool'lari kullanilmalidir.

LiteLLM agent loop'u kaldirildi; provider cagrilari Pydantic AI native
provider'lariyla yapilir. Mevcut SSE event sozlesmesi korunur:
`token`, `tool_call`, `attachment`, `done`, `error`.

Ilgili notlar: [[web-app]], [[agent-service]], [[dashboard]].
