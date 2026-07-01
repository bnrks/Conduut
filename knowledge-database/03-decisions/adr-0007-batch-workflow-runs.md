# ADR 0007: Batch Workflow Runs

Merkez: [[index]]

## Durum

Accepted for MVP.

## Baglam

[[adr-0004-parameterized-workflow-inputs]] ile dashboard ve agent ayni runtime
input contract uzerinden workflow'u tek sefer calistirabiliyordu. Kullanici
potansiyel musteri listesi, lead tablosu veya benzer satir bazli veri icin ayni
workflow'u defalarca elle calistirmak zorunda kalabilir.

## Karar

V1 batch run workflow JSON'unu degistirmez. Conduut dashboard, `.xlsx` veya
`.csv` dosyasini tarayicida parse eder, kullanicidan workflow input alanlari ile
kolon/sabit deger eslemesini alir ve agent'a yalniz mapped row input listesi
gonderir.

Agent `POST /api/workflows/{workflow_id}/batch-run` endpoint'inde:

- Credential/readiness ve Conduut-runnable webhook hazirligini batch basinda
  yapar.
- En fazla 50 satiri sequential calistirir.
- Her satiri mevcut `input_schema` ile validate eder.
- Eksik required input olan satiri webhook'a gondermeden `skipped` yapar.
- Bir satir hata verirse kalan satirlara devam eder.
- Artifact origin bilgisini `workflow_batch_run`, `batchRunId`, `rowNumber` ve
  `executionId` ile saklar.

2026-07-01 guncellemesi: Batch girisi artik iki kaynakli. Dosyaya (xlsx/csv)
ek olarak dashboard'da `Run batch` icinde `Manual entry` alt-sekmesi eklendi:
kullanici degerleri duzenlenebilir bir tabloda elle tek tek girer (her satir bir
calistirma). Ikinci kaynak ayni `{ rowNumber, input }` satir listesini (max 50)
uretir ve mevcut `batch-run/stream` akisini kullanir; **backend/endpoint contract
degismez, degisiklik tamamen frontend** (`apps/web/.../workflows/page.tsx`). Bos
satirlar elenir, required dogrulama satir bazlidir. Spec:
`docs/superpowers/specs/2026-07-01-manual-batch-run-input-design.md`.

2026-05-31 guncellemesi: Dashboard UX icin ayni davranisin streaming yuzeyi de
eklendi. `POST /api/workflows/{workflow_id}/batch-run/stream`, batch baslangici,
satir baslangici, satir sonucu ve tamamlanma event'lerini SSE olarak dondurur.
Mevcut JSON endpoint geriye donuk uyumluluk icin korunur; frontend batch run
baslatirken stream yuzeyini kullanarak `islenen / toplam`, sonuc sayaclari,
progress bar ve client tarafinda olusturulan kisa row onizlemesi gosterir.

## Sonuclar

Avantajlar:

- Mevcut n8n workflow'lari ve compiler ciktilari bozulmadan tekrar
  kullanilabilir.
- Batch davranisi dashboard'a eklenir; chat agent batch akisi sonraya
  birakilir.
- Dosya ham hali backend'e gitmez; backend yalniz runtime input payload'larini
  alir.

Sinirlar:

- V1 concurrency `1` ve row limiti `50`.
- Google Sheets kaynak secimi, saved mapping, paste/JSON import, retry/cancel
  ve async batch history sonraki iterasyon konularidir.
- Stream yuzeyi iptal/cancel semantigi tasimaz; gercek cancel icin ayri backend
  cancellation contract gerekir.

Ilgili notlar: [[dashboard]], [[agent-service]], [[chat-workflow-generation]].
