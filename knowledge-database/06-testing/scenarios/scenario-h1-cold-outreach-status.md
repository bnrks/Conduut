# Senaryo H1 — Sheet oku → süz → mail → satırı "Sent" yaz

Merkez: [[scenario-bank]]

- **Zorluk:** hard
- **Kaynak (n8n.io):** https://n8n.io/workflows/4214-cold-email-outreach-with-gmail-and-google-sheets-status-tracking
- **Capability'ler / node'lar:** Google Sheets (`sheets.range.read` + `sheets.range.update`),
  Filter/IF, Gmail (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-h2-lead-outreach]] — **birincil kardeş**
  (aynı read→filter→send→update-status deseni, farklı yüzey). Genellik guard'ının
  canlı örneği: H1'de bulunan bir Sheets-update/column-map düzeltmesi H2'yi de geçirmeli.
- **Risk noktaları:** **Sheets v4 update kolon eşlemesi** (`dataMode`/`values` →
  v4 `columns` + `matchingColumns`) — [[known-issues]] madde 1'in "reddet"/
  ModelRetry alanı; yanlış eşleşme **yanlış satıra yazar** = veri bozulması.
  Ayrıca per-row döngü, mail sonrası write-back ile tekrar-gönderim engelleme.

## Task (agent'a verilen doğal-dil)

> Sheet'imdeki henüz mail atılmamış potansiyel müşterilere sırayla tanıtım maili
> gönder ve her gönderdikten sonra o satırı "Gönderildi" olarak işaretle ki
> tekrar mail gitmesin.

## Referans yapı (yalnız bizde; agent görmez)

- **Google Sheets read** (`resource: sheet`, `operation: read`).
- **Filter/IF**: `Status != "Sent"` (veya boş).
- **Gmail send**: `sendTo = {{$json.Email}}`, kişiselleştirilmiş gövde.
- **Google Sheets update**: `operation: update` / `appendOrUpdate`,
  `columns` + `matchingColumns` (ör. `Email` veya `row_number` ile eşleşme),
  `Status = "Sent"`.
- Bağlantı: (Trigger) → Sheets read → Filter → Gmail → Sheets update.

## Beklenen sonuç (fonksiyonel)

Yalnız gönderilmemiş satırlara mail gider ve o satırlar "Gönderildi" olur;
ikinci çalıştırmada aynı kişilere tekrar mail gitmez. **Kritik:** update doğru
satırı güncellemeli (matchingColumns doğru olmalı).

## Sonuç geçmişi

**Guncel durum (2026-07-23): GECTI.** Workflow `8gUbKCVF28CzKNO2` ilk real
execution `#421` icinde yalniz `Hayir` durumundaki `musteri_no=1002/1004`
satirlarini gecirdi; iki farkli AI cikti, iki Gmail `SENT` receipt, iki esit
identity write-back ve bounded remote Sheet read-back ile `Evet` kanitlandi.
Hemen sonraki preview `0/0/0`, real execution `#423` ise Sheet'teki dort
satirin tamamini `Evet` okuyup Filter true branch'te `0` item uretti; AI,
Gmail ve Sheets Update hic calismadi. Boylece tekrar-gonderim engeli canlida
dogrulandi. n8n'in sifir-item `lastNode` webhook cevabini HTTP 500 +
`No item to return was found` vermesi execution assessment'ta exact
`success + no mutation` kosulunda `no_action` olarak normalize edildi.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-23 | Gecti | Workflow `8gUbKCVF28CzKNO2`: ilk real execution `#421` `2 eligible / 2 Gmail SENT / 2 Sheet write-back` ve remote read-back verdi; kimlikler `1002/1004`, AI ciktilari item-bazli ve farkliydi. Ikinci preview `0/0/0`; real execution `#423` Filter true branch `0`, false branch `4 Evet`, AI/Gmail/Sheets Update runData yok. Idempotency canli kanitlandi. Ikinci run'da n8n `lastNode` sifir-item sentinel'i HTTP 500 donduruyordu; execution `success`, runData mevcut ve mutation yoksa bu exact cevap `no_action` sayilacak sekilde execution assessment duzeltildi. Mutation calismis 500'ler partial/failed kalir. Hedefli workflow runner/route/claim/sandbox regresyonlari `87 passed`; `#423` snapshot'i yeni kodla `no_action`, `eligible=0`, `action=0`, `writeback=0`, `transportOk=true` verdi. |
| 2026-07-23 | Kaldi (yeni canli kosu bekliyor) | Card runtime wiring duzeltildi: local agent generated corpus'u yanlis `apps/agent/data` yolunda ariyordu ve `workflow_card_count=0` ile legacy fallback'e dusuyordu. Data-dir resolver localde `packages/n8n-registry/data`, Docker'da `/app/data` seciyor. Community detail'in dis node katalog ozeti yerine native `workflow.workflow` JSON'u extract ediliyor; H1'in parametreleri bosaltildigi icin exact operation uydurulmadan node type/name uzerinden action/write-back, `send_email/read_sheet/update_sheet_rows/scheduled_run` ve high-risk inference'i uretiliyor. Seed + raw merge sonrasinda n8n `1.121.3` icin 497 gecerli Workflow Card, 7.727 Node Card ve uyumlu manifest/index hazir. H1 Community template `4214` sorguda top-1. Bu kanit retrieval readiness'tir; gercek ilk/ikinci H1 execution oracle'i olmadigi icin senaryo halen gecmis sayilmaz. |
| 2026-07-23 | Kaldi (ikinci real run bekliyor) | `Potansiyel Müşterilere Tanıtım Maili` execution `#416` ilk-run fonksiyonel kaniti gercekte basariliydi: 2 Gmail `SENT` receipt, ayni iki `musteri_no` (`1002`, `1004`) write-back ve remote Sheet read'de iki `Evet`. UI'nin `Needs attention` sonucu yanlis negatifti: bounded read-after-write resolver `={{ $('IF').item.json.musteri_no }}` ifadesini resolved output yerine literal kimlik sanarak remote eslesmeyi fail ediyordu. Resolver artik dinamik expression hedefini write-node execution output'undan aliyor, configured literal postcondition'i koruyor. Ayni run'daki `Haklisiniz` metni kullanici mesaji degil, evidence output validator `ModelRetry` geri bildiriminin model tarafindan konusma gibi yorumlanmasiydi; claim ihlali artik retry yerine stream/final ortak deterministic summary ile kapanir. Hedefli claim/read-after-write testleri gecti. H1 tam kabul icin acik onayli ikinci real run `0/0/0` halen bekleniyor. |
| 2026-07-23 | Kaldi (canli kabul bekliyor) | [[adr-0020-workflow-node-cards-assurance-v2]] implemente edildi. Registry operation selector bug'i duzeltildi; Gmail `message.send` ve Sheets exact operation contract'lari artik dogru. Workflow Card top-10/max-3 retrieval, live Sheet header fail-closed build, typed Oracle/ProbeEvidence, projected status-loop `0/0/0`, immutable execution evidence, contextless-verified engeli, item-bazli Gmail receipt, bounded Sheets read-after-write, partial-side-effect auto-retry bloku ve streamed claim gate eklendi. Registry ve agent otomatik testleri gecti. Bu degisiklik gercek mail/Sheet mutation'i yapmadi; H1 ancak acik onayli ilk run `2/2/2` + read-back ve ikinci real run `0/0/0` kanitiyla gecer. |
| 2026-07-21 | Kaldi | Yeni agent run'i workflow `vDwEqG2MHbMYOsmT` olusturdu fakat real Gmail/Sheets side effect calistirilmadi. Sandbox clone execution `#396/#397/#398` failed; son bulgu `Filtrele: Could not get parameter - Parameter: jsCode`. Agent bozuk IF sekli reddedilince Code'a gecti ve `language="javascript"` yazdi; n8n exact `javaScript` beklerken registry'nin agent-facing Code semasi `displayOptions` nedeniyle `jsCode` alanini gostermiyordu. Genel duzeltme: tek-yollu elemede Filter tercihi, IF/Filter canonical condition example + ortak fail-closed validator, Code semasina `javaScript + jsCode` contract'i ve lowercase enum/missing-code validation'i. Hedefli registry/validation testleri gecti; canli H1 + H2 yeniden kosusu bekliyor. |
| 2026-07-21 | Kaldi | Canli workflow `RfDitjuT1Kg8dj8c`, execution `#395` transport olarak success ve 4 Gmail `SENT` + 4 Sheet write-back uretti. Ancak read durumlari `Evet, Hayir, Evet, Hayir` iken IF true branch dort item'in tamamini gecirdi; canonical olmayan `operator="equals"` string'i n8n tarafindan sessizce yanlis yorumlandi. AI Agent dort farkli metin uretirken Gmail `$('AI Agent').first().json.output` kullandigi icin kisisellestirme de ilk item'a sabitlendi. Kok neden prompt + IF validation + item-lineage assurance + sandbox predicate audit bosluguydu. Genel duzeltme: IF v2 object operator fail-closed validation, side-effect'in direct predecessor `.first()` referansini blocking assurance ve basit equals branch-conformance sandbox guard. Canli H1 ve kardes H2 tekrar kosusu bekliyor. |
| 2026-07-07 | Kaldı | Sheet inceleme (`run_platform_action` → `GET .../values/A1:Z10`) başarılıydı; agent `search_n8n_nodes` + iki `get_node_schema` çağrısından sonra `agent_unexpected_model_behavior`: "Model token limit ... exceeded before any response was generated" verdi. Kök neden workflow JSON veya DeepSeek değil, lokal config drift: root `.env` `CONDUUT_MODEL_PROFILE=default` kaldığı için runtime `profile=default`, `provider=anthropic`, `model=claude-sonnet-4-6` seçti. Düzeltme: `.env` `CONDUUT_MODEL_PROFILE=deepseek`; yanlış ara teshisle eklenen Anthropic token-budget kodu geri alındı. Test: `test_thinking_builder.py` + `test_runner.py` hedefli suite ve ruff temiz. Kardeş-doğrulama bekliyor; H1 aynı task ile yeniden koşulacak. |
| 2026-07-08 | Kaldı | Gece son deneme (`conversation=890363de`, workflow `qTrjFjmakuZKGPI4`) artık doğru Conduut profiliyle çalıştı: `profile=deepseek`, `provider=deepseek`, `model=deepseek-v4-pro`. Sandbox yine `AI Agent` node'unda düştü; hata workflow içindeki n8n `Anthropic Chat Model` node'unun eski Claude ID'leri kullanmasıydı (`claude-3-haiku-20240307`, sonra `claude-3-5-sonnet-20241022`). Kök neden: ham n8n `nodes.json` latest v1.3 `model` `resourceLocator` parametresini içeriyordu, fakat `n8n-registry` loader'i `displayOptions` bulunan parametreleri attığı için `get_node_schema` agent'a model default'u ve `searchModels` metadata'sını göstermiyordu. Düzeltme: registry schema extraction latest/default version koşullarını değerlendiriyor, `resourceLocator` parametrelerini ve dinamik seçim metadata'sını `keyParameters`/`exampleNode` içine taşıyor; Anthropic'e özel hardcoded normalizer/prompt kuralı kaldırıldı. Canlı `qTrjFjmakuZKGPI4` workflow'undaki daha önce yapılmış manuel model patch'i repo diff'i değil; gerçek Gmail/Sheets side-effect çalıştırılmadı. H1 sandbox/gerçek run yeniden koşulmalı; kardeş H2 doğrulaması bekliyor. |
| 2026-07-09 | Kaldı | Gece koşusu (`Toplu Tanıtım Maili - Sheet'ten`, workflow `Mm10bScLRc9sBO4M`) artık Anthropic schema/model sorununu aşmış: `lmChatAnthropic` v1.3 `model={__rl:true, mode:list, value:claude-sonnet-4-5-20250929}` ve üç sandbox clone execution'ı (`233`, `235`, `236`) success. Üretilen ana akış H1 niyetine yakın: Webhook → Sheet Oku → Kod → AI Agent → Gmail → Sheet Güncelle; Google Sheets/Gmail/Anthropic credential'ları attach edilmiş, ana workflow `active=false`. Ancak H1 fonksiyonel oracle'ı hâlâ geçmedi: `Kod` node'u gönderilmiş satırları `mail_atildi_mi !== 'TRUE'` ile eliyor, `Sheet Güncelle` ise aynı alanı `"Gönderildi"` yapıyor. Bu değer uyumsuzluğu ikinci çalıştırmada aynı satırların yeniden seçilip tekrar mail atmasına yol açar. Ayrıca update `matchingColumns=["firma_adi"]` kullanıyor; doğru satır garantisi için benzersiz email/row id daha güvenli. Sonuç: sandbox build/path başarılı ama idempotency/write-back semantiği hatalı; gerçek side-effect run yapılmadı. Bir sonraki fix, status filtre ve update değerini aynı kanonik değere bağlamalı ve H2 ile kardeş doğrulama yapılmalı. |
