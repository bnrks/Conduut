# Agent-Yönetimli Credential (araştır + taslak oluştur + Conduut-farkındalığı) — Tasarım

Tarih: 2026-06-21
Durum: Onay bekliyor (brainstorming çıktısı)
İlgili: [[adr-0012-custom-http-credentials]], `apps/agent/src/agent/credential_types.py`,
`apps/agent/src/agent/tools/credentials.py`, `apps/agent/src/store.py`

## Bağlam / Problem

ADR-0012 ile kullanıcılar custom (HTTP) credential'ları Conduut'ta kaydedip
host'a göre eşleştirip kullanabiliyor. Ama **credential'ın nasıl yapılandırılması
gerektiğini** (hangi auth tipi, hangi header/param adı, prefix var mı) hâlâ
kullanıcı biliyor/seçiyor. Hedef: bunu **agent bilsin ve yönetsin** —

1. Agent, bir API'nin nasıl auth istediğini **araştırabilsin** (her API farklı).
2. Agent, secret-olmayan alanları doldurulmuş bir **credential oluşturabilsin**;
   kullanıcının sağlaması gereken alanları (API key, secret) **boş bıraksın**;
   kullanıcı bunları **sonra** doldursun.
3. Agent, bu adımların Conduut'a özgü **farkındalığına** sahip olsun — kullanıcıya
   "nasıl yapacağını" anlatabilsin.

Ön doğrulama (spike) yapıldı: Pydantic AI 1.88.0 `WebSearchTool` builtin'i var;
**decoupled Gemini grounding** ile araştırma provider-bağımsız çalışıyor (Claude
ana model, Gemini araştırır — kanıtlandı). Token maliyeti Gemini grounding'de
çok düşük (~75 input token; Anthropic web_search'te ~16k input).

## Kararlar (brainstorming)

- **Tetikleyici:** hem **reaktif** (workflow kurarken eksik-credential'lı HTTP
  node'a denk gelince) hem **proaktif** ("X API'sine bağlan").
- **Reaktif yol agent-tool ile** (readiness otomatik araştırma tetiklemez —
  maliyet kontrolü + araştırma agent'ın muhakemesinde kalsın).
- **Taslak kalıcı:** secret'sız credential bir "draft" olarak Firestore'da durur;
  kullanıcı chat'te **şimdi** ya da dashboard'da **sonra** tamamlar.
- **Taslakta n8n credential YOK:** secret gelene kadar yalnız Firestore metadata;
  finalize'da n8n credential oluşturulur (junk credential olmaz).
- **Otomatik + cache'li araştırma:** agent bilmediği API'de kendiliğinden araştırır;
  sonuç **paylaşımlı** global cache'e yazılır (API başına bir kez aranır).
- **Research provider:** sabit, ucuz **Gemini (Flash) + grounding**, tier modelinden
  bağımsız (decoupled). Anthropic/OpenAI değil (token maliyeti yüksek).
- **Cache kapsamı:** paylaşımlı (tüm kullanıcılar). Auth şeması halka açık, hassas
  değil → güvenli + en ucuz.

## Mimari & uçtan uca akış

### Reaktif (workflow kurarken)
1. Agent HTTP node'u kurar (`authentication=genericCredentialType`); host için
   kayıtlı **ready** credential / **draft** yok.
2. Agent `prepare_api_credential(url, workflow_id, node_name)` tool'unu çağırır.
3. Tool: host normalize → cache bak → miss ise Gemini grounding araştır → cache'e
   yaz → güven yeterliyse secret'sız **draft** oluştur (`pending_workflow_id`/
   `pending_node_name` ile) → "sadece secret gir" kartı emit et.
4. Agent kullanıcıya Conduut akışını anlatır (secret'ı bana yazma; karttan ya da
   Dashboard → Credentials'tan gir).
5. Kullanıcı secret'ı girer (chat ŞİMDİ veya dashboard SONRA) → finalize → n8n
   credential oluşur + bekleyen node'a bağlanır → workflow çalışır.

### Proaktif ("Stripe'a bağlan")
Aynı `prepare_api_credential(api_or_url)` (workflow bağlamı yok) → taslak +
kart; taslak kütüphanede bekler, sonra herhangi bir workflow'da kullanılır.

## Bileşenler

### 1. Araştırma motoru — `apps/agent/src/agent/research.py` (yeni)
- `AuthResearchResult` (Pydantic): `scheme` (header|query|basic|custom|none),
  `field_name`, `value_prefix`, `secret_fields: list[str]`, `summary`,
  `source_url`, `confidence` (high|medium|low).
- Modül-seviyesi **decoupled Gemini grounding agent**: `provider_factory.build_model`
  ile sabit Gemini Flash modeli + `builtin_tools=[WebSearchTool()]` +
  `output_type=AuthResearchResult`. Tier/router'dan **bağımsız**.
- `async def research_api_auth(host_or_api: str) -> AuthResearchResult`:
  cache oku → hit ise dön → miss ise grounding agent çalıştır → cache'e yaz → dön.
- `scheme → credential_type` map: header→`httpHeaderAuth`, query→`httpQueryAuth`,
  basic→`httpBasicAuth`, custom→`httpCustomAuth`, none→`""` (auth yok).
- Model id `config.py`'de ayarlanır (`research_model`, default ucuz Gemini Flash;
  geçersizse `gemini-3.1-pro-preview` fallback — id canlı `/models` ile doğrulanır).

### 2. Paylaşımlı cache — `store.py` (global koleksiyon)
- Koleksiyon: kök `api_auth_cache/{host}` (kullanıcı-üstü; doc id = normalize host).
- İçerik: `host, scheme, credential_type, field_name, value_prefix, secret_fields,
  summary, source_url, confidence, researched_at, model`. **Secret yok.**
- `store.get_api_auth_cache(host) -> ApiAuthCache | None`,
  `store.save_api_auth_cache(host, result)`, `store.delete_api_auth_cache(host)`
  (force-refresh).
- **TTL:** `researched_at` 60 günden eskiyse yeniden araştır. Yalnız high/medium
  güven cache'lenir; low → cache'leme.

### 3. Taslak credential modeli — `store.py` `CustomCredential` genişler
Yeni alanlar:
- `status`: `"draft"` | `"ready"` (varsayılan eski kayıtlar `"ready"`).
- `auth_config`: secret-olmayan yapı `{method, field_name, value_prefix}`
  (n8n `data`'yı finalize'da kurmak için).
- `secret_fields: list[str]` — kullanıcının dolduracağı alanlar.
- `source_url`, `confidence` — şeffaflık (araştırma kaynağı).
- `pending_workflow_id`, `pending_node_name` — finalize'da bağlanacak node (ops).
- `n8n_credential_id` taslakta **boş**; finalize'da set.

CRUD: `save_draft_credential(...)`, `get_custom_credential` (mevcut, status okur),
`finalize_draft_credential(user_id, draft_id, *, n8n_credential_id, n8n_credential_name)`,
`list_custom_credentials` (mevcut; draft+ready döner).

### 4. Agent tool'ları — `apps/agent/src/agent/tools/`
- **Yeni `prepare_api_credential(ctx, api_or_url, workflow_id=None, node_name=None)`**
  (factory.py kaydı; mantık `tools/credentials.py`'de
  `prepare_api_credential_payload`):
  1. `host = normalize_host`. Var olan **ready** credential host-eşleşirse →
     "zaten var" (mevcut reuse akışına bırak). Var olan **draft** varsa →
     "taslak bekliyor, secret gir" kartını tekrar göster.
  2. `research_api_auth(host)` çağır.
  3. `confidence == low` veya `scheme == none-belirsiz` → **draft oluşturma**;
     mevcut düz-dil manuel kartına düş (uydurma yok).
  4. Draft oluştur (`save_draft_credential`), `credential_request` kartını
     **secret-only + draftId + provenance** ile emit et.
  5. Sonuç + Conduut-farkındalık talimatı döndür (agent kullanıcıya anlatır).
- `prompt.py`: HTTP API'sine credential gerektiğinde ve kayıtlı yoksa
  `prepare_api_credential` çağır; kullanıcıya secret'ı **kart/dashboard'dan**
  girmesini söyle, **anahtarı chat'e yazdırma**, secret'ı agent görmez.

### 5. Finalize yüzeyleri (kalıcı taslak)
- **Backend:** `POST /api/credentials/{draft_id}/finalize` (`routes/credentials.py`)
  → draft yükle (ownership) → `auth_config`+secret'tan n8n `data` kur →
  `n8n_client.create_credential` → `store.finalize_draft_credential` (status=ready)
  → `pending_workflow_id`/`node_name` varsa attach (generic auth wiring) → dön.
- **Chat kartı:** `credential-request.tsx` + paylaşılan `CredentialForm`; draft
  kartı yalnız secret alan(lar)ını sorar (tip/host/field read-only gösterilir),
  `draftId` ile finalize endpoint'ine gider. Araştırma kaynağı küçük not olarak.
- **Dashboard `/dashboard/credentials`:** taslaklar **"Tamamlanmamış"** rozetiyle
  + **"Tamamla"** butonu → secret formu → finalize. Mevcut liste + form genişler.

**BYO tenancy uygulamasi (2026-08-03):** finalize oncesi draft'in authenticated
`user_id` ile birlikte hedef `instance_id` ownership'i dogrulanir.
`n8n_client.create_credential` global instance'a degil resolver'in sectigi
customer-owned n8n'e gider; sonuc `n8n_credential_id` yalniz ayni
`instance_id` icinde kullanilir. Target baglantisi yoksa veya draft baska
instance'a aitse finalize fail-closed davranir; bu ownership kontrolu ve
instance-scoped client V1 kodunda uygulanmistir. Bkz. [[customer-owned-n8n]] ve
[[adr-0022-customer-owned-n8n]].

### 6. Conduut-farkındalığı (part 3)
Büyük ölçüde prompt + taslak kartının/mesajının dili:
- Agent: "X için **Header Auth** credential'ı hazırladım (kaynak: …). API anahtarını
  **şu karta** gir ya da **Dashboard → Credentials → Tamamla**'dan gir. Anahtarı
  bana yazma; ben secret'ları görmem."
- `prompt.py`'ye Conduut credential/connection akışı kuralları (taslak → secret →
  finalize → attach → run) eklenir.

## Hata yönetimi / fallback
- Araştırma "auth gerekmiyor" (public API) → credential yok, node auth'suz.
- Araştırma hatası/timeout/düşük güven → düz-dil manuel kart (ADR-0012 mevcut akış).
- Gemini grounding hatası → log + fallback; akış kırılmaz.
- Cache'li cevap yanlışsa (auth'ta patlarsa) → force-refresh ile yeniden araştır.
- Maliyet: shared cache + sadece-gerektiğinde + ucuz Flash → API başına ~bir kez.

## Test (TDD)
- `research_api_auth`: structured output parse, cache hit/miss, TTL bayatlama,
  düşük-güven fallback, scheme→credential_type map (Gemini mock).
- `store`: `api_auth_cache` CRUD; draft save/finalize + status geçişi.
- `prepare_api_credential_payload`: ready-var/draft-var/araştır-ve-oluştur dalları,
  düşük-güven → manuel kart sinyali (research + n8n + store mock).
- `routes/credentials` finalize: n8n create + attach + status=ready; ownership 404.
- Frontend: taslak kartı (secret-only) + dashboard "Tamamla" akışı (tsc/lint).
- Canlı spike zaten doğrulandı (api-ninjas → X-Api-Key, OWM → appid).

## Kapsam / YAGNI
- Araştırma yalnız **HTTP auth şeması** (4 tip + "auth yok"); generic OAuth2 hariç.
- Cache **paylaşımlı** (global `api_auth_cache`).
- Research modeli **sabit Gemini Flash** (geçersizse Pro fallback), config'ten.
- Faz önerisi: **Faz 1** research + cache + `prepare_api_credential` + chat finalize;
  **Faz 2** dashboard taslak UI + "Tamamla"; **Faz 3** Conduut-farkındalık prompt
  cilası + force-refresh. (Tek spec, fazlı uygulama.)
