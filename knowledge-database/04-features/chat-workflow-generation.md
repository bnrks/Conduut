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
- `tool_call`: tool calistigini UI'a bildirmek icin gelir; mevcut UI bunu
  dogrudan gostermiyor.
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
