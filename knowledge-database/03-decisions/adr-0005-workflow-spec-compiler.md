# ADR-0005: WorkflowSpec IR ve Deterministic Compiler

Merkez: [[index]]

## Durum

Kabul edildi — **SUPERSEDED by [[adr-0010-json-surface-repair-normalizer]]**
(2026-06-14). WorkflowSpec IR + compiler model yuzeyinden kaldirildi; tek
kompakt-JSON yuzeyi + `repair.py` aktif yol oldu. Compiler kodu Faz 3'te
(2026-06-30) silindi. Bu ADR tarihsel kayit olarak korunur.

## Baglam

n8n workflow JSON'lari karmasiklastikca LLM'ler node type, typeVersion,
conditional parameter, expression ve `connections` shape kararlarinda hata
yapiyor. Fine-tune uzun vadede iyi bir secenek olabilir, fakat MVP maliyeti
yuksek. Mevcut [[n8n-registry]] lookup-first yaklasimi faydali olsa da model
hala uzun raw n8n JSON'u kendisi uretmek zorunda kaliyor.

## Karar

Conduut, desteklenen dar workflow aileleri icin raw n8n JSON yerine
`WorkflowSpec` adli compact IR kullanan deterministic compiler yaklasimini
benimser. Ilk pilot Gmail on-demand workflow'udur:

- `trigger.kind=on_demand`.
- Tek step: `capability=send_email`, `service=gmail`.
- Runtime input: `to`, `subject`, `message`.
- Compiler Webhook trigger, Gmail send node'u, nested connection ve input
  schema payload'unu uretir.
- Webhook output'u POST body'yi `$json.body` altinda verdigi icin Gmail send
  expression'lari `={{$json.body.to}}`, `={{$json.body.subject}}` ve
  `={{$json.body.message}}` formundadir.
- Webhook/Gmail `typeVersion` registry'den okunur; schema yoksa n8n'e side
  effect yapilmaz.

Ikinci desteklenen aile Google Sheets satir filtreleme ve Gmail gonderimidir:

- Trigger `on_demand` veya gunluk `schedule` olabilir.
- Step sirasi sabittir: `read_sheet_rows`/`google_sheets` ->
  `filter_items`/`core` -> `send_email`/`gmail`.
- Google Sheets node'u spreadsheet/sheet locator bilgisiyle read operation
  kullanir; Filter node'u tek kosullu V2 condition yapisi uretir; Gmail node'u
  satir alanlarina veya sabit subject/message degerlerine baglanir.
- Gmail subject/message sabit metin icinde `{{...}}` expression parcasi
  tasiyorsa compiler string'i n8n expression modu icin `=` ile baslatir.
- Bu akista email verisi sheet satirindan geldigi icin compiler explicit bos
  `input_schema` dondurur; generic Gmail runtime input inference uygulanmaz.
- Webhook veya Schedule, Google Sheets, Filter ve Gmail `typeVersion`
  degerleri registry'den okunur; eksik schema veya desteklenmeyen operator
  n8n'e side effect yapmadan hata dondurur.

2026-05-17 guncellemesi: `WorkflowSpec` workflow-shape bazli pilot olarak
korunur, fakat yeni tercih edilen yol `WorkflowPlan` action graph IR'idir.
Agent artik desteklenen akislarda raw n8n node JSON'u veya hardcoded workflow
shape'i yerine semantic action listesi gonderir:

- `trigger`: `on_demand` veya gunluk `schedule`.
- `inputs`: runtime input schema; gerekirse compiler `input.*` ref'lerinden
  `to`, `subject`, `message` gibi alanlari infer eder.
- `actions`: `gmail.send`, `sheets.row.append`, `sheets.read_rows`,
  `core.filter` gibi semantic action primitive'leri.
- `params`: n8n parameter isimleri degil, `to`, `subject`, `message`,
  `spreadsheet_id`, `sheet_name`, `columns`, `field`, `operator`, `value` gibi
  is seviyesindeki isimler.
- `after`: action'lar arasi baglanti; yoksa compiler lineer sirayi kullanir.

Compiler action factory'leri Gmail, Google Sheets, Filter ve trigger node'larini
uretir; `typeVersion`, n8n expression, `connections`, Sheets resourceMapper
shape'i ve runtime metadata backend'de belirlenir. Ilk yeni hedef Gmail send
sonrasi Google Sheets append log akisini desteklemektir. Ilk kararda Sheet
otomatik provisioning kapsam disiydi; [[adr-0006-platform-capability-layer]]
sonrasi plan action'i `spreadsheet_title` veya benzeri baslik bilgisi tasiyorsa
provisioning compiler oncesi platform layer tarafindan yapilir.

2026-05-17 ek not: `sheets.row.append` semantic action'i her zaman tek n8n
node'una birebir karsilik gelmez. n8n Google Sheets append implementasyonu sheet
tamamen bossa `columns.mappingMode=defineBelow` verilmis olsa bile
`autoMapInputData` moduna duser. Bu durumda action Gmail send'den sonra
bagliysa Gmail output alanlari (`id`, `threadId`, `labelIds`) sheet'e yazilir.
Bu nedenle compiler `sheets.row.append` icin Google Sheets Append oncesine
`Prepare Sheets Row` Set node'u ekler, current item'i semantic `columns`
map'ine donusturur ve Sheets Append node'unu bu Set cikisini
`autoMapInputData` ile yazacak sekilde kurar. Bu karar action-graph IR'in
"semantic action bir veya daha fazla n8n node'una genisleyebilir" ilkesini
netlestirir.

2026-05-17 yon karari: Mevcut `WorkflowPlan` yaklasimi simdilik yeterli ve
bugfix icin ayrica buyuk compiler refactor'i gerekmiyor. Bir sonraki buyuk adim
Action Registry / platform action pack yapisidir, fakat bu refactor ilk yeni
platform veya action ailesi eklenirken yapilmalidir. Ornek: Slack OAuth eklemek
tek basina compiler'in Slack akisini anlamasini saglamaz; compiler'a
`slack.message.send` gibi semantic action ve onun n8n node/subgraph mapping'i
eklenmelidir. Hedef, her workflow shape'ini hardcode etmek degil; desteklenen
platform action'larini reusable parcalar olarak tanimlayip workflow'lari bu
parcalardan compose etmektir.

## Sonuclar

- LLM kullanici niyeti ve compact spec kararina odaklanir.
- n8n JSON, expression ve connection shape gibi hata yapmaya acik kisimlar
  backend tarafinda uretilir.
- Mevcut raw `create_workflow`/`update_workflow` yolu fallback olarak korunur.
- `create_workflow_from_plan` desteklenen action graph'lar icin birincil
  tool'dur; `create_workflow_from_spec` geriye donuk uyumluluk icin kalir.
- Yeni capability'ler ileride compiler'a kademeli eklenebilir.
- Sheets/Gmail gibi coklu servisli workflow'larda credential readiness mevcut
  akisi kullanir; managed Google Gmail ve Sheets connection'lari canonical
  platform capability registry uzerinden n8n node'larina otomatik attach
  edilebilir.

Ilgili notlar: [[agent-service]], [[chat-workflow-generation]], [[n8n-registry]].
