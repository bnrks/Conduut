# Schema-Driven Service Credential Formu (n8n credentials.json) — Tasarım

Tarih: 2026-06-26
Durum: Onaylanan tasarım (spec) — implementasyon planı bekliyor
Branch: `feature/predefined-credentials` (predefined credential library üstüne devam)
İlgili: [[adr-0015-predefined-credential-library]], [[adr-0012-custom-http-credentials]],
[[n8n-registry]], [[agent-service]]

## Problem

ADR-0015 ile gelen **Service** credential formu, n8n credential şemasındaki tüm alanları
**düz, boş kutular** olarak döküyor. Örnek `anthropicApi`: kullanıcı `Apikey`, `Url`,
`Header`, `Headername`, `Headervalue` diye boş alanlar görüyor — hiçbiri default'lu değil,
zorunlu/opsiyonel ayrımı yok, `header` aslında bir boolean toggle ama text input olarak
çiziliyor, koşullu alanlar (`headerName`/`headerValue`) her zaman görünüyor.

n8n'in kendi formu ise: `API Key` (zorunlu), `Base URL` (default `https://api.anthropic.com`),
`Add Custom Header` (toggle, kapalı), açıldığında `Header Name`/`Header Value`, ve
`Allowed HTTP Request Domains` (dropdown, default "All").

Kök neden: şu an **public API'nin sade JSON-schema'sını** (`GET /credentials/schema/{type}`)
kullanıyoruz; bunda `displayOptions` (koşullu görünürlük), `options` (dropdown), `typeOptions.
password`, `default`, `placeholder`, `description` **yok**. n8n'in UI'ı bu zengin bilgiyi
kendi credential tanımlarından (`INodeProperties[]`) alıyor.

## Feasibility (doğrulandı)

n8n cache'inde `nodes.json`'un yanında **`credentials.json`** var
(`/home/node/.cache/n8n/public/types/credentials.json`, 415 tip, 601KB). Her tip için tam
tanım: `name`, `displayName`, `iconUrl`, `documentationUrl`, `properties[]`. Her property:
`displayName`, `name`, `type` (string/boolean/options/...), `typeOptions.password`, `required`,
`default`, `placeholder`, `description`, `options[]`, `displayOptions.show`. Yani n8n'in UI'ında
kullandığı **her şey** mevcut. Bu, projenin `nodes.json`'u çektiği mekanizmanın (docker cp) aynısı.

## Kullanıcı kararları (brainstorm)

- **Form sadakati:** Sadeleştirilmiş — zorunlu/temel alanlar önde + default'lar dolu; zorunlu
  olmayan/koşullu alanlar "Gelişmiş" panelde; toggle/dropdown/koşullu mantık yine çalışır.
- **Kapsam:** `credentials.json` hem **form alanları** hem **katalog** (gerçek `displayName` +
  `iconUrl` + daha iyi OAuth filtresi) için kullanılır; nodes.json humanize heuristiği predefined
  için emekli (fallback kalır).
- **Frontend:** ayrı `DynamicCredentialFields` bileşeni (mevcut HTTP `CredentialForm`/AuthMethod
  yolunu şişirmeden).

## Mimari

### 1. Veri — `credentials.json` n8n-registry'ye

- **Fetch script** `packages/n8n-registry/scripts/fetch_credentials.py` (parallel `fetch_nodes.py`):
  `docker cp conduut-n8n:/home/node/.cache/n8n/public/types/credentials.json
  packages/n8n-registry/data/credentials.json`. `data/credentials.json` gitignore'da (nodes.json gibi).
- **Model** (`n8n_registry/models.py`): yeni `CredentialTypeInfo` dataclass —
  `name`, `display_name`, `icon_url`, `documentation_url`, `properties: list[dict]` (ham n8n
  property'leri), `extends: list[str]`, `generic_auth: bool`, `is_oauth: bool`.
- **Loader** (`n8n_registry/loader.py`): `load_credentials_from_file(path) -> list[CredentialTypeInfo]`;
  `is_oauth` ve `generic_auth` yüklemede hesaplanır.
- **Registry** (`n8n_registry/registry.py`): startup'ta `credentials.json` da yüklenir
  (`initialize_from_n8n` + `load_from_files`); yeni metodlar:
  - `list_credential_catalog(query=None) -> list[dict]` — fillable (non-OAuth, non-genericAuth)
    tipler; her öğe `{type, label, icon_url}`; `displayName`/query ile filtreli, label'a göre sıralı.
  - `get_credential_definition(type) -> CredentialTypeInfo | None`.
  - credentials.json yoksa boş döner (offline/CI degrade — mevcut nodes.json deseni).

### 2. OAuth + generic ayıklama (registry içinde, yükleme zamanı)

- `is_oauth(definition)`: **isim** `/oauth/i` **VEYA** `extends` girdilerinden biri `/oauth/i`
  (zincir: `googleSheetsOAuth2Api → extends ["googleOAuth2Api"]`) **VEYA** property adlarında
  oauth imzası (`oauthTokenData`/`grantType`/`authUrl`/`accessTokenUrl`/`authQueryParameters`).
  (415 tipten ~100'ü OAuth; `extends` sinyali şart — bazı OAuth tipleri kendi property'sinde
  oauth alanı taşımaz.)
- `generic_auth`: definition'da `genericAuth: true` (httpHeaderAuth/Basic/Query/Custom/SSL...).
  Bunlar **Service kataloğundan çıkar** — Custom HTTP sekmesine aittir (ADR-0012).

### 3. Zengin alan modeli — `CredentialField` (schemas.py + TS)

Mevcut (`name`, `label`, `type`, `required`) + yeni opsiyonel alanlar:

| Alan | Anlam |
|------|-------|
| `default` | ön-doldurma değeri (string/bool) |
| `placeholder` | input placeholder |
| `description` | alan altı yardım metni |
| `advanced` | true ise "Gelişmiş" panelde |
| `options` | `[{label, value}]` — dropdown için (type="options") |
| `showWhen` | `{field: str, values: list}` — n8n `displayOptions.show`; alan ancak `field` değeri `values` içindeyse görünür |

`type` genişler: `text | password | json | number | boolean | options`.

**n8n property → CredentialField eşleme** (`credential_catalog.credential_fields_from_definition`):
- `displayName → label`, `name → name`, `default/placeholder/description` taşınır.
- `type`: `string`+`typeOptions.password=true → password`; `string → text`; `boolean → boolean`;
  `options → options` (+`options` map'i); `number → number`; `json → json`.
- `required → required`; **`required olmayan → advanced=true`** (sadeleştirme).
- `displayOptions.show` (tek anahtarlı) → `showWhen={field, values}`. (Çok-anahtarlı koşullar V1'de
  ilk anahtara indirgenir; nadirdir.)
- **Atlanan:** `type: "notice"` (sadece-gösterim bilgi alanı). `allowedHttpRequestDomains` +
  `allowedDomains` korunur ama advanced (n8n da gösteriyor).

### 4. Backend wiring

- `credential_catalog.build_catalog` → `registry.list_credential_catalog()` kullanır (label=displayName,
  icon_url; OAuth+generic ayıklanmış). nodes.json `list_credential_types` + humanize predefined için
  emekli; humanize yalnız credentials.json'da olmayan tip için fallback.
- Alanlar artık **registry'den senkron** gelir (HTTP yok): `credential_fields_from_definition(type)`.
  `fetch_credential_fields` (public-API) ve route'un n8n `get_credential_schema` çağrısı emekli.
- Route'lar:
  - `GET /credentials/catalog?q=` → `{catalog:[{type,label,icon_url}]}`.
  - `GET /credentials/catalog/{type}/schema` → `{credentialType, label, iconUrl, fields:[zengin CredentialField]}`. OAuth/generic tip istenirse 422.
- `add_service_credential_payload` + `readiness._credential_request_for_node` → zengin alanları kullanır;
  kart datasına `iconUrl` + zengin `fields` eklenir. (Secret yine yalnız n8n'de; default'lar secret değil.)

### 5. Frontend — `DynamicCredentialFields` (yeni)

`apps/web/src/components/credentials/dynamic-credential-fields.tsx` — `CredentialField[]` alır,
form state yönetir, submit'te `data` döner. Servis picker + chat predefined kartı bunu kullanır;
**HTTP Custom yolu mevcut `CredentialForm`/AuthMethod'da kalır.**

Davranış:
- `default`'ları başlangıç değeri yapar; zorunlu alanlara `*`.
- `type` render: `text`/`password` (maskeli) `Input`; `boolean` → toggle/switch; `options` → `select`;
  `json` → `Textarea`.
- `advanced=true` alanlar "Gelişmiş" expander'ı altında (mevcut desen).
- **Koşullu:** `showWhen` olan alan, kontrol alanının o anki değeri `values` içindeyse render edilir
  (ör. `header` toggle açık → `headerName`/`headerValue` görünür).
- `placeholder` + `description` gösterilir.
- Servis `iconUrl` form başlığında + picker satırında (yoksa mevcut KeyRound fallback).

`service-credential-picker.tsx` + `credential-request.tsx` (predefined kart) bu bileşene geçer.
`lib/credential-auth-methods.ts` `serviceMethodFromFields` predefined yolda artık kullanılmaz
(HTTP method modeli kalır). `CredentialField` TS tipi (chat + dashboard) zengin alanlarla genişler.
BFF `catalog/[type]/schema` route'u zaten proxy — değişmez.

## Modül sınırları

- `credential_catalog.py` — credentials.json definition → CredentialField eşleme + katalog; bağımlılık
  `registry` + `schemas`. (public-API/n8n_client bağımlılığı kalkar.)
- `n8n-registry` — credentials.json yükleme + OAuth/generic sınıflandırma; tek sorumluluk, test edilebilir.
- `DynamicCredentialFields` — tek sorumluluk: zengin alan listesini render + state; n8n/registry bilmez,
  yalnız `CredentialField[]` + `onSubmit`.

## Test Planı

Backend (pytest, TDD):
- `loader`: credentials.json parse → `CredentialTypeInfo`; `is_oauth` (slackOAuth2Api=true,
  googleSheetsOAuth2Api=true via extends, openAiApi=false), `generic_auth` (httpHeaderAuth=true).
- `registry.list_credential_catalog`: OAuth+generic dışlar, label=displayName, query filtre, sıralı.
- `credential_fields_from_definition("anthropicApi")` golden: `apiKey` required+password+essential;
  `url` default=`https://api.anthropic.com`+advanced; `header` boolean+advanced; `headerName`/`headerValue`
  `showWhen={field:"header", values:[true]}`+password(value); `notice` atlanır; `allowedHttpRequestDomains`
  options+default="all"+advanced.
- route: catalog (icon_url), schema (zengin fields), OAuth 422.
- Test fixture: küçük gömülü credentials.json örneği (anthropicApi + slackOAuth2Api + httpHeaderAuth);
  canlı n8n'e bağımlı değil.

Frontend: `pnpm lint` + `npx tsc --noEmit`; manuel — `anthropicApi` formu n8n'e benzemeli (API Key önde,
Base URL default'lu Gelişmiş'te, Add Custom Header toggle → Header Name/Value koşullu).

Canlı doğrulama: `fetch_credentials.py` çalıştır → agent restart → dashboard Service → "Anthropic" →
form n8n gibi; kaydet → n8n'de `anthropicApi` credential (url default dahil) oluşur.

## Kapsam dışı (V1)

- OAuth2 tipleri (ayıklanır; ileri broker işi ADR-0006/0003).
- İleri n8n `typeOptions` (multiline editor, expression editor, resourceLocator, fixedCollection) —
  düz alana indirgenir veya atlanır; nadir credential alanları.
- Çok-anahtarlı `displayOptions` (ilk anahtara indirgenir).
- credentials.json otomatik senkron (manuel script, nodes.json gibi).
- Custom HTTP sekmesi (ADR-0012 plain-language form) — değişmez.

## Açık riskler

- **Stale credentials.json:** n8n sürümü değişince alanlar eskir; `fetch_credentials.py` ile yenilenir
  (nodes.json ile aynı operasyonel borç).
- **typeOptions çeşitliliği:** 415 tip arasında alışılmadık alan tipleri olabilir; tanınmayan tip →
  güvenli `text` fallback (+ log), form yine çalışır.
- **showWhen kontrol alanı advanced ise:** kontrol (ör. `header` toggle) advanced panelde; koşullu
  alanlar da advanced'de görünür — tutarlı.
