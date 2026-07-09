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

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-07 | Kaldı | Sheet inceleme (`run_platform_action` → `GET .../values/A1:Z10`) başarılıydı; agent `search_n8n_nodes` + iki `get_node_schema` çağrısından sonra `agent_unexpected_model_behavior`: "Model token limit ... exceeded before any response was generated" verdi. Kök neden workflow JSON veya DeepSeek değil, lokal config drift: root `.env` `CONDUUT_MODEL_PROFILE=default` kaldığı için runtime `profile=default`, `provider=anthropic`, `model=claude-sonnet-4-6` seçti. Düzeltme: `.env` `CONDUUT_MODEL_PROFILE=deepseek`; yanlış ara teshisle eklenen Anthropic token-budget kodu geri alındı. Test: `test_thinking_builder.py` + `test_runner.py` hedefli suite ve ruff temiz. Kardeş-doğrulama bekliyor; H1 aynı task ile yeniden koşulacak. |
| 2026-07-08 | Kaldı | Gece son deneme (`conversation=890363de`, workflow `qTrjFjmakuZKGPI4`) artık doğru Conduut profiliyle çalıştı: `profile=deepseek`, `provider=deepseek`, `model=deepseek-v4-pro`. Sandbox yine `AI Agent` node'unda düştü; hata workflow içindeki n8n `Anthropic Chat Model` node'unun eski Claude ID'leri kullanmasıydı (`claude-3-haiku-20240307`, sonra `claude-3-5-sonnet-20241022`). Kök neden: ham n8n `nodes.json` latest v1.3 `model` `resourceLocator` parametresini içeriyordu, fakat `n8n-registry` loader'i `displayOptions` bulunan parametreleri attığı için `get_node_schema` agent'a model default'u ve `searchModels` metadata'sını göstermiyordu. Düzeltme: registry schema extraction latest/default version koşullarını değerlendiriyor, `resourceLocator` parametrelerini ve dinamik seçim metadata'sını `keyParameters`/`exampleNode` içine taşıyor; Anthropic'e özel hardcoded normalizer/prompt kuralı kaldırıldı. Canlı `qTrjFjmakuZKGPI4` workflow'undaki daha önce yapılmış manuel model patch'i repo diff'i değil; gerçek Gmail/Sheets side-effect çalıştırılmadı. H1 sandbox/gerçek run yeniden koşulmalı; kardeş H2 doğrulaması bekliyor. |
| 2026-07-09 | Kaldı | Gece koşusu (`Toplu Tanıtım Maili - Sheet'ten`, workflow `Mm10bScLRc9sBO4M`) artık Anthropic schema/model sorununu aşmış: `lmChatAnthropic` v1.3 `model={__rl:true, mode:list, value:claude-sonnet-4-5-20250929}` ve üç sandbox clone execution'ı (`233`, `235`, `236`) success. Üretilen ana akış H1 niyetine yakın: Webhook → Sheet Oku → Kod → AI Agent → Gmail → Sheet Güncelle; Google Sheets/Gmail/Anthropic credential'ları attach edilmiş, ana workflow `active=false`. Ancak H1 fonksiyonel oracle'ı hâlâ geçmedi: `Kod` node'u gönderilmiş satırları `mail_atildi_mi !== 'TRUE'` ile eliyor, `Sheet Güncelle` ise aynı alanı `"Gönderildi"` yapıyor. Bu değer uyumsuzluğu ikinci çalıştırmada aynı satırların yeniden seçilip tekrar mail atmasına yol açar. Ayrıca update `matchingColumns=["firma_adi"]` kullanıyor; doğru satır garantisi için benzersiz email/row id daha güvenli. Sonuç: sandbox build/path başarılı ama idempotency/write-back semantiği hatalı; gerçek side-effect run yapılmadı. Bir sonraki fix, status filtre ve update değerini aynı kanonik değere bağlamalı ve H2 ile kardeş doğrulama yapılmalı. |
