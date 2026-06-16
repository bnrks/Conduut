# Known Issues

Merkez: [[index]]

Bu not, repo icinde gorulen bilinen sorunlari ve dikkat noktalarini toplar.

Kullanicinin yeni fark ettigi ve henuz triage edilmemis sorun/bug notlari icin
ayri alan: [[issue-backlog]].

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

`apps/agent/src/store.py` provider API key'lerini Firestore alanlari olarak
kaydediyor. Bu MVP icin hizli cozum, production icin guvenlik riski.

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
gelince broker'a evrilecek (kullanicinin kendi `ProviderConnection` key'ini kendi
container'ina enjekte). Secenekler: (A) credential broker'i API-key'lere genislet,
(B) app provider key'ini n8n'e enjekte et, (C) n8n OpenAI node yerine Conduut LLM
katmani. Bkz. [[issue-backlog]], [[per-user-container-credentials]] (memory).

## Mock Dashboard Areas

- Usage sayfasi mock data.
- Settings profile/security/preferences kaydetme aksiyonlari tam entegre degil.
- Layout sidebar bazi kullanici bilgilerini mock olarak gosteriyor.

## Stale Assistant Docs

`.github/copilot-instructions.md` ve root `copilot-instructions.md` bazi eski
veya planlanan mimari bilgilerini iceriyor. Kod yazarken once kaynak kod,
manifestler, root `AGENTS.md` ve bu vault kontrol edilmeli.

## Workflow Intent Engine Reverted — Stale .pyc Kalintisi

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
