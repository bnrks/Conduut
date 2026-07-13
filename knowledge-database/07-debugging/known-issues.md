# Known Issues

Merkez: [[index]]

Bu not, repo icinde gorulen bilinen sorunlari ve dikkat noktalarini toplar.

Kullanicinin yeni fark ettigi ve henuz triage edilmemis sorun/bug notlari icin
ayri alan: [[issue-backlog]].

## Workflow ici Anthropic Chat Model eski Claude model ID'leriyle patladi (2026-07-08, cozuldu)

**Belirti:** H1 cold outreach workflow'u (`qTrjFjmakuZKGPI4`, conversation
`890363de`, request `aaed022d`) DeepSeek Pro ile uretildi/onarildi
(`profile=deepseek`, `provider=deepseek`, `model=deepseek-v4-pro`) ama sandbox
testi `AI Agent` node'unda defalarca dustu. `sandbox_test_needs_attention`
bulgusu: `"The resource you are requesting could not be found — model:
claude-3-haiku-20240307"`; sonraki denemede `claude-3-5-sonnet-20241022` de
ayni sekilde patladi.

**Kok neden:** Bu Anthropic, Conduut'un kendi agent/router saglayicisi degil;
n8n workflow icindeki `@n8n/n8n-nodes-langchain.lmChatAnthropic` node'unun
Anthropic API credential'iyle cagirdigi modeldi. Ham n8n `nodes.json` icinde
latest v1.3 `model` parametresi `resourceLocator` olarak vardi; fakat
`packages/n8n-registry` loader'i `displayOptions` gordugu her parametreyi
atladigi icin `get_node_schema` bu bilgiyi agent'a tasimiyordu. Bu nedenle
agent eski template/hafiza etkisiyle Claude 3 / 3.5 ID'leri veya "Sonnet 4" gibi
muallak adlar yazabiliyordu.

**Cozum:** Asil duzeltme `packages/n8n-registry` katmaninda yapildi:
`displayOptions.show/hide @version` kosullari latest/default node version'a gore
degerlendiriliyor, latest `resourceLocator` parametreleri `keyParameters` icine
aliniyor ve `modes.typeOptions.searchListMethod`, `loadOptionsMethod` gibi
dinamik secim metadata'si kondanse ediliyor. `lmChatAnthropic` icin
`get_node_schema` artik v1.3 `model` parametresini `resourceLocator` olarak,
default `claude-sonnet-4-5-20250929` ve `searchModels` list method'u ile
dondurur; `exampleNode.parameters.model` da n8n'in bekledigi
`{__rl, mode, value}` formatinda gelir. Yanlis ara cozum olan Anthropic'e ozel
hardcoded model normalizer/prompt kurali ve testleri kaldirildi. Canli
`qTrjFjmakuZKGPI4` workflow'una daha once yapilan manuel model patch'i repo diff'i
degildir; bu not onu geri almaz.

## H1 kosusunda `.env` model profili `default` kalmis → DeepSeek yerine Sonnet calisti (2026-07-07, cozuldu)

**Belirti:** Senaryo bankasi H1 kosusunda (`f7aa5f67`, request
`6848d99e`) agent Sheet'i direct action ile basariyla inceledi
(`GET .../values/A1:Z10` 200), artifact preview emit etti, sonra
`search_n8n_nodes` ve iki `get_node_schema` cagrisi yapti. Hemen ardindan
`agent_unexpected_model_behavior`: `Model token limit (provider default)
exceeded before any response was generated` verdi. Hata workflow create/update
asamasina gelmeden oldu; Sheets API veya n8n schema hatasi degildi.

**Kok neden:** Kodda `Settings.model_profile` default'u `deepseek`, ama lokal
root `.env` dosyasi `CONDUUT_MODEL_PROFILE=default` olarak kalmis. Bu override
runtime'da DeepSeek Flash/Pro router yerine `PROFILE_DEFAULT`'u secti; loglarda
`profile=default`, `provider=anthropic`, `model=claude-sonnet-4-6` goruldu. Yani
hata DeepSeek davranisi degil, lokal config drift idi.

**Cozum:** Root `.env` `CONDUUT_MODEL_PROFILE=deepseek` olarak duzeltildi.
Yanlis ara teshisle eklenen Anthropic `max_tokens` kod degisikligi geri alindi.
Hedefli testler (`test_thinking_builder.py`, `test_runner.py`) ve ruff temiz.
H1 ayni task ile yeniden kosulacak; asil Sheets update/matchingColumns oracle'i
hala bekliyor.

## googleSheets v4 sema uyumsuzlugu → workflow runtime'da crash (2026-07-01, fatal kisim cozuldu)

**Belirti:** "Sipariş Onay Maili" testinde (kullanici log incelemesi,
conversation `6729700d`, DeepSeek V4) agent iki Sheets dosyasi arasinda
lookup + 15:00 cutoff + mail + "evet"e geri-yazma iceren workflow uretti,
aktive etti — ama **hicbir zaman calismadi**. Aktivasyondan sadece 8dk gectigi
icin (schedule 15dk) henuz execution yoktu; ama kok neden execution beklemeden
belli: tetiklendiginde **ilk node (Read Siparisler) patlardi**.

**Kok neden (kurulu n8n 1.121.3 `Google/Sheet/v2/actions/router.js` ile
dogrulandi):** model uc Sheets node'unu da v4-oncesi semayla yazmis:
`resource: "spreadsheet"` + `spreadsheetId` + `range: "Siparisler!A:F"`.
v4 router `resource: "spreadsheet"`'i yalniz `create`/`delete` implement eden
module yonlendirir → `spreadsheet["read"]` = `undefined` →
`Cannot read properties of undefined (reading 'execute')`. Sistematik: yetim
kopya (`bshJwFCLXEN2lwS6`) da ayni semadaydi. Mevcut Stage 7 RL-normalizer
`documentId`/`sheetName` beklediginden hic tetiklenmemisti.

**Cozum (TDD, `repair.py` Stage 6, [[adr-0010-json-surface-repair-normalizer]]):**
`resource:spreadsheet`+satir-op → `sheet`; `spreadsheetId`→`documentId`;
`range:"Tab!..."`→`sheetName:"Tab"`. RL sarma'dan once calisir. Gercek bozuk
workflow node'lari fix'ten gecirilerek dogrulandi: iki Read artik gecerli v4.7,
crash gitti. `test_repair.py` +5 test, tum agent suite **386 passed**, ruff temiz.

**ACIK KALAN (bilincli/triage):**
1. **Update kolon-eslemesi — validation kontrolu eklendi (2026-07-01).**
   `Update Siparis`'te `dataMode:"raw"` (gecersiz) + duz `values` var; v4 update
   `columns`+`matchingColumns` ister. Repair bunu **onarmaz** (dogru eslesen-kolonu
   yeniden kurmak belirsiz; yanlis tahmin yanlis satira yazar). Bunun yerine
   `validation._validate_google_sheets_node` (mevcut `_validate_gmail_node`
   precedent'i) update/appendOrUpdate'te `columns` yoksa/`matchingColumns` bossa
   **ModelRetry** ile reddeder; ipucu hedef v4 sekli birebir gosterir + birakilacak
   legacy key'leri (dataMode/values/range) isimlendirir. Gercek bozuk workflow'la
   uctan-uca dogrulandi (repair→validate → dogru hata). **KALAN risk:** validation
   tespit eder, duzeltmeyi *model* yapar; v4 update mapping karmasik oldugundan
   DeepSeek retry'da toparlamazsa yine basarisiz olabilir → daha guclu tamamlayici:
   prompt.py'a kanonik Sheets-update few-shot
   ([[adr-0010-json-surface-repair-normalizer]] "few-shot=gecici finetune").

   **Canli dogrulama (2026-07-01, conversation `2a04bf12`, yeniden uretim):**
   fix'ler CANLI calisti. (a) repair Stage 6 uc Sheets node'unu v4'e cevirdi
   (loglarda `set googleSheets resource=sheet` / `mapped ...`). (b) `create_workflow`
   validation'da `Mark Sent` update'inin `columns`'u eksik diye reddedildi (benim
   hint'im, dataMode/values isimlendirildi). (c) **model tek retry'da toparladi**:
   ikinci create'te `columns={mappingMode:defineBelow, matchingColumns:["siparis_no"],
   value:{teslim_mail:"evet"}}` uretti → validation gecti, tek workflow (orphan yok),
   `$input.all()`+index (onceki `$input.first()` bug'i yok), filtre case-insensitive.
   Yani validation+ipucu yaklasimi DeepSeek'i **gercekten yakinsatti** — few-shot
   simdilik gerekmedi. **AMA ikinci-derece bug ortaya cikti + duzeltildi:** model
   `matchingColumns:["siparis_no"]` dedi ama `columns.value`'ya `siparis_no`
   **degerini koymadi**; v4 update eslesme degerini `columns.value["siparis_no"]`'dan
   okur (`update.operation.js:312`), bossa `"The 'Column to Match On' parameter is
   required"` firlatir. `_validate_google_sheets_node` **genisletildi**: defineBelow'da
   her `matchingColumns` girdisi `columns.value`'da (dolu) olmali; degilse hedef-ornekli
   hint. autoMapInputData'da item'dan geldigi icin istenmez. Toplam `test_workflow_validation.py`
   +6 test, suite **392 passed**, ruff temiz; gercek `Mark Sent` node'u validate edilerek
   dogrulandi.

   **DIKKAT — su an aktif workflow (`Z4vuApPVx2buTpBy`) bu genisletmeden ONCE
   uretildi:** `Mark Sent` hala `siparis_no` degeri eksik → tetiklenince (30dk schedule,
   aktivasyon 12:45 UTC) Mark Sent runtime'da patlar. Iki senaryo: (i) `siparis_saati`
   kolonu YOKsa Process Orders `undefined.split` ile once patlar → mail gitmez; (ii)
   kolon VARsa mail gider ama Mark Sent patlar → satir "evet"e yazilmaz → **her tick'te
   tekrar mail (duplicate)**. Oneri: bu workflow'u DEAKTIVE et + yeniden urettir
   (genisletilmis validation artik dogru Mark Sent'i zorlar). `siparis_saati` /
   snake_case header varsayimlari veri-bagimli; validation'da cozulemez (kullanici
   dogrulamali) — bkz. madde 3.
2. **Platform gap:** sandbox `test_workflow` + `analyze_workflow_readiness` +
   `repair.py` ucu de calismayan workflow'u "hazir" gecirdi. Sandbox gate read
   node'larini gercekten execute edip bu TypeError'i yakalamiyor.
3. **Ikincil (agent davranisi, ayni testte):** (a) agent tek run'da iki workflow
   yaratip zayif olani aktive etti, iyi olani (9-node, lookup+row-num) yetim
   birakti; (b) aktif Code node'u `runOnceForEachItem`'da `$input.first().json`
   kullaniyor → cok siparişte hepsi ilk siparisin verisiyle gider (`$input.item`
   olmali); (c) `siparis_saati` kolonu varsayimi — kullanici o kolonu tanimlamadi,
   yoksa cutoff sessizce hep "ayni gun"; (d) kolon E hardcode + snake_case header
   varsayimi (`teslim_mail`/`urun_kodlari`) gercek basliklarla eslesmezse kirilir.
   Bunlar repair kapsaminda degil; prompt/few-shot veya agent-akisi isi.

### E1 (webhook→Sheets append): bare `range` tab adi + eksik `columns` → workflow "has issues", hic calismadi (2026-07-02, cozuldu; uctan-uca deferred)

**Belirti:** Senaryo bankasi E1 ("Iletisim Formu → Google Sheets", conv
`1e2e07e5`, DeepSeek V4). Agent Webhook→Set→googleSheets(append) workflow'u kurup
aktive etti; webhook POST → **HTTP 500**, n8n execution #212 `status=error`,
**0 node** ("The workflow has issues and cannot be executed").

**Kok neden:** append node tab'i v4'un zorunlu `sheetName` (`__rl`) alani yerine
legacy top-level `range: "Kayitlar"` (`!` yok) olarak yazmis + `columns` eslemesi
hic yok. `sheetName` olmadan n8n node'u gecersiz sayip workflow'u hic calistirmiyor.
Iki katman boslugu: (a) repair Stage 6 `range→sheetName` YALNIZ `!` iceren
range'lerde calisiyordu; bare "Kayitlar" "belirsiz" diye dokunulmadan birakiliyordu;
(b) validation yalniz `update`/`appendOrUpdate`'i denetliyordu, duz `append`
bostan geciyordu.

**Cozum (TDD, genel; [[adr-0010-json-surface-repair-normalizer]]):**
- **repair.py Stage 6 genisletildi:** bare `range` (`!` yok) A1 notasyonu DEGILSE
  (`_A1_RANGE_RE`) → deterministik `sheetName`'e tasi, `range` sil (Stage 7 `__rl`
  sarar). Gercek A1 araligi (`A:F`, `A1:C10`) validation'a birakilir. Ayrica
  `operation=="append"` + `columns` yoksa → `mappingMode: autoMapInputData` (n8n
  default; append icin tek belirsiz-olmayan esleme; update/appendOrUpdate dokunulmaz).
- **validation.py emniyet agi:** her googleSheets satir-op'u (read/append/update/…)
  `sheetName` yoksa hedef `__rl` seklini gosteren ModelRetry hint'iyle reddeder.
- **test:** `test_repair.py` +4, `test_workflow_validation.py` +1 (3 mevcut update
  fixture'ina gercekci `sheetName` eklendi). Suite **397 passed**, ruff temiz.

**Genellik guard (senaryo-bankasi kurali):** fix task metnine degil node-tipi/desen
duzeyinde; ayni duzeltme M3 (webhook→Sheets append) ve M1/H1/H2 (Sheets read/update)
satir-op'larini da kapsar.

**2. tur — `columns.schema` (2026-07-02, cozuldu, ampirik dogrulandi):** sheetName
fix'i sonrasi E1 chat'ten yeniden kuruldu → workflow artik pre-flight'i geciyor
(Webhook+Sheets execute oluyor), ama Sheets node runtime'da **`Could not get
parameter: columns.schema`** ile patliyor. Kok neden: bu rebuild'de Set node yoktu
(Webhook→Sheets direkt), model `columns`'u `defineBelow` ile ama **yanlis yapida**
yazdi: `value: {"mappingValues": [{"column","mappingValue"}]}` + `schema` yok.
n8n v4 duz `value` map + `schema` dizisi bekler. **Ampirik zemin:** test workflow'un
columns'u kanonik sekle (`value` map + synth `schema`) cevrilip webhook tetiklendi →
execution #217 **status=success**, satir dustu. **Cozum (repair.py):**
`_normalize_sheets_columns_shape` — `value.mappingValues[]` → duz map'e flatten +
defineBelow'da `schema` eksikse kolon adlarindan synth (`_sheets_schema_entry`);
dogru sekiller ve autoMapInputData dokunulmaz. `test_repair.py` +3, suite **401 passed**.
**Kalan:** agent'in gercek uretim yolundan (chat rebuild) uctan-uca geciş — repair
canli (uvicorn reload), sonraki rebuild'de dogrulanacak.

**Not (test ortami):** ayni testte DeepSeek profili (`config.py` default
`model_profile="deepseek"`) ~10dk **stall→ReadTimeout** verdi (`agent_run_error`);
"takildi" hissinin sebebi buydu, Conduut bug'i degil. Senaryo-bankasi kosulari
guvenilir sinyal icin `default` profille yapilmali — bkz. [[scenario-bank]],
[[claude-vs-deepseek-comparison-2026-06]]. **(Update 2026-07-02: DeepSeek'te
kalma karari verildi — dusuk maliyet + kalite; asagidaki timeout hardening ile
stall hafifletildi.)**

## DeepSeek ~10dk stall → ReadTimeout (OpenAI SDK 600s default timeout, 2026-07-02, cozuldu)

**Belirti:** Senaryo bankasi E1 turunda (DeepSeek V4, conv `1e2e07e5`) agent run'i
`07:00:43`→`07:10:44` arasi **~10 dakika** yanitsiz kaldi, sonra
`agent_run_error: ReadTimeout` + `reliability_guard_garbage: provider_error`.
Kullaniciya "takildi" gibi gorundu; gercek bir kullanici da 10dk donmus ekran gorurdu.

**Kok neden:** `provider_factory.build_model` DeepSeek (ve openai) istemcisini
`OpenAIProvider(base_url, api_key)` ile **ozel timeout/http_client vermeden**
kuruyordu. OpenAI SDK varsayilan request timeout'u **600s (10dk)** → DeepSeek bir
stream'i yanitsiz biraktiginda istemci tam 10dk bekleyip ReadTimeout veriyor.

**Cozum (TDD):** `_openai_compatible_client(api_key, base_url)` helper'i
`AsyncOpenAI`'yi `timeout=httpx.Timeout(connect=15, read=120, write=60, pool=15)`
+ `max_retries=2` ile kurar; `openai` + `deepseek` case'leri bunu
`OpenAIProvider(openai_client=...)` ile kullanir. Stream'de 120sn byte gelmezse
hizli basarisiz → SDK retry; saglikli uzun uretimi kesmez (chunk'lar read'i canli
tutar). `test_provider_factory.py` +2, suite **399 passed**, ruff temiz.

**Reliability data point (bake-off):** DeepSeek'in ~10dk stall vermesi
[[model-cost-research-2026-06]] / [[claude-vs-deepseek-comparison-2026-06]] icin
operasyonel guvenilirlik verisidir; timeout+retry ile hafifletildi ama
saglayici-kaynakli stall'in kendisi maliyet/kalite kararinda not edilmeli.

## DeepSeek guard UI'i run sonuna kadar bos birakiyordu (2026-07-11, cozuldu)

**Belirti:** #1244 tool-call-as-text korumasi DeepSeek attempt'inin tum event'lerini buffer
ettigi icin uzun build sirasinda UI yalniz "Conduut is thinking" gosteriyor; tool asamalari ve
thinking ancak run bittikten sonra replay ediliyordu. Guard calissa bile urun takilmis hissi
veriyordu.

**Cozum:** Whole-run buffer/replay kaldirildi. Incremental guard + kisa look-behind ile event'ler
`attempt_id` tasiyarak canli akar. Hata replay-safe asamada yakalanirsa `recovery` SSE UI'daki
yarim attempt'i temizler ve en fazla iki kez sifirdan dener. Merkezi replay-safety katalogu
workflow/credential/platform mutation'i baslamissa otomatik retry'yi engeller; duplicate yan
etki yerine gecerli kartlar ve guvenli toparlama mesaji dondurulur. Bozuk attempt persist edilmez.
Ilgili: [[model-cost-research-2026-06]], [[chat-workflow-generation]], [[agent-service]].

### Repetition detector normal cok-turlu ozeti loop sandi (2026-07-12, cozuldu)

Canli salt-okuma testi (conversation `5d560203-2adc-44d9-914a-c3e1022564ab`)
uc attempt'te de `list_workflows` ve `get_workflow` tool'larini basariyla calistirdi;
ancak guard her seferinde `reason=repetition` verip temiz sonucu reddetti ve sonunda
`reliability_guard_exhausted` uretti. Kok neden DeepSeek task basarisizligi degil,
ayni 20 karakterlik pencerenin attempt'in farkli model response'lari boyunca dort kez
gorulmesini loop sayan fazla genis detector'du.

Fix: repetition state her model response sonunda sifirlanir. Detector
`20/40/80/160/320/640/1280` karakter pencerelerinde yakin eslesmeleri arar ve
false-positive'i azaltmak icin tum tekrar periyodunun gercekten ayni oldugunu dogrular;
boylece 8K siniri icinde dort kez tekrarlanabilen yaklasik 2.000 karaktere kadar tum
periyotlar runaway sinirini beklemeden yakalanir. Exact tool-call-as-text ve attempt-geneli
8.000 karakter
runaway korumalari degismedi. Failure logu ham icerik yerine SHA-256 fingerprint, pencere/
periyot boyutu, tekrar sayisi, gap ve karakter sayaclari tasir. Regresyon testleri normal
cok-turlu narrasyon/yapilandirilmis ozeti kabul ederken kisa ve uzun split-chunk loop'lari
reddeder. Streaming detector her karakter icin cok-olcekli rolling 64-bit hash gunceller;
tool regex'i yalniz kisa suffix'i tarar. Hash yalniz aday uretir, karar dort tam periyodun
birebir karsilastirilmasiyla verilir; dorduncu blok tamamlanmadiysa aday `required_end`'e
kadar bekletilir. 7.999 tek-karakter chunk benchmark'i yaklasik 0,21 sn'dir.

## create_workflow, silinmis dedup id'sinde 404 → "Agent could not complete" (2026-07-02, cozuldu)

**Belirti:** Kullanici ayni sohbette "otomasyonu sil ve bastan yap" dedi → agent
uzun bir retry loop'una girip her `create_workflow`'da basarisiz oldu, sonunda
generic **"Agent could not complete the task."**. Log: `n8n_request_error GET
/workflows/<id> 404` + `tool_error create_workflow: Not Found`, tekrar tekrar
(E1 rebuild, conv `1e2e07e5`, profil `default`/Sonnet).

**Kok neden:** `create_workflow` tool'undaki dedup mantigi (`factory.py`): ayni
sohbette ayni isimli workflow varsa create yerine **update** eder.
`existing_id = conversation_workflows[name]` sohbet gecmisindeki
`workflow_preview.id`'den gelir. Kullanici o workflow'u **sildigi** icin
`get_workflow(existing_id)` → **404** → create_workflow recreate'e dusmeden
tamamen patliyordu. (repair/columns fix'leri calisiyordu — `normalized
googleSheets...` loglarda; sorun bu degildi.)

**Cozum (TDD):** `_dedup_existing_workflow(existing_id)` helper — 404'te (workflow
silinmis) `None` doner → caller stale id'yi `conversation_workflows`'tan unutup
**fresh create** eder; non-404 hatalar propagate. `test_workflow_build.py` +4
(none-id / present / 404→None / non-404 reraise). Suite **405 passed**, ruff temiz.

**Not:** Bu run `default` profil (Sonnet) idi → DeepSeek stall'i yoktu; hata
tamamen dedup-id bug'iydi (E1 Sheets fix'leriyle ilgisiz, ayni sohbetin
kirli context'inden tetiklendi).

## `/api/workflows` N+1 ile ~4sn (2026-06-22, cozuldu — canli dogrulama bekliyor)

**Belirti:** Dashboard workflows sayfasi acilirken uzun suruyordu. Kullanici
bunu "frontend/Turbopack yavas" sandi; gercek neden backend veri cekme.

**Kanit (agent log `logs/agent/conduut-agent.jsonl`):** `GET /api/workflows`
**duration_ms: 4062** (baska ornek 2797). Icinde n8n'e N+1 fan-out:
`GET /workflows` (list) 866ms + her workflow icin ayri `GET /workflows/{id}`
(2380/1892/1369/836ms). Karsilastirma: `/api/conversations` ~205ms,
`/api/conversations/{id}` ~236ms (saglikli; N+1 yok).

**Kok neden:** `routes/workflows.py:list_workflows` her workflow icin
`n8n_client.get_workflow(w.id)` ile **tum workflow JSON'unu** cekiyordu —
sadece `node_count = len(detail["nodes"])` icin. `asyncio.gather` ile paralel
ama n8n basina 0.8-2.4sn oldugundan en yavasi + list cagrisi toplami ~4sn.

**Cozum (TDD):** n8n list cevabi her workflow'un `nodes`'unu zaten dondurur →
`N8nWorkflow.node_count` alani eklendi, `list_workflows()` bunu list cevabindan
doldurur, route artik per-workflow `get_workflow` ATMAZ (sadece input_schema
icin Firestore metadata'ya paralel gider). Beklenen: 4sn → ~1sn. Test:
`test_list_workflows_does_not_fetch_each_workflow` (get_workflow cagirilirsa
AssertionError). **261 passed (5 Windows-tmp hata, alakasiz); ruff temiz.**

**BEKLEYEN canli dogrulama:** Varsayim — n8n public API `GET /api/v1/workflows`
list cevabi her item'da `nodes` dizisini icerir (standart n8n davranisi). n8n
kapaliyken test edilemedi. n8n acilinca dogrula:
`curl -H "X-N8N-API-KEY: <key>" http://localhost:6180/api/v1/workflows?limit=1`
→ ilk item'da `nodes` var mi? Yoksa nodeCount 0 gosterir (kozmetik regresyon,
crash degil) → o durumda list'e nodes dahil etme yolu eklenir.

**Ek optimizasyonlar (2026-06-22, uygulandi):**
- **Firestore metadata batch:** `store.get_all_workflow_metadata(user_id)` (tek
  `workflow_metadata` koleksiyon `.stream()`) eklendi; route artik per-workflow
  `get_workflow_metadata` (N+1) yerine bunu kullaniyor. `/api/workflows` artik
  **workflow sayisindan bagimsiz duz 2 cagri**: n8n list + tek Firestore sorgusu.
  `asyncio.gather` kaldirildi. Test: `metadata_calls == ["user_1"]`.
- **Sidebar refetch:** `conversation-sidebar.tsx` artik her gezinmede tum
  konusma listesini cekmiyor. `pathname`'den `currentConversationId` turetilir;
  liste yukluyse ve acilan konusma store'da varsa (eski chat'e gecis) fetch
  ATLANIR. Sadece ilk yuklemede veya store'da olmayan yeni konusma id'sinde cek
  (`useChatStore.getState()` ile loop-safe; yeni chat akisi store'u
  guncellemedigi icin `pathname` dep'i load-bearing'di, bu yuzden tamamen
  kaldirilmadi). Eski chat'e gecis: fazladan list fetch + hop yok.
- **xlsx lazy-load:** `workflows/page.tsx` top-level `import * as XLSX` kaldirildi;
  sadece dosya yuklenince `await import("xlsx")` (handler zaten async). Route'un
  ilk bundle/derlemesi hafifledi.
- **Chat streaming render O(N²) (frontend):** `message.tsx` her SSE token'inda
  tum mesaj listesini yeniden render edip, stream edilen mesajin TUM markdown'ini
  yeniden parse + `rehypeHighlight` (highlight.js, otomatik dil tespiti) ediyordu
  → uzun cevaplarda O(N²) CPU/jank, ayrica gecmis mesajlar da her token'da
  yeniden parse. Cozum (sadece render katmani, SSE state machine'e dokunulmadan):
  (1) `Message` artik `React.memo` — `upsertAssistantMessage` degismeyen mesajlari
  ayni referansla dondurdugu icin sadece stream edilen mesaj re-render olur;
  (2) `MarkdownContent` memoize + `streaming` prop'u → stream sirasinda
  `rehypeHighlight` ATLANIR (plain markdown), mesaj bitince (`isAgentTyping` false)
  bir kez highlight; (3) `message-list.tsx` son agent mesajini `isAgentTyping`
  iken `isStreaming` isaretler (her iki chat sayfasi da MessageList kullandigi
  icin ikisine de uygular). tsc temiz, eslint 0. Kullanici "yavas yukleme" olarak
  hissetmemisti (asil dert page-load'di) ama uzun yanitlarda gercek kazanc.
- **Credential reuse N+1 (readiness):** `readiness._discover_existing_credential`
  her workflow icin `get_workflow` (~934ms) atip node'larda credential ariyordu
  (activate/run + agent credential-reuse yolunda). n8n list cevabi node'lari
  (credentials dahil) zaten dondurdugu icin (canli dogrulandi: httpHeaderAuth,
  gmailOAuth2 list'te var) yeni `n8n_client.list_workflows_raw()` ile tek
  cagriya indirildi; `list_workflows()` de bunu kullanir (DRY). Test:
  `test_readiness` mock'u `list_workflows_raw` doner + `get_workflow` cagrilirsa
  AssertionError. **261 passed, ruff temiz.**

**Dogrulama:** agent 261 passed (5 Windows-tmp, alakasiz), ruff temiz; web tsc
temiz, eslint 0. Workflows N+1 canli dogrulamasi (n8n list `nodes` iceriyor mu)
hala bekliyor (yukaridaki curl).

## Dev server yavas: `--webpack` Turbopack'i devre disi birakmis (2026-06-22, cozuldu)

**Belirti:** Proje buyudukce `apps/web` dev sunucusunda "Compiling..." asamalari
uzadi, frontend agir hissettiriyordu. Kullanici bunu "Turbopack yavasligi" sandi.

**Kok neden:** `apps/web/package.json` dev script'i `next dev --webpack` idi —
yani Turbopack **bilerek devre disi birakilmis** ve yavas Webpack bundler'i
kullaniliyordu. `--webpack` flag'i 55de643 (alakasiz bir Gmail preview feature
commit'i) icinde, **hicbir gerekce yazilmadan** eklenmisti. `next.config.ts`
**bos** (hicbir `webpack()` ozellestirmesi yok) → Webpack'e gercek bir bagimlilik
yoktu. Proje aslinda kucuk (101 ts/tsx dosyasi, ~10k satir), yani darbogaz
**boyut degil bundler**.

**Kanit (ayni makine, cold compile, sadece bundler farkli; Next 16.2.1):**
| Route | Webpack | Turbopack | Hizlanma |
|---|---|---|---|
| `/` | 13.24s | 6.86s | 1.9x |
| `/chat` (markdown+highlight+motion) | 6.80s | 2.04s | 3.3x |
| `/dashboard/workflows` (xlsx) | 1.95s | 1.32s | 1.5x |

Turbopack **sifir hata/uyari** ile calisti → `--webpack` hic load-bearing degildi.

**Cozum:** `package.json` → `"dev": "next dev"` (flag kaldirildi; Next 16'da
Turbopack varsayilan). Iteratif compile 1.9–3.3x hizlandi.

**Ikincil notlar (uygulanmadi, opsiyonel):** (1) `workflows/page.tsx` `import * as
XLSX from "xlsx"` (buyuk CJS lib) sayfa tepesinde eager — kullanildigi handler'da
`await import("xlsx")` ile lazy yapilabilir. (2) Windows Defender real-time
scanning `node_modules`/`.next` klasorlerini taradigindan dev'i yavaslatabilir;
proje klasorunu exclusion'a eklemek Windows'ta ek hizlanma saglar.

## HTTP generic credential readiness'te tespit edilmiyordu (2026-06-20, cozuldu)

**Belirti:** API Ninjas workflow'u olusturulup calistirilinca n8n
`Credentials not found` (500) veriyordu. HTTP node'da
`authentication=genericCredentialType` + `genericAuthType=httpHeaderAuth` vardi
ama `credentials` **bos** (cred iliştirilmemis), ve agent build sirasinda
credential onerisi/karti hic emit etmemisti.

**Kok neden:** Registry'deki `n8n-nodes-base.httpRequest` semasi yalnizca
`credentials: ['httpSslAuth']` listeliyor — n8n generic auth tiplerini
(httpHeaderAuth/Basic/Query/Custom) `displayOptions` ile **kosullu** tanimladigi
icin sema extraction bunlari hic enumere etmiyor. `readiness._required_credential_types_for_node`
`genericAuthType`'in sema credentials listesinde olmasini sart kosuyordu
(`generic in credential_types`) → `'httpHeaderAuth' in ['httpSslAuth']` False →
`[]` donduruyor → readiness node'u atliyor → oneri yok, iliştirme yok → n8n
runtime'da patliyor. (Onceki calismada agent **proaktif** `list_credentials`+
`attach_credential` cagirdigi icin denk gelmis calismisti.)

**Cozum:** `authentication=genericCredentialType` iken `genericAuthType` set
ise, sema credentials listesinden bagimsiz olarak **`[genericAuthType]`**
donduruluyor (n8n o credential'i zaten sart kosuyor). Canli dogrulandi: gercek
workflow + kayitli "API Ninjas" credential → `reuse_candidates` uretiliyor.
Test: `test_readiness.py` (+2). **Confirm-first vs explicit Run:** agent'in
chat build akisi confirm-first kalir (`execute_workflow` reuse_candidate'te
bloklar, onay sorar). Ama **explicit dashboard "Run"** (ve batch run)
`workflow_runner._prepare_workflow_for_conduut_run` icinde
`readiness.attach_unambiguous_reuse_candidates` ile host'u tam eslesen **TEK**
kayitli credential'i **otomatik iliştirir** → "olustur → Run" sifir-friction
calisir (kullanici karariyla, 2026-06-21). Coklu eslesme onay icin birakilir.

## HTTP dizi cevabinda bos mail ($json[0] indexleme) (2026-06-21, cozuldu)

**Belirti:** "api-ninjas'tan soz cek -> mail" workflow'u calisti, agent chat'te
soz'u dogru gosterdi, ama gelen **mail bos**'tu. Gmail node ifadesi
`{{ $json[0].quote }}` idi.

**Kok neden:** n8n HTTP Request node'u bir JSON **dizi** cevabini ayri item'lara
**boluyor**; sonraki node'un `$json`'i artik dizinin ilk **objesi** (`{quote,
author}`), dizinin kendisi degil. Yani `$json[0].quote` -> undefined -> bos.
Execution datasi: Get Quote ciktisi 1 item, `json={quote, author, category}`
(dict). Agent chat ozetini dogru cikardi (LLM), ama n8n ifadesi yanlisti.

**Cozum:** `repair.py` `_repair_http_array_indexing` (Stage 5b): HTTP Request
node'una **dogrudan baglanan** node'larda `$json[<n>].field` -> `$json.field`,
ve herhangi bir node'da `$('Http').first().json[<n>].` -> `...json.` yeniden
yazimi (yalniz HTTP node'lar kapsaminda; Code-node dizileri dokunulmaz). Prompt
kurali da eklendi (HTTP dizi cevabi item'lara bolunur -> `$json.field`). Test:
`test_repair.py` (+3). 260 passed.

## Gmail runtime-input cikarimi sabit degerleri eziyordu (2026-06-20, cozuldu)

**Belirti:** "api-ninjas'tan soz cek -> sabit adrese mail at" workflow'unda agent
her turda `request_user_input` ile alici/konu/mesaj sorup duruyor, workflow hic
calismiyordu (sonsuz soru dongusu). Canli n8n'de `Send Email` node'u
`sendTo={{$json.body.to}}`, `subject={{$json.body.subject}}`,
`message={{$json.body.message}}` idi — agent'in kurdugu sabit alici + Get Quote
ciktisindan gelen mesaj **ezilmisti**.

**Kok neden:** `agent/tools/runtime_inputs.py` `_infer_runtime_input_schema`
herhangi bir Gmail-send node'u gorunce (agent acik `input_schema` vermediyse)
`to/subject/message`'i **zorunlu runtime input** yapiyor, `_apply_runtime_inputs_to_nodes`
da Gmail parametrelerini **kosulsuz** `$json.body.*` ile eziyordu. Sonra
`execute_workflow` bu zorunlu input'lari eksik gorup `request_user_input`
cagiriyordu. Kasitli ama hatali tasarim (iki test bu davranisi dogruluyordu):
"reusable e-posta" senaryosu icin yapilmis, "sabit alici + yukari-node icerigi"
senaryosunu kiriyordu. (Credential ozelligi dogru calisti; bu ayri bir bug'di.)

**Cozum (TDD):** Cikarim/uygulama artik yalnizca **bos** Gmail alanlari icin
runtime input uretir/doldurur; agent'in yazdigi somut degerler (sabit alici,
yukari-node mesaj expression'i) **korunur**. Placeholder alicilar zaten
`validation._looks_like_placeholder_email` ile yakalandigi icin "bos birak"
rescue'suna gerek yok. Gmail parametrik semasi artik `_GMAIL_RUNTIME_INPUT_FIELDS`
ile **acikca** bildirilir (dolu alanlardan infer etmez). _(2026-06-30, Faz 3:
eskiden bu liste spec compiler `_compile_gmail_on_demand` icindeydi; spec/graph IR
compiler'lari tamamen kaldirildi, mekanizma artik `tools/runtime_inputs.py`
icinde.)_ Prompt'a da: icerik yukari node'dan geliyorsa
referansla + sabit aliciyi hardcode et; runtime input sadece kullanici her
calistirmada deger girecekse. **237 passed, ruff temiz.** Eski bozuk workflow
(`7F4Dxt0r6LGUS9Ph`) agent yeniden kurunca duzelir.

## Router HARD kademesini cok zor secyor (2026-06-19)

Yeni 3-kademe router'i (gpt-5-mini, [[adr-0011-conduut-managed-tiered-models]])
istekleri agirlikli olarak **MEDIUM**'a atiyor; HARD nadiren tetikleniyor. Tek-IF
dalli "siparis onay" workflow'u (1000 TL ustu/alti -> mail/sheets + tesekkur maili)
bile MEDIUM siniflandirildi; canli testlerde `gemini-3.1-pro-preview` (HARD primary)
hic cagrilmadi. Router prompt'u belirsizde MEDIUM'a dusmeyi soyluyor, bu yuzden
HARD esigi pratikte cok yuksek.

- **Etki:** dusuk; MEDIUM (Sonnet) bu isleri zaten iyi kuruyor. Sadece pahali HARD
  modeli (Gemini 3 Pro) neredeyse hic kullanilmiyor -> tier ayrimi etkisiz.
- **Cozum (backlog):** router prompt'unda HARD kriterlerini keskinlestir (ornekler
  ekle: coklu Switch/dallanma, mevcut workflow debug, belirsiz cok-adimli istek),
  ya da MEDIUM-default egilimini gevset. Tuning birkac ornek prompt'la denenmeli.
- **Karar (2026-06-19):** simdilik dokunulmuyor; feature kapatildi, bu sadece not.

## Duplicated Nested App Paths

Worktree'de nested ve muhtemelen yanlis olusmus klasorler var:

- `apps/agent/apps/agent/src/agent/CLAUDE.md`
- `apps/web/apps/agent/...`
- `apps/web/apps/web/...`

Bunlar buyuk olasilikla onceki agent tooling tarafindan olusturulan bos/yanlis
memory dosyalari. Kullanici onayi olmadan silinmemeli. Temizlik yapilacaksa ayri
task olarak ele alinmali.

## Hardcoded Dev n8n Key

`docker-compose.yml` icinde dev n8n API key/JWT benzeri degerler var. Lokal MVP
icin kullaniliyor olabilir, fakat production icin uygun degil. Production'a
gidilmeden once env/secret yonetimine alinmali.

## Windows Port 8000 Exclusion

Windows ortaminda `netsh interface ipv4 show excludedportrange protocol=tcp`
`7981-8080` araligini reserve edebiliyor. Bu durumda Docker host port `8000`
publish ederken `ports are not available` hatasi alinir. `docker-compose.yml`
agent container portunu `8000` olarak birakir, fakat host tarafinda `8100`
publish eder: `8100:8000`. Web servisi Docker network icinde hala
`http://agent:8000` kullanir.

## Windows Port 5678 Exclusion

Bu makinede `netsh interface ipv4 show excludedportrange protocol=tcp` ciktisi
`5643-5742` araligini da reserve ediyor. n8n varsayilan host portu `5678`
oldugu icin Docker `ports are not available` hatasi verir. 2026-05-31
kontrolunde onceki alternatif `5980` de `5940-6039` exclusion araliginda
goruldu. `docker-compose.yml` n8n container portunu `5678` olarak birakir,
fakat host tarafinda yalnizca localhost'a varsayilan olarak `6180:5678`
publish eder. Lokal n8n UI icin adres: `http://localhost:6180`. Farkli port
gerekirse `CONDUUT_N8N_PORT` env degeriyle compose ve `start-local-dev.bat`
akisi override edilebilir.

## Windows Port 3000 Exclusion

2026-05-16 kontrolunde Windows port exclusion listesinde `2907-3006` araligi
goruldu. Bu nedenle Next dev server `0.0.0.0:3000` icin `listen EACCES:
permission denied 0.0.0.0:3000` hatasi verebilir; portta aktif process olmasi
gerekmez. Root `start-local-dev.bat` bu yuzden web'i default olarak
`127.0.0.1:3007` uzerinden baslatir ve agent icin `CONDUUT_PUBLIC_WEB_URL`'i
`http://localhost:3007` yapar. Farkli port gerekirse script oncesi
`CONDUUT_WEB_PORT` env degeri verilebilir. Google OAuth local callback'i icin
secilen portun Google Console redirect URI listesinde de bulunmasi gerekir.

## Firestore Plain API Keys

✅ Cozuldu/eskidi (2026-06-30): BYO-provider tamamen kaldirildi
([[adr-0011-conduut-managed-tiered-models]]) — kullanici LLM provider key'leri
(`ProviderConnection`/`LLMSettings`/`favorites`) artik yok; modeller
Conduut-yonetimli env key'leri + tier router ile calisir. Ayrica `store.py`
artik `src/store/` paketi. Yani "provider API key'leri Firestore'da plaintext"
sorunu gecersiz. (Tarihsel baglam: eskiden `apps/agent/src/store.py` provider
API key'lerini Firestore alanlari olarak kaydediyordu — MVP hizli cozumu,
production guvenlik riskiydi.)

Workflow credential metadata'si da Firestore'da tutuluyor; secret degerleri
n8n credential store'a yaziliyor. Yine de gercek production icin Vault/Secret
Manager ve per-user isolation gerekir.

Google Gmail connection flow'u raw Google access/refresh token'i Firestore'a
yazmaz; token data n8n `gmailOAuth2` credential store icinde kalir. n8n public
API `gmailOAuth2` credential create icin `oauthTokenData` disinda `serverUrl`,
`sendAdditionalBodyProperties` ve `additionalBodyProperties` alanlarini da
ister. Buna ragmen shared n8n instance nedeniyle production izolasyonu
sayilmaz. Public production icin per-user n8n veya secret isolation ve Google
sensitive scope verification ayri ele alinmali.

## Shared n8n Ownership Gap

Workflow routes shared n8n instance uzerinden tum workflow'lari listeler ve user
ownership filtrelemesi yapmaz. Bu [[adr-0001-shared-n8n-mvp]] kararinin dogrudan
sonucudur.

## Credential Prompt After Workflow Create

2026-05-09'da gorulen vaka: Chat ile Google Sheets append workflow'u
olusturuldu (`Form girdilerini Google Sheets'e ekle`), fakat Sheets node'unda
credential yoktu ve n8n execution kaydi olusmamisti. Root cause n8n hatasi
degil; eksik Google Sheets OAuth prompt'u emit edildikten sonra agent'in ayni
turda calistirma/activate denemelerine devam edebilmesiydi. Agent artik eksik
credential/OAuth attachment'i emit edince `awaiting_user_input` durumuna gecip
side-effect tool'larini durdurur ve kullaniciya once connection'i tamamlamasini
soylemelidir.

## Google Sheets OAuth Credential Schema

2026-05-09'da Sheets connection callback'i Google token exchange ve userinfo
adimlarini basariyla tamamladiktan sonra n8n credential create adiminda
`400 Bad Request` verdi. n8n `1.121.3` `googleSheetsOAuth2Api` credential
schema'si `additionalProperties=false` ve top-level `scope` alanini kabul
etmiyor. Scope yalnizca `oauthTokenData.scope` icinde tutulmali; aksi halde
`POST /api/v1/credentials` 400 doner. Eski OAuth state hata sonrasi kullanilmis
sayilabilecegi icin tekrar denemede yeni authorize akisi baslatilmalidir.

## Google Sheets Append Resource Mismatch

2026-05-09'da `D9Cowkphes0Jx7T6` workflow'u Google Sheets credential'i
baglandiktan sonra webhook'u `200 OK` ile kabul etti, fakat n8n execution `17`
`Google Sheets’e Yaz` node'unda `Cannot read properties of undefined (reading
'execute')` hatasiyla bitti. Node parametreleri `operation=append` ama
`resource=spreadsheet` idi. n8n Google Sheets v4 append operasyonu
`resource=sheet` altinda calisir. Normalizer artik yeni workflow'larda
`operation=append` + `resource=spreadsheet` kombinasyonunu `resource=sheet`
olarak duzeltir. Mevcut live workflow'lar otomatik patch'lenmemeli; kullanici
acikca onay verirse ilgili workflow update edilmelidir.

## n8n Editor Connection Shape

n8n public API bazi malformed `connections` payload'larini kabul edebiliyor,
fakat editor acilirken `Could not find workflow` ve `object is not iterable`
hatasina dusebiliyor. Gorulen ornek: `{"main": [{"node": "Gmail"}]}` flat
formatinin editor icin `{"main": [[{"node": "Gmail", "type": "main",
"index": 0}]]}` nested output array formatina cevrilmesi gerekiyor. Agent
normalizer bu formati artik otomatik duzeltir.

## Langchain Sub-Node Main-Flow Wiring (Bos AI Mail Govdesi)

2026-06-11: "Firmalara otomatik teklif" senaryosu test edilirken mail govdesi
bos gidiyordu (yalnizca baslik atiliyordu). Root cause: agent (gpt-4o-mini)
graph compiler'i (`create_workflow_from_graph`) **atlayip** ham `create_workflow`
JSON yolunu kullandi ve langchain chat-model sub-node'unu (`lmChatOpenAi`) duz
`main` akisina bagladi:

`Webhook -> OpenAI Chat Model -> Code -> Gmail` (hepsi main).

Langchain sub-node'lari (chat model, memory, tool, output parser) **main I/O'ya
sahip degildir**; yalnizca bir AI Agent'a `ai_*` portundan baglanir. Main akista
tek baslarina hicbir cikti uretmezler. Sonuc: Code dugumu `$json.text` =
undefined okudu, Gmail `message` bos kaldi, `subject` fallback "Teklif" oldu.
(Karsi ornek: ayni oturumdaki `3XskIaDrFUFUEcpv` dogru kurulmustu — model
`ai_languageModel` portundan AI Agent'a bagli, Gmail `={{$('AI Agent').first()
.json["output"]}}`.)

Cozum (defense-in-depth, kalici kok-neden fix):

- `apps/agent/src/agent/validation.py` — `validate_workflow_payload` artik
  langchain sub-node'larini (`_is_langchain_ai_subnode`: `lm`, `memory`,
  `embeddings`, `outputParser`, `textSplitter`, `retriever`, `tool` prefiksleri)
  `main` baglantisinda (kaynak veya hedef) yakalar ve hata dondurur. Hata
  `_validated_runtime_workflow` -> `ModelRetry` ile modele geri gider, yani hem
  `create_workflow` hem `update_workflow` ham yolunda zorlayicidir. AI Agent ve
  chain (`agent`, `chainLlm`, `chatTrigger`) bilincli olarak haric.
- `apps/agent/src/agent/tools/prompt.py` — "Node rules" bolumune ham JSON yolu
  icin langchain sub-node kurali eklendi (ai_* port zorunlulugu + bos cikti
  uyarisi).
- Test: `apps/agent/tests/test_workflow_validation.py` — 5 yeni test (main-target
  fail, main-source fail, ai_languageModel ile dogru baglama pass; bare
  `{{input.x}}` fail, trigger json.body ifadesi pass).

**Ikinci ham-yol bug'i (ayni kok-neden):** Ayni oturumdaki `TJ1BBPbuDhtGdUYD` ve
`3XskIaDrFUFUEcpv` wiring'i DOGRU kurmustu ama AI Agent prompt'unda gecersiz
`{{input.company_name}}` ifadeleri vardi. `input` n8n'de tanimli degildir (graph
compiler `{ref:'input.X'}`'i `$('trigger').json.body.X`'e cevirir; ham yol
ceviremez), bu yuzden kisisellestirme calismaz. Ek guard:
`validation.py` `_validate_input_expressions` artik `{{input.` (ve `{{ input.`)
deseni iceren parametre ifadelerini yakalayip `ModelRetry` dondurur. Yani ham
`create_workflow` yolu artik hem sub-node wiring'i hem gecersiz input ifadesini
reddediyor. Asil cozum agent'in `create_workflow_from_graph` kullanmasidir (her
iki hata da o yolda imkansiz); gpt-4o-mini build icin tutarsiz oldugundan daha
guclu bir model onerilir.

**Ucuncu ham-yol bug'i (2026-06-12):** Iki guard sonrasi agent **gpt-5 (thinking
medium)** ile yeniden kurdu (`HJXIBudaUl5ZU9Gp`): wiring DOGRU, `{{input.x}}` YOK
— ama Code node webhook girdisini `$json.company_name` ile okudu. Conduut webhook'a
payload'i POST body olarak gonderir (`n8n_client.call_webhook`), n8n bunu
`$json.body.*` altinda acar; dogru yol `$json.body.company_name`. Sonuc:
company/desc/services `undefined` -> AI kisisellestirilemeyen genel metin uretir
(mail bos degil ama yanlis). Code node jsCode'u freeform oldugundan ne validator
ne compiler ic veri yolunu denetler. Calisan workflow icin Code node `$json.X` ->
`$json.body.X` elle yamalandi. Prevention: `prompt.py` "Node rules"a "webhook
girdileri `$json.body.<field>` altindadir" kurali eklendi.

> **Model atfi duzeltmesi (2026-06-13):** Onceki notlar bu uc bug'i "gpt-4o-mini"ye
> bagliyordu — yanlis. 06-10 build'leri (`1jbY`, `TJ1B`) gpt-4o-mini idi, ama
> 06-12 build'i (`HJXIBudaUl5ZU9Gp`) konusma metadata'sina gore **gpt-5**. Yani
> uc ham-yol hatasini guclu bir reasoning modeli (gpt-5) bile uretti.

**Kok-neden (neden agent `create_workflow_from_graph`'i atliyor?) — 2026-06-13
statik analiz:** Sorun model gucu degil, **pretraining-onyargisi vs. Conduut'a-ozgu
soyutlama** catismasi:

- Agent'in 4 rakip "create" tool'u var: `create_workflow_from_graph`,
  `_from_plan`, `_from_spec` (hepsi Conduut'un uydurdugu IR'lar) ve `create_workflow`
  (ham n8n JSON). Ilk uçu yalnizca bu repoda + prompt'ta var; ham n8n JSON ise
  modelin pretraining'inde bol bol gecer (`@n8n/n8n-nodes-langchain.lmChatOpenAi`,
  connections objesi, `$json` ifadeleri internette her yerde).
- Herhangi bir belirsizlik/karmasiklik altinda model en yuksek olasilikli bildigi
  yola (ham JSON) geriler. WorkflowGraph IR'in `kind` sozlugu, `attached_to`/`role`
  mekanizmasi ve `{ref:'input.x'}` ifadeleri ogrenilmesi gereken yeni soyutlamadir.
- Karar anindaki tek yonlendirme zayifti: graph tool'unda "Preferred" kelimesi +
  bir prompt madde isareti. **Pydantic AI `@agent.tool` docstring'i LLM'e tool
  description olarak gonderir**, ama ham `create_workflow`/`update_workflow`
  docstring'leri tek satirlik ve notrdu ("Create a new n8n workflow after
  validating...") — hicbir karsi-sinyal vermiyordu. Karar noktasinda iki tool esit
  goruunuyor, model pretraining onyargisina gore ham yolu seciyor.
- Uc gozlemlenen bug da (langchain main-wiring, `{{input.x}}`, `$json.body` atlama)
  modelin hafizadan ham n8n JSON yazip Conduut'a-ozgu runtime detaylarini yanlis
  yapmasinin semptomudur.

**Cikarim:** Sadece prompt ile GPT-5'i guvenilir sekilde graph yoluna zorlayamazsin
(pretraining ile savasiyorsun). Dogru strateji ham yolu GUVENLI kilmak — her klasik
hatayi `ModelRetry`'a ceviren deterministik guard'lar. Uc delikten ikisi kapali
(wiring + input-expr guard'lari). Aksiyon (2026-06-13): ham `create_workflow` ve
`update_workflow` docstring'leri "Last-resort fallback only" olarak yeniden yazildi;
`create_workflow_from_graph`'a yonlendiriyor ve uc klasik hatayi (ai_* port,
`$json.body.<field>`, `{{input.x}}` yasak) karar aninda modele isaret ediyor —
sistem prompt'una gomulu bir madde yerine modelin gercekten okudugu tool
description'ina. **Beklemede:** body-path bug'i icin deterministik guard
(webhook'a dogrudan bagli node'larda, deklare edilmis runtime input alanini
`.body` olmadan okuyan `$json.<field>` ifadesini yakalayan, dusuk-yanlis-pozitif
kapsamli) tasarlandi ama n8n offline oldugu icin uctan uca dogrulanamadi; canli
n8n ile dogrulanip eklenecek.

Not: O an n8n'de duran bozuk workflow (`1jbYOquxyrLtxTOk`) silinmedi/yeniden
kurulmadi; kullanici secimi yalnizca kalici fix idi. Agent'a yeniden kurdurulursa
guard artik dogru yapiyi zorlar. Ilgili: [[adr-0009-workflow-graph-compiler]],
[[agent-service]].

**COZUM (2026-06-14, [[adr-0010-json-surface-repair-normalizer]]):** Uc ham-yol
bug'i artik deterministik **onariliyor** (reddedilmiyor). Yeni `agent/repair.py`
hatti (normalize -> repair -> validate): (1) tek-agent varsa langchain sub-node'u
`main`'den alip `ai_languageModel` portuna tasir; (2) `{{input.x}}`'i
`$('<trigger>').first().json.body.x`'e cevirir; (3) trigger'a dogrudan bagli
node'da deklare runtime input icin `$json.x`'i `$json.body.x`'e cevirir (Code
jsCode dahil). Model artik IR yerine kompakt n8n JSON yaziyor (IR tool'lari
model yuzeyinden kaldirildi), bu yuzden A->B format catismasi da ortadan kalkti.
Belirsiz durumlar (cok-agent, trigger yok) hala `validate_workflow_payload`
tarafindan reddedilir. Test: `test_repair.py` (9) + `test_tools.py` pipeline
testi.

**GUNCELLEME (2026-06-30, Faz 3):** IR compiler'lari (`graph_compiler.py`,
`spec_compiler.py`, `blocks.py`) ve rakip `create_workflow_from_graph`/`_plan`/`_spec`
tool'lari **tamamen kaldirildi**. Artik tek canli yol kompakt n8n JSON yuzeyi
(`create_workflow`/`update_workflow`) + `agent/repair.py` hatti. Yani yukaridaki
uzun "agent neden `create_workflow_from_graph`'i atliyor?" pretraining-onyargisi
analizi tarihsel/gecersizdir — atlanacak bir IR yolu kalmadi; ham yol = tek yol
ve uc klasik hatayi `repair.py` deterministik onariyor. (validation.py ve
prompt.py guard'lari yerinde; build pipeline `tools/build_pipeline.py`.)

**Canli dogrulama (2026-06-15, `HMIb1xyrmhcoZlS8`, gpt-5):** Uc klasik bug da
YOK — AI Agent `{{ $json.body.company/... }}`, Gmail `{{ $json.body.email }}` +
`{{ $('AI Agent').first().json.output }}`, chat model `ai_languageModel`
portunda. **Ama yeni bir regresyon yakalandi:** ai_languageModel baglantisinin
`type` alani `"main"` idi (dogru: `"ai_languageModel"`). Kok-neden:
`normalize_workflow_connections` -> `_ensure_connection_target` her hedefin
`type`'ini korlemesine `"main"` yapiyordu; AI portu altindaki baglantilarda bu
n8n'in chat model'i gormezden gelmesine -> bos agent'a yol acar. Fix:
`_normalize_connection_shape` artik port adini (`ai_languageModel`/`ai_tool`/...)
hedef `type`'ina threadliyor (test: `test_normalize_connections_assigns_ai_port_type`).
Few-shot ornegine de acik `"type": "ai_languageModel"` eklendi. Canli workflow
API'den yamalandi.

**Calistirma sirasinda iki ek bug daha (2026-06-15, execution datasi ile):**
Ilk execution `error` verdi ve AI ciktisi `{{ $json.body.company }}`'i LITERAL
icieriyordu. Iki kok-neden:
1. **`=` oneki eksik:** AI Agent `text` (ve Gmail `subject`) `{{ }}` iceriyordu
   ama `=` ile baslamiyordu; n8n bir alani ancak `=` ile basliyorsa ifade olarak
   degerlendirir, aksi halde `{{ }}`'i duz metin gonderir. Fix: `repair`
   `{{ }}` iceren ama `=`'siz alanlara `=` ekler (Code `jsCode` haric — o JS'tir).
2. **Dolaylı node'da nitelemesiz webhook referansi:** Gmail `sendTo` =
   `{{ $json.body.email }}` idi; ama Gmail webhook'tan DOLAYLI besleniyor (AI
   Agent'tan sonra), orada `$json` = AI Agent ciktisi (`{output}`), `body` yok ->
   `undefined.split` hatasi. Fix: `repair` trigger'a dogrudan bagli OLMAYAN
   node'larda deklare input referanslarini `$('<trigger>').first().json.body.<f>`
   olarak niteler. (Dogrudan bagli node'da `$json.body.<f>` kalir.)
   Testler: `test_template_field_gets_equals_prefix`,
   `test_non_trigger_fed_node_qualifies_webhook_reference`,
   `test_code_node_jscode_not_prefixed_with_equals`.

**SONUC — uctan uca BASARILI (execution 96, status=success):** Repair canli
workflow'a uygulandiktan sonra AI ciktisi gercek firma adiyla ("Acme Yazilim
A.S. olarak KOBI'lere...") uretildi ve Gmail dolu govdeyle gonderildi (label
SENT). Tek JSON yuzeyi + repair zinciri artik "firmalara teklif" senaryosunu
uctan uca dogru calistiriyor. Few-shot ornegi de `=` + nitelenmis referans
gosterecek sekilde guncellendi.

**Chat model `model` param sekli (2026-06-15, `IjahkWKFE9nhxnJa`):** Agent yeni
senaryoyu (adaylara geri donus) **bastan dogru** kurdu (ai_languageModel portu +
type, `=` ifadeler, nitelenmis refler) — yani tek-yuzey+repair canli teyit edildi.
Ama execution "Could not get parameter" verdi: `lmChatOpenAi` tv1.3 `model`'i
**resourceLocator** bekliyor (`{__rl,mode:list,value}`), agent ise duz string
`"gpt-4o-mini"` yaziyordu. Eski graph compiler `_build_chat_model` bunu uretirdi;
kompakt yuzeyde node'a-ozgu sekillendirme yoktu. Fix: `validation._normalize_chat_model_node`
(Gmail/Sheets normalizer'lari gibi) `@n8n/n8n-nodes-langchain.lmChat*` node'larinda
string `model`'i resourceLocator'a cevirir. Yamadan sonra execution 98 success,
kisisellestirilmis mail gonderildi. (NOT bir credential sorunu degildi.)

**Acik feature — n8n node credential yonetimi:** OpenAI Chat Model node'u n8n
icinde kendi `openAiApi` credential'ina ihtiyac duyuyor; bu, app'in workflow'u
KURMAK icin kullandigi LLM provider key'inden ayri. Su an Gmail/Sheets icin OAuth
broker var (ADR-0003) ama LLM/API-key node'lari icin tam broker yok.

**Tekil-asama koprusu (2026-06-16, uygulandi):** n8n public API credential
listelemeyi desteklemiyor (`GET /credentials` -> 405), ama `list_workflows` +
`get_workflow` calisiyor. `readiness._attach_existing_credential_if_available`:
bir node managed-olmayan bir credential'a (orn. `openAiApi`) ihtiyac duyup
node'da yoksa, kullanicinin **baska bir workflow'a zaten bagladigi** ayni tipteki
credential'i kesfedip (`_discover_existing_credential`) node'a baglar. Managed
Google tipleri (`gmailOAuth2`/`googleSheetsOAuth2`) haric (OAuth broker'a dokunmaz).
Canli dogrulandi: throwaway workflow'da `openAiApi` -> `nk5cJsBDTXOt7134`
("OpenAi account") otomatik baglandi. Testler: `test_readiness.py` (4). Boylece
agent-kurdugu AI workflow'lari elle credential baglamadan calisiyor.

**Hala bekleyen (tam cozum):** per-user container + kullanici credential saklama
gelince broker'a evrilecek (kullanicinin kendi sakladigi API key'ini kendi
container'ina enjekte). _(Not 2026-06-30: eski BYO `ProviderConnection` modeli
[[adr-0011-conduut-managed-tiered-models]] ile kaldirildi; bu pending kalem artik
per-user-container faza ait kullanici credential saklamaya bagli, kaldirilan BYO
koduna degil.)_ Secenekler: (A) credential broker'i API-key'lere genislet,
(B) app provider key'ini n8n'e enjekte et, (C) n8n OpenAI node yerine Conduut LLM
katmani. Bkz. [[issue-backlog]]; per-user container + credential saklama Claude
memory'sinde (`per-user-container-credentials`).

## Markdown tablo dark tema hover kontrastı (2026-07-13, çözüldü)

Chat içindeki agent Markdown tablolarında `th` ve hover satırı açık tema
renklerini sabit (`#F4F4F5` / `#FAFAFA`) kullanıyordu. Dark temada metin
`var(--foreground)` ile açık kaldığı için başlık ve hover satırındaki yazılar
kontrastını kaybediyordu. `apps/web/src/app/globals.css` içinde light ve dark
tema için `--markdown-table-header` / `--markdown-table-hover` değişkenleri
tanımlandı ve tablo kuralları bunlara bağlandı. Dark değerler koyu yüzeyler
kullandığı için açık metin başlıkta ve hover sırasında görünür kalıyor.
Canlı `localhost:3007` kontrolünde `.dark` altında hesaplanan değerler sırasıyla
`#18181b` ve `#27272a`; yüklenen CSS kuralları da bu değişkenleri kullanıyor.

## Mock Dashboard Areas

- Usage sayfasi mock data.
- Settings profile/security/preferences kaydetme aksiyonlari tam entegre degil.
- Layout sidebar bazi kullanici bilgilerini mock olarak gosteriyor.

## Stale Assistant Docs

✅ Cozuldu (2026-06-30, Faz 2): Copilot talimat dosyalari (root +
`.github/copilot-instructions.md`) silindi; `CLAUDE.md` ince pointer'a indirildi;
kanonik rehber artik root `AGENTS.md`. Kod yazarken kaynak kod + `AGENTS.md` +
bu vault esas alinir.

## Workflow Intent Engine Reverted — Stale .pyc Kalintisi

✅ Cozuldu/eskidi (2026-06-30, Faz 3): Asagidaki tarihsel kayit artik gecersiz.
`apps/agent/src/agent/workflow_intent/` klasoru (stale `.pyc` kalintisi dahil)
tamamen silindi. Ayrica o donemde "aktif yol" diye anilan `create_workflow_from_plan`
ve `spec_compiler.py` da kaldirildi; canli yol tek kompakt-JSON yuzeyi
(`create_workflow`/`update_workflow`) + `repair.py`
([[adr-0010-json-surface-repair-normalizer]]). Tarihsel baglam icin asagisi korunur.

2026-06-07: [[adr-0008-typed-workflow-intent-engine]] kararinin 2026-06-05'te
baslayan ilk implementasyon slice'i kullanici tarafindan geri alindi (birkac
gunluk ara sonrasi yarim is revert edildi). Sonuc:

- `apps/agent/src/agent/workflow_intent/` icinde kaynak `.py` dosyalari **yok**;
  yalnizca `__pycache__/*.pyc` bytecode kalintisi (schemas, profiles, renderer,
  service, evals, __init__) kaldi. Bu kod hicbir yerden import edilmiyor.
- `create_workflow_from_intent` tool'u kayitli degil; aktif yol
  `create_workflow_from_plan` (`spec_compiler.py`, WorkflowPlan compiler) ve
  desteklenen aksiyonlar `gmail.send`, `sheets.row.append`, `sheets.read_rows`,
  `core.filter` ile sinirli.
- Stale `__pycache__` klasoru kullanici onayiyla silinebilir; ayri temizlik
  task'i olarak ele alinmali. Engine'i tekrar kurmak gerekirse karar
  [[adr-0008-typed-workflow-intent-engine]] ve [[new-engine-plan]] notlarinda
  duruyor, ancak kaynak commit edilmedigi icin pratikte sifirdan yazim gerekir.

## n8n Registry Data Availability

`packages/n8n-registry/data/nodes.json` gitignore'da. Dosya yoksa registry node
bilgisi bos kalabilir, cunku modern n8n HTTP `/types/nodes.json` fallback'i
bilincli olarak skip ediliyor. 2026-05-15 kontrolunde lokal workspace'te dosya
mevcut, fakat yeni checkout veya container ortaminda yine uretilmesi gerekebilir.
Gerekirse:

```bash
python packages/n8n-registry/scripts/fetch_nodes.py
```

Ilgili notlar: [[current-state]], [[agent-service]], [[dashboard]],
[[issue-backlog]].
