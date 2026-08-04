# ADR-0018: n8n Source-of-Truth Execution History

Merkez: [[index]]

## Durum

Kabul edildi ve uygulandi (2026-07-15).

## Karar

Runs V1'in source of truth'i shared n8n execution API'sidir. Firestore execution
index'i olusturulmaz. API ve agent tool'lari `src/executions.py` katmanindan
gecer; katman bugun shared client kullansa da `user_id` contract'ini zorunlu
tutar.

Shared n8n production multi-tenant guvenlik siniri olarak kabul edilmez.
Customer-owned n8n provider resolution production'a cikis oncesi zorunlu
release gate'tir ve ileride yalniz execution provider resolution degistirilerek
Runs/chat contract'i korunacaktir ([[adr-0022-customer-owned-n8n]]).

Web'e raw n8n execution payload'i verilmez. Detay contract'i yalniz status,
timing, workflow kimligi/adi, kisa summary, failed node ve redakte hata tasir.
Agent repair tool'u ise ayni service sinirinda, HTTP'ye acilmayan bounded
response/output preview'li internal inspection kullanir.
`Fix with Conduut` istemci metnine guvenmez; backend execution id'yi yeniden
cozerek canonical attachment uretir.

## Gerekce

n8n source-of-truth, Conduut disinda schedule/webhook ile olusan run'lari da
gosterir ve iki persistence sisteminin drift etmesini onler. Tek service siniri,
customer-owned n8n gecisinde route, UI ve agent tool sozlesmelerinin degismesini
onler. `user_id`, hedef instance provider'ini cozer; internal execution lineage
`instance_id` tasir.

## Sonuclar

- Liste n8n opaque cursor'ini tasir ve workflow adi icin sayfa basina ek workflow
  listesi okur.
- Gorunen tarih n8n retention penceresiyle sinirlidir.
- Retry/replay, delete, raw data ve billing usage V1 disidir.
- Shared ortam yalniz local/dev MVP icindir.

Ilgili: [[execution-history]], [[adr-0001-shared-n8n-mvp]],
[[system-architecture]], [[customer-owned-n8n]], [[agent-service]].
