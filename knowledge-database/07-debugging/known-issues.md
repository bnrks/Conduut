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

## Mock Dashboard Areas

- Usage sayfasi mock data.
- Settings profile/security/preferences kaydetme aksiyonlari tam entegre degil.
- Layout sidebar bazi kullanici bilgilerini mock olarak gosteriyor.

## Stale Assistant Docs

`.github/copilot-instructions.md` ve root `copilot-instructions.md` bazi eski
veya planlanan mimari bilgilerini iceriyor. Kod yazarken once kaynak kod,
manifestler, root `AGENTS.md` ve bu vault kontrol edilmeli.

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
