# ADR 0013: Agent-Managed Credentials (research + draft + Conduut-awareness)

Merkez: [[index]]

## Durum

Accepted - 2026-06-21.

## Baglam

[[adr-0012-custom-http-credentials]] ile kullanici custom (HTTP) credential
kaydedebiliyor, ama credential'in **nasil yapilandirilacagini** (auth tipi,
header/param adi, prefix) hala kullanici seciyor. Her API'nin auth semasi farkli
ve kullanici bunu bilmek zorunda kalmamali. Ayrica agent gerektiginde bir
credential **olusturabilmeli**, kullanicinin saglamasi gereken alanlari (api
key/secret) bos birakip kullanici sonra doldurabilmeli.

Web-search spike'i (Pydantic AI 1.88 `WebSearchTool`) dogrulandi: **decoupled
Gemini grounding** ile arastirma provider-bagimsiz calisiyor (ana model Claude
olsa bile arastirmayi Gemini yapar). Token maliyeti Gemini grounding'de cok
dusuk (~75 input vs Anthropic web_search ~16k).

## Karar

Agent bir API'nin auth semasini arastirir, **secret'siz bir taslak credential**
olusturur; kullanici secret'i chat'te veya dashboard'da **sonra** doldurur;
finalize'da n8n credential olusup node'a baglanir. **Secret asla agent/LLM'den
gecmez.**

**Arastirma (provider-bagimsiz):** `agent/research.py` `research_api_auth(host)`
sabit, ucuz **Gemini Flash + grounding** alt-agent'i (tier/router'dan bagimsiz)
calistirir, structured `AuthResearchResult` (`scheme`, `field_name`,
`value_prefix`, `secret_fields`, `summary`, `source_url`, `confidence`) doner.
Grounding cagrisi `_run_grounding_research` arkasinda (cache/map mantigi
unit-testable). Provider-native builtin tool (Option A) provider-bagimli
oldugundan, **decoupled tool (Option B)** secildi.

**Paylasimli cache:** global Firestore `api_auth_cache/{host}` (kullanici-ustu,
secret yok, TTL 60g, yalniz high/medium guven). Web-search maliyeti
okuma/yazmadan pahali → bir kez arastir, herkese servis et. Auth semasi halka
acik/hassas-olmayan bilgi oldugundan paylasim guvenli.

**Taslak credential:** `CustomCredential.status=draft` (n8n credential **YOK**) +
`auth_config` (secret-olmayan yapi) + `secret_fields` + `source_url` +
`pending_workflow_id/node_name`. Finalize'da (`POST /credentials/{id}/finalize`)
`auth_config`+secret → n8n `data` kurulur, n8n credential olusur, status=ready,
bekleyen node'a baglanir.

**Tool + prompt:** yeni `prepare_api_credential(api_or_url, workflow_id?,
node_name?)` (reaktif: eksik-credential'li HTTP node; proaktif: "X'e baglan").
Sonuc status'leri: `exists` / `draft_pending` / `draft_created` / `needs_manual`
/ `no_auth`. Dusuk guven → taslak uydurma, duz-dil manuel karta dus.
Conduut-farkindaligi prompt'ta: kullaniciya hangi auth method kuruldugunu +
secret'i karttan ya da Dashboard → Credentials → Tamamla'dan girmesini soyle;
anahtari chat'e yazdirma.

**Yuzeyler:** chat secret-only draft karti (paylasilan `CredentialForm`
`secretOnly` modu, finalize endpoint'e gider, kaynak notu) + dashboard taslak
rozeti ("Tamamlanmamis") + "Tamamla" (secret formu → finalize).

## Sonuclar

- Secret yalniz n8n'de; agent metadata + auth semasi gorur, secret'i hic gormez.
- Research modeli sabit Gemini (config `research_model`), tier'dan bagimsiz;
  Anthropic/OpenAI degil (token maliyeti).
- Cache cross-user (public auth bilgisi); per-user'a cevrilebilir.
- Taslak n8n'i kirletmez; finalize'da olusur.
- **Acik (canli):** Gemini `output_type`+`WebSearchTool` kombinasyonu canli
  dogrulanmali; reddederse `_run_grounding_research` free-text+parse fallback.

## Ilgili

- [[adr-0012-custom-http-credentials]] - custom credential kutuphanesi temeli.
- [[adr-0011-conduut-managed-tiered-models]] - tier/provider modeli (research
  bundan bagimsiz, sabit Gemini).
- [[agent-service]], [[known-issues]].
