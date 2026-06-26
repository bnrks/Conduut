# Predefined Credential Library + Connections/Credentials Ayrımı — Tasarım

Tarih: 2026-06-26
Durum: Onaylanan tasarım (spec) — implementasyon planı bekliyor
İlgili: [[adr-0012-custom-http-credentials]], [[adr-0013-agent-managed-credentials]],
[[adr-0003-google-oauth-broker-mvp]], [[adr-0006-platform-capability-layer]]

## Problem

Conduut'un "Credentials" sistemi yalnızca **generic HTTP node auth** tiplerini
(Header / Basic / Query / Custom Auth) destekliyor; bunlar **host**'a göre eşleşip
yalnızca `n8n-nodes-base.httpRequest` node'larına bağlanıyor (ADR-0012). Ancak
n8n'in **hazır (predefined) credential tipleri** — en acil olarak AI node'larının
ihtiyaç duyduğu `openAiApi` — kütüphanede **birinci sınıf değil**:

- Dashboard "Add credential" yalnızca 4 generic HTTP tipini gösteriyor; `openAiApi`,
  `anthropicApi`, `slackApi`, `notionApi` gibi tipler eklenemiyor.
- Chat'te bir AI node `openAiApi` isteyince `readiness.py` bir kart çıkarabiliyor
  (alanları n8n'in `GET /credentials/schema/{type}` ucundan okuyarak), ama kaydedilen
  credential bir **kütüphaneye** girmiyor — tek "hafıza" kırılgan, tek-tenant'a bağlı
  cross-workflow reuse köprüsü (`readiness._discover_existing_credential`).
- `CustomCredential` modeli `host` zorunlu varsayıyor; predefined tipler host'la değil
  **credential-tipiyle** eşleşmeli.

Ayrıca kullanıcı **Connections** ile **Credentials** arasında net bir kavramsal ayrım
istiyor.

## Kavramsal Model (Connections vs Credentials)

Ayrım kriteri (kullanıcı kararı): Conduut'un servise **n8n dışında da doğrudan erişimi
var mı?**

- **Connections** — Conduut'un hem n8n'de hem de servisin kendisinde yetkisi olan OAuth
  entegrasyonları. Bugün Google (Gmail, Sheets): `direct_api_enabled` bayrağı +
  `platforms/actions.py` ile n8n'i bypass edip servise direkt erişim (ADR-0006).
  **Bu iş kapsamında DEĞİŞMEZ.**
- **Credentials** — secret'ın **yalnızca n8n içinde** kullanıldığı, Conduut'un servise
  doğrudan erişmediği her şey. `openAiApi` burada. Bu kategori genişletilecek.

Credentials iki alt-türden oluşur:

| Alt-tür | Eşleşme | Örnek | Durum |
|---------|---------|-------|-------|
| host-matched (generic HTTP) | URL host'u | httpHeaderAuth + `api.example.com` | Mevcut (ADR-0012) |
| type-matched (predefined) | credential tipi | `openAiApi`, `anthropicApi`, `slackApi` | **Yeni** |

## Kapsam (V1)

Dahil:
- n8n'in **statik-alanla doldurulabilen** (fillable) hazır credential tipleri.
- Katalog **dinamik**: node registry'den tüm referans edilen credential tipleri
  çıkarılır, aranabilir liste; alanlar n8n şemasından canlı gelir.
- Type-matched eşleşme + onay-önce / tekil-otomatik bağlama.
- Hem dashboard'dan proaktif ekleme hem chat-içi (reaktif kart + proaktif tool).

Kapsam dışı (non-goals):
- **OAuth2 tabanlı** predefined tipler (`*OAuth2Api`): consent akışı public API'den
  sürülemez. Katalogdan ayıklanır; gerekirse listede "Connections — yakında" notuyla
  pasif gösterilir. İleride Connections broker track'inde ele alınır.
- Yeni Connections broker provider'ı (Slack/Notion OAuth vb.).
- Secret rotation / secret geri-okuma (n8n write-only kalır).
- `knowledge-database` migrasyonu / eski `workflow_credentials` koleksiyonu (zaten
  deprecate).

## Mimari (Yaklaşım A — Birleşik kütüphane)

Mevcut `CustomCredential` / `users/{uid}/credentials` koleksiyonu ve `/credentials`
route'ları **genelleştirilir**; tek kütüphane hem host-matched hem type-matched
credential'ları tutar. Mevcut draft/finalize (ADR-0013) ve attach altyapısı yeniden
kullanılır.

### 1. Veri modeli — `store.CustomCredential`

- Yeni alan: `match_kind: Literal["host", "type"]` (varsayılan `"host"` → geriye uyumlu;
  mevcut kayıtlar okunduğunda host varsayılır).
- `host` opsiyonel kalır (type-matched'de boş string).
- `credential_type` zaten n8n tipini tutuyor (`openAiApi`).
- `label` dostane ad (örn. "OpenAI").
- `store.save_custom_credential(...)` imzasına `match_kind` eklenir (varsayılan "host").
- Firestore migrasyonu yok; `match_kind` yokken host varsayılır.

### 2. Katalog modülü — `agent/credential_catalog.py` (yeni)

Tek sorumluluk: n8n'in hazır credential tiplerini keşfet, sınıflandır, dostane sun.

- `registry.list_credential_types()` (registry'e yeni metod): tüm `NodeInfo.credentials`
  taranır → `{type: {label, used_by_nodes, fillable}}`. Tip-başına dostane etiket türetimi:
  - öncelik: tipi kullanan node'un `display_name`'i (örn. `openAiApi` → "OpenAI" node'u);
  - fallback: tip adından humanize (`openAiApi` → "OpenAI"; `xApi`/`xOAuth2Api` ekleri
    temizlenir).
- **OAuth ayıklama** (`is_fillable_credential_type`): heuristik —
  - tip adında `oauth` geçiyorsa fillable=False;
  - şema alanlarında OAuth imzası (`oauthTokenData`, `grantType`, `authUrl`,
    `accessTokenUrl`) varsa fillable=False.
  - Yalnızca fillable tipler dashboard'da "eklenebilir" görünür.
- `credential_catalog(query: str | None)` → fillable tiplerin aranabilir listesi
  `[{type, label, fillable}]`.
- Alan şeması **on-demand**: `n8n_client.get_credential_schema(type)` (cache'li, mevcut
  `readiness._fields_from_schema` ile parse). Liste hafif (tip+label); alanlar tip
  seçilince gelir. Cache: süreç-içi basit dict (host auth cache deseni gibi; TTL gerekmez
  çünkü şema değişmez, ama registry reload'da temizlenir).

### 3. Backend — route & store

`routes/credentials.py` genişletilir:

- `GET /credentials/catalog?q=<query>` → fillable predefined tip listesi (OAuth ayıklanmış).
- `GET /credentials/catalog/{type}/schema` → o tipin alanları (`CredentialField[]`).
- `POST /credentials` genelleştirilir: yeni opsiyonel gövde alanları `match_kind`
  ("host"|"type", varsayılan mevcut davranışı koruyacak şekilde türetilir) ve type-matched
  için host zorunlu DEĞİL. Mevcut host-zorunluluğu yalnızca generic HTTP (host) yolunda
  kalır.
- `DELETE`, `GET /credentials`, `/finalize` aynen çalışır; liste payload'una `match_kind`
  eklenir.
- `store.match_credentials_by_type(credential_type, credentials)` (yeni helper,
  `credential_types.py` veya `credential_catalog.py` içinde): aynı tipte, status="ready"
  credential'ları döndürür.

### 4. Readiness / attach — type-matched akış

`readiness.analyze_workflow_readiness_payload`:

- Predefined (non-HTTP, non-managed-Google) credential tipi için artık kütüphaneyi
  **tipe göre** kontrol eder (mevcut cross-workflow reuse köprüsünden ÖNCE):
  - **Tam 1** ready eşleşme → `reuse_candidates`'a eklenir (chat'te onay-önce attach).
  - **0** → mevcut `_credential_request_for_node` kartı (alanlar n8n şemasından); kart
    submit'i `/api/credentials`'a `match_kind="type"` ile yazar → kütüphaneye girer.
  - **>1** → `reuse_candidates`'a hepsi eklenir; agent hangisi diye sorar (tekil değil).
- `attach_unambiguous_reuse_candidates`: tip-eşleşmeli tekil adayları da kapsar (dashboard
  Run / batch'te tek eşleşme otomatik bağlanır; host-matched ile aynı mantık).
- Cross-workflow reuse köprüsü (`_discover_existing_credential`): kütüphane eşleşmesi
  öncelikli; köprü **fallback** olarak kalır (log'lu), zamanla deprecate.

`reuse_candidates` payload'una `matchKind` eklenir ki attach tarafı host mı tip mi
ayırt etsin (generic_auth_type yalnızca host/HTTP için gönderilir; predefined tipte
`attach_credential_to_workflow` `generic_auth_type=None` ile çağrılır, node'un
`credentials[<type>]` alanı yazılır).

### 5. Agent tool & prompt

- `list_credentials` tool'u: mevcut `url` parametresine ek `credential_type` parametresi;
  type eşleşme bayrağı (`matches_type`) döner.
- **Yeni proaktif tool `add_service_credential(service_or_type)`**: kullanıcı "OpenAI
  anahtarımı ekle" derse — katalogdan tipi bulur (isim/etiket eşleşmesi), o tipin
  alanlarını içeren bir `credential_request` kartı döndürür (host'suz, `match_kind="type"`,
  workflow_id/node_name opsiyonel). Reaktif kart yapısının proaktif kardeşi.
- `tools/factory.py`: yeni tool kaydı + create/update sonucu `credential_suggestions`
  type-matched adayları da içerir.
- `tools/prompt.py`: AI/servis node'ları için kural — önce kütüphaneyi tipe göre kontrol
  et (`list_credentials(credential_type=...)`) → onay-önce bağla (`attach_credential`);
  yoksa kart. Secret'ı asla chat'e yazdırma; kullanıcıya karttan ya da Dashboard →
  Credentials'tan girmesini söyle.

### 6. Frontend — Dashboard UX

`/dashboard/credentials` "Add credential" akışı iki moda ayrılır:

- **"Servis seç" (yeni, varsayılan)**: aranabilir n8n servis listesi (`GET
  /credentials/catalog?q=`) → tip seç → `GET /credentials/catalog/{type}/schema` ile
  dinamik alanlar render → kaydet (host'suz, `match_kind="type"`).
- **"Generic HTTP" (mevcut)**: host + plain-language auth method (`AUTH_METHODS`,
  `credential-form.tsx`). `requireHost` korunur.

Liste kartı:
- type-matched → servis adı/ikon (host yerine `friendlyTypeLabel`); host alanı gizli.
- host-matched → host satırı (mevcut).
- Draft "Tamamlanmamış" / "Tamamla" akışı (ADR-0013) korunur.

OAuth tipleri: katalog listesinde görünmez (fillable=False). (Opsiyonel iyileştirme:
ayrı pasif "OAuth tabanlı — Connections, yakında" bölümü; V1 için zorunlu değil.)

BFF route'ları (`apps/web/src/app/api/credentials/...`): `catalog` ve `catalog/[type]/
schema` proxy'leri eklenir.

### 7. Chat kartı (reaktif)

`components/credentials/credential-request.tsx`: type-matched kartta host alanı gizlenir;
alanlar backend'den gelen `fields`'tan render edilir (zaten generic mekanizma var). Submit
`/api/credentials`'a `match_kind="type"` gönderir.

## Modül sınırları (isolation)

- `credential_catalog.py` — tek sorumluluk: tip keşfi + sınıflandırma + dostane etiket.
  Bağımlılık: `registry`, `n8n_client.get_credential_schema`. Test edilebilir (registry
  fixture + fake schema).
- `store.CustomCredential` — `match_kind` ile polimorfik ama tek koleksiyon; CRUD aynı.
- `readiness.py` — type-matched dalı host-matched dalın yanına eklenir; ortak attach yolu.
- Frontend `credential-form.tsx` paylaşılan kalır; "servis seç" modu yeni bir alt-bileşen
  (`service-credential-picker.tsx`) olarak eklenir, forma method besler.

## Test Planı

Backend (pytest, TDD):
- `credential_catalog`: registry fixture'dan tip enumerate; OAuth ayıklama (`slackOAuth2Api`
  ayıklanır, `openAiApi` kalır); dostane etiket türetimi; query filtreleme.
- `match_credentials_by_type`: tip eşleşmesi, status="ready" filtresi.
- `routes/credentials`: `GET /catalog`, `GET /catalog/{type}/schema`, `POST` type-matched
  (host'suz 201), host-matched host-zorunluluğu korunur.
- `readiness`: type-matched 0/1/>1 senaryoları (kart / reuse_candidate / çoklu); köprü
  fallback'i sıralaması.
- `add_service_credential` tool payload'u.

Frontend: `tsc` + `eslint` temiz; manuel akış.

Canlı doğrulama (n8n + agent + web açık):
- Dashboard'dan "OpenAI" credential ekle (host'suz) → kaydet → n8n'de credential oluşur.
- Chat: "AI ile özet çıkarıp X yapan workflow kur" → AI node `openAiApi` ister →
  readiness tipe göre kütüphaneyi bulur → onay-önce attach → çalışır.
- Eşleşme yokken kart çıkar; doldur → kütüphaneye girer → ikinci workflow'da reuse.

## Açık Riskler / Notlar

- **OAuth detection heuristik**: bazı tipler isimde "oauth" geçmeden OAuth olabilir; şema-
  alan imzası ikinci savunma. Yanlış-pozitif (fillable tipi yanlışlıkla ayıklamak) →
  kullanıcı tipi göremez; yanlış-negatif (OAuth tipi fillable görünmek) → yarım credential
  riski. İmza listesi konservatif tutulacak; canlı testte birkaç popüler tiple doğrulanacak.
- **Dostane etiket**: çoklu node aynı tipi kullanabilir; ilk/en alakalı node display_name
  seçilir, değilse humanize fallback.
- **Schema cache**: registry reload'da temizlenmeli (startup'ta dolu).
- Single-tenant shared n8n MVP'sinde credential herkesçe görünür değildir (metadata
  Firestore'da per-uid); ama cross-workflow reuse köprüsü hâlâ tek n8n'i tarar (mevcut
  davranış, bu işte değişmez, sadece önceliği düşer).
