# ADR 0004: Parameterized Workflow Inputs

Merkez: [[index]]

## Durum

Accepted for MVP.

## Baglam

Gmail send gibi workflow'lar ilk uretildiginde alici, konu ve mesaj gibi is
degerleri node parametrelerine hard-code edilebiliyordu. Bu, workflow'u tek bir
kisiye veya tek bir mesaja bagli hale getiriyor ve tekrar calistirma
deneyimini zayiflatiyordu.

## Karar

Workflow'lar calisma aninda Conduut runtime input alabilecek:

- Dashboard ve agent ayni `POST /api/workflows/{workflow_id}/run` contract'ini
  kullanir.
- Runtime input metadata'si MVP'de Firestore
  `users/{uid}/workflow_metadata/{workflowId}` altinda saklanir.
- Gmail send workflow'lari icin `to`, `subject`, `message` input field'lari
  uretilebilir ve Gmail node'u webhook payload expression'larina baglanir.
- Kullaniciya raw n8n webhook URL'i public contract olarak verilmez; Conduut
  run endpoint auth, validation ve webhook proxy katmani olur.

## Sonuclar

Avantajlar:

- Workflow'lar tekrar kullanilabilir hale gelir.
- Dashboard'dan calistirma LLM token'i harcamaz.
- Agent'tan calistirma ayni backend run yolunu kullanir ve workflow'u yeniden
  uretmez.

Riskler:

- [[adr-0001-shared-n8n-mvp]] nedeniyle workflow ownership hala production
  seviyesinde degildir.
- Input schema su an MVP icin `string`, `email`, `textarea` ile sinirlidir.

Ilgili notlar: [[chat-workflow-generation]], [[dashboard]], [[agent-service]].
