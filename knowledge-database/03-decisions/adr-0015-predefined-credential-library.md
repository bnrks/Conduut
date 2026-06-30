# ADR 0015: Predefined Credential Library (n8n hazir tipler)

Merkez: [[index]]

## Durum

Accepted - 2026-06-26.

## Baglam

ADR-0012 ile kurulan credential kutuphanesi yalnizca generic HTTP auth tiplerini
(`httpHeaderAuth`, `httpBasicAuth`, `httpQueryAuth`, `httpCustomAuth`) destekliyordu.
n8n'in `predefinedCredentialType` mekanizmasi ise `openAiApi`, `anthropicApi`,
`githubApi` gibi yuzlerce hazir tipten olusuyor; her tip n8n'in kendi sema
validasyonunu ve n8n node'larina **dogrudan** baglaniyor. Bu tipler HTTP Request
node'unun `genericCredentialType` yolu disinda calisir: bir `openAiAgent` node'u
`credentials.openAiApi` bekler, `genericAuthType` alamaz.

Eksik senaryo: kullanici chat'te "OpenAI ile bir workflow kur" dediginde agent
`openAiApi` tipinden bir credential gerektigini anlayabiliyor ama bunu Conduut
kutuphanesine kaydedecek yol yoktu. Sonuc: readiness karti her seferinde kullanicidan
ayni secret'i yeniden istiyordu; cross-workflow reuse olmuyordu.

Ek karmasiklik: predefined tipler arasindan **OAuth2 tabanli olanlari** (Google,
GitHub OAuth, Slack OAuth vb.) ayiklamak gerekiyor — bunlar kullanicidan key/secret
istemez, consent akisi gerektiriyor ve ADR-0003 / ADR-0006 kapsaminda ayri islem
goruyorlar.

## Karar

ADR-0012'nin birlesik `users/{uid}/credentials` koleksiyonu **iki alt-tur** icerir:

| match_kind | Hangi credential'lar | Eslestirme ekseni |
|---|---|---|
| `"host"` | Generic HTTP auth (ADR-0012 yolu) | URL'deki hostname |
| `"type"` | Predefined n8n tipleri (bu ADR) | n8n `credential_type` adinin tam eslesmesi |

`store.CustomCredential` modeline `match_kind: "host" | "type"` alani eklendi;
varsayilan `"host"` — geri uyumlu, mevcut veriye migrasyon yok.

**Katalog modulu (`agent/credential_catalog.py`):**

- `registry.list_credential_types()` n8n'in aktif registry'sindeki tum credential
  tiplerini numaralandirir (startup'ta yuklenir).
- `build_catalog(raw_types, query=None)` OAuth2 tiplerini iki kuralla ayiklar:
  - `is_oauth_type_name(name)` — tip adinda "oauth" / "OAuth" bulunuyorsa OAuth'tur.
  - `schema_is_oauth(schema)` — sema alanlarinda `oauthTokenData` / `oauthRedirectUrl`
    / `callbackUrls` bulunuyorsa OAuth'tur.
  Her tip icin kullanici dostu etiket: ilgili node'larin en kisa display adindan
  turetilir, yoksa tip adi insancil bicime cevirilir (`friendly_label`).
- `match_credentials_by_type(credential_type, credentials)` — type-matched
  credential'lari tip adindan bulur.
- `parse_schema_fields(schema)` — n8n sema'sindan doldurulabilir alanlari cikarir
  (onceden `readiness.py`'deydi, buraya tasindi; `readiness` alias kullanir).
- `fetch_credential_fields(credential_type)` — n8n `GET /credentials/schema/{type}`
  cagirip alanlari dogrudan getirir.

**Route'lar (`routes/credentials.py`):**

- `GET /credentials/catalog?q=` — filtrelenmis katalog (arama destekli).
- `GET /credentials/catalog/{type}/schema` — belirli bir predefined tipin alanlarini
  getirir; OAuth tipi istenirshe **422** dondurur (isim heuristigi + sema imzasi).
- `POST /credentials` — `match_kind` alir veya tipin `httpHeaderAuth`/`httpBasicAuth`/
  `httpQueryAuth`/`httpCustomAuth` olup olmadigina gore turetir. Type-matched
  credential icin host zorunlu degil; baglanirken `generic_auth_type=None` kullanilir
  (n8n dogrudan `credentials.{type}` wiring'i yapar).
- `GET /credentials` listesi artik `match_kind` alani icerir.

**Readiness (`tools/readiness.py`):**

Predefined (non-HTTP, non-managed) tiplerde readiness artik cross-workflow legacy
koprusunden (onceki `_discover_existing_credential`) **once** kutuphanede type-matched
bakiyor. `reuse_candidates` artik `matchKind: "host" | "type"` bilgisi tasiyor.
Boylece ayni tip icin once kendi kutuphanesi kontrol ediliyor.

**Agent araclari:**

- `list_credentials(credential_type=...)` type-matched bayragini dondurur.
- Yeni `add_service_credential(service_or_type, ...)` tool'u: kullanicidan secret
  isteyip kutuphaneye `match_kind="type"` ile kaydeden bir **servis credential karti**
  gosterir. Secret hicbir zaman agent/LLM'den gecmez.
- Prompt kurali eklendi: agent bir predefined credential tipi tespit edince once
  `list_credentials(credential_type=...)` cagirip var mi kontrol eder; yoksa
  `add_service_credential` ile proaktif olarak ekletir.

**Frontend (`apps/web`):**

`/dashboard/credentials` sayfasi iki mod kazandi:

- **Servis secici modu:** aranabilir katalog (`service-credential-picker.tsx`) →
  secilen tip icin dinamik alanlar (n8n schemasinden) → kaydet.
- **Custom HTTP modu:** ADR-0012 yolu (degismedi).

`credential-auth-methods.ts` dosyasina `serviceMethodFromFields(credentialType, label,
fields)` eklendi: n8n alanlarina gore duz-dil etiket olusturur. Chat karti
(`credential-request.tsx`) artik `match_kind` gonderiyor.

## Sonuclar

- Secret her iki modda da yalnizca n8n credential store'unda yasayor; agent/LLM/log
  katmanlarindan gecmiyor.
- `match_kind="type"` credential'lari cross-workflow reuse'a katilir: ayni tip icin
  ikinci bir workflow kurulunca agent oneri getirir.
- OAuth2 predefined tipler (Google, Slack OAuth, GitHub OAuth) dashboardda **gorunmez**;
  o tipler ADR-0003 / ADR-0006 kapsaminda kalir (Connections = servise n8n-disi
  dogrudan erisim, degismez).
- Per-user container getirildiginde (ADR-0001 -> kontrol katmani) bu metadata->
  credential haritas dogal olarak per-container store'a tasinir.
- Shared n8n MVP'de type-matched credential tum kullanicilarin n8n'inde yaratilir;
  per-user container oncesinde Firestore uid izolasyonu gecerli.
- Tam test paketi: 336 backend birim testi gecti; frontend lint + tsc temiz.
  Canli uc-tan-uca dogrulama BEKLIYOR (manuel, task-12 Step 4).

## Kapsam Disi (V1)

- OAuth2 tabanli predefined tipler (consent akisi gerektirenler) — bu ADR disinda.
- Gizli-deger rotasyonu / yenileme.
- Yeni Connections (ADR-0006) broker saglayicisi.
- `httpHeaderAuth` vs. predefined karar logigi degisikligi — ADR-0012 yolu aynen
  devam ediyor.

## Güncelleme (2026-06-26b) — Şema-güdümlü form + ikon proxy

**Bağlam (Faz 2, branch `feature/predefined-credentials`):** Faz 1 katalog + type-matched
reuse mekanizmasını kurmuştu. Faz 2, credential formunu **n8n'in kendi `credentials.json`
şemasından** türeterek n8n formunu birebir yansıtacak şekilde genişletti.

**Veri kaynağı:** `credentials.json` (415 tip, tam `INodeProperties`) `n8n-registry` paketine
yükleniyor (`scripts/fetch_credentials.py` ile docker cp; `data/credentials.json` gitignored —
Docker build öncesi `fetch_credentials.py` çalıştırılmalı, `nodes.json` ile aynı sözleşme).
Yeni `CredentialTypeInfo` modeli (`name`, `display_name`, `icon_url`, `properties`, `extends`,
`generic_auth`, `is_oauth`); `registry.list_credential_catalog(query)` + `registry.get_credential_definition(type)`.

**OAuth/generic ayıklama:** Yükleme sırasında hesaplanır: `is_oauth` = ad `/oauth/i` VEYA
`extends` girişi `/oauth/i` VEYA oauth özellik imzası; `generic_auth` = n8n `genericAuth`
(httpHeaderAuth vb. — Özel HTTP sekmesine ait, Servis katalogundan dışlanır).

**Zengin alan modeli:** `CredentialField` `default`/`placeholder`/`description`/`advanced`/
`options`/`showWhen` kazandı; `credential_fields_from_definition(definition)` n8n özelliklerini
alanlara eşler (şifre→typeOptions, boolean→toggle, options→dropdown, `displayOptions.show`
tek-anahtar→`showWhen`, `notice`/`hidden` atlanır, zorunlu-olmayan→advanced). Katalog + tip-başına
alanlar artık registry'den sunuluyor. Eski `build_catalog`/`friendly_label`/`list_credential_types`/
`fetch_credential_fields` + `credential_catalog.py`→`n8n_client` bağımlılığı kaldırıldı.

**Frontend:** `components/credentials/dynamic-credential-fields.tsx` (**yeni**): defaults ön-dolu,
zorunlu `*`, boolean toggle, options dropdown, koşullu `showWhen` görünürlüğü, zorunlu-olmayan
alanlar "Gelişmiş seçenekler" altında. Submit daraltılmış-gelişmiş alanların defaultlarını içerir
(ör. Base URL), n8n ile uyumlu; yalnızca `showWhen`-gizli alanlar düşürülür.

**Servis ikonları:** `GET /credentials/icon?path=icons/...` (PUBLIC, SSRF korumalı: `icons/`
öneki + `..` yasağı) agent'ta n8n ikon SVG'lerini proxy'liyor; web BFF binary route önünde.
`<img>` bearer token gönderemeyeceğinden public. `iconUrl` `{light,dark}` nesnesi olabilir —
loader her ikisini de işliyor.

**Test:** Agent suite 345 passed (5 bilinen Windows-tmp hatası), n8n-registry suite yeşil,
frontend lint+tsc temiz, ruff temiz. Tüm-branch incelemesi (opus): Critical/Important yok,
merge hazır. Canlı uçtan-uca doğrulama BEKLIYOR (manuel). Spec/plan: `.superpowers/sdd/`
(gitignored, yerel).

## Ilgili

- [[adr-0012-custom-http-credentials]] - birlesik kutuphane ve `match_kind="host"` alt-tur
  temeli.
- [[adr-0013-agent-managed-credentials]] - Gemini grounding ile taslak credential
  ve finalize akisi; ayni `users/{uid}/credentials` koleksiyonu.
- [[adr-0003-google-oauth-broker-mvp]] - Connections = n8n-disi servis erisimi;
  bu ADR'in kapsam disi kisildiginin referansi.
- [[adr-0006-platform-capability-layer]] - platform capability katmani; managed
  servislerin (Gmail/Sheets) ayrimi.
- [[agent-service]] - agent mimarisi ve tool listesi.
- [[known-issues]] - canli dogrulama bekleyen senaryolar.
