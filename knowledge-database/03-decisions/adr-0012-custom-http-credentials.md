# ADR 0012: Custom (HTTP) Credential Library

Merkez: [[index]]

## Durum

Accepted - 2026-06-19.

## Baglam

Kullanicilarin n8n'in OAuth disindaki "normal" credential'larini (HTTP node auth
tipleri: Header / Basic / Query / Custom Auth) Conduut'ta kaydedip HTTP Request
node'larinda kullanabilmesi gerekiyor. Mevcut akis yalnizca **reaktif** ve
**workflow'a bagli** idi (`readiness` bir node'da eksik credential gorur,
`credential_request` karti emit eder, `/api/credentials` n8n'de olusturup o
node'a baglar). Eksik olanlar:

- Yeniden kullanilabilir bir credential **kutuphanesi** (workflow'dan bagimsiz).
- Agent'in kayitli credential'lardan haberdar olmasi ve HTTP node'una dogru
  olani baglamasi.
- n8n public API credential **listelemiyor** (`GET /credentials` -> 405); bu
  yuzden listeleyip eslestirebilmek icin metadata'nin baska yerde tutulmasi.

Brainstorm kararlari: 4 tip de desteklensin; eslestirme **host'a gore** olsun;
baglama **onay-once** olsun; host alani **zorunlu**; yonetim hem dashboard hem
chat-ici olsun.

## Karar

Per-user **credential kutuphanesi**: secret yalnizca n8n credential store'unda
(write-only, geri okunamaz), secret-olmayan isaretci (`label`,
`credential_type`, `host`, `n8n_credential_id`) Firestore
`users/{uid}/credentials` altinda. [[adr-0003-google-oauth-broker-mvp]]'deki
`AppConnection` deseniyle ayni; izolasyon Firestore metadata katmaninda (agent
yalnizca kendi uid'sinin credential'larini gorur).

V1 tipleri yalnizca generic HTTP auth: `httpHeaderAuth`, `httpBasicAuth`,
`httpQueryAuth`, `httpCustomAuth`. Generic OAuth2 ve `predefinedCredentialType`
kapsam disi.

**Eslestirme (deterministik):** `agent/credential_types.py` `normalize_host`
URL/host/expression'dan hostname cikarir (dinamik `{{ }}` ise None);
`match_credentials` HTTP node URL'inin host'unu kullanicinin kayitli
credential'lariyla karsilastirir. Yalniz `n8n-nodes-base.httpRequest` node'lari
icin devreye girer (Webhook inbound basic-auth gibi durumlar eski reaktif yolda
kalir).

**Baglama (onay-once, agent-gudumlu):**

- Agent HTTP node'unu gercek URL ile kurar; auth gerekiyorsa
  `authentication=genericCredentialType` (+ biliyorsa `genericAuthType`).
- `readiness` host eslesmesi bulursa kart emit ETMEZ; create/update tool
  sonucuna `credential_suggestions` ekler.
- Agent `request_user_input` ile onay sorar; onay gelince
  `attach_credential(workflow_id, node_name, credential_id)` cagirir.
  Deterministik baglama node'un `authentication`/`genericAuthType` parametrelerini
  ve `credentials` alanini yazar (`n8n_client.attach_credential_to_workflow`
  `generic_auth_type` parametresi).
- Attach islemi workflow-bazli ortak mutation lock'u icinde calisir. Ayni
  workflow'da birden cok credential paralel baglansa bile her tur en son
  committed state'i yeniden okur; bir credential digerini ezmez. Tool, n8n'in
  committed cevabinda istenen credential bagini dogrulamadan basari donmez.
- Genel `update_workflow` credential otoritesi degildir: retained node'un mevcut
  credential state'i aynen korunur, yeni/retype node'daki model-kaynakli
  `credentials` atilir. Credential degisikligi yalniz bu dedicated/onayli yol ve
  managed readiness katmani uzerinden yapilir.
- Eslesme yoksa tip-secicili `credential_request` karti (4 tip + host onceden
  dolu) gosterilir; formu doldurup kaydetmek zaten bir onaydir.

**Host zorunlulugu:** outbound HTTP credential kutuphanesi (dashboard create veya
HTTP Request tip-secici kart, ki `generic_auth_type` gonderir) icin host
zorunlu. Eski reaktif per-workflow yol (orn. Webhook basic auth) host gerektirmez.

**Yuzeyler:** dashboard `/dashboard/credentials` (proaktif kutuphane: ekle/sil)
ve chat-ici reaktif kart. Yeni tool'lar: `list_credentials(url?)` (secret yok,
host-eslesme bayrakli), `attach_credential`. Yeni route'lar: `POST /credentials`
(library create + opsiyonel attach), `GET /credentials`, `GET /credentials/types`,
`DELETE /credentials/{id}`.

## Kullanici Yuzeyi (UX, 2026-06-19b)

Kullanici n8n credential tip adlarini (httpHeaderAuth/Basic/Query/Custom) **hic
gormez**. Bunun yerine duz-dil "auth method" modeli (frontend'de
`lib/credential-auth-methods.ts`): "API key / token" (varsayilan), "Username &
password", + Gelismis ("API key in the URL", "Custom"). Frontend bunlari n8n
`credential_type` + `data` sekline cevirir (backend degismez). Paylasilan
`components/credentials/credential-form.tsx` hem chat karti hem dashboard
formunda kullanilir.

- **Chat (asil yol):** agent semayi kendisi secer (system prompt: API key/token
  -> httpHeaderAuth; username+password -> httpBasicAuth; emin degilse TEK duz-dil
  soru). Kart tek yontemle gelir -> kullanici sadece secret'i girer; header adi
  (varsayilan `Authorization`) + `Bearer` prefiksi "Gelismis" altinda.
- **Dashboard:** duz-dil yontem secici (varsayilan "API key / token"), host
  zorunlu. Liste rozetinde `friendlyTypeLabel` ile dostane etiket.

"API key / token" yontemi `{name: <header>, value: "<prefix> <key>"}` uretir
(varsayilan `Authorization` + `Bearer`); ozel header / prefiks Gelismis'te
degistirilir. Boylece yaygin durum sifir-friction, nadir durumlar Gelismis ile.

## Sonuclar

- Secret hic bir zaman Conduut tarafindan loglanmaz/geri dondurulmez/node
  parametresine yazilmaz; agent yalniz metadata gorur.
- Shared n8n MVP'de cross-workflow reuse koprusu
  (`_discover_existing_credential`) HTTP custom creds icin **kullanilmaz** (yeni
  vault yolu oncelikli); kopru yalniz non-HTTP tipler (orn. `openAiApi`) icin
  kalir. Bkz. [[known-issues]].
- Customer-owned n8n gecisinde metadata->credential map'i `instance_id` ile
  scope edilir; secret resolver'in sectigi kullanici n8n credential store'unda
  kalir ([[customer-owned-n8n]]).
- Eski `workflow_credentials` koleksiyonu deprecate; yeni creds `credentials`
  koleksiyonuna yazilir (migrasyon yok, MVP).
- HTTP credential attach basarisi yalniz credential id/name nesnesine bakmaz;
  committed node parametrelerinde `authentication=genericCredentialType` ve
  beklenen `genericAuthType` da korunmus olmalidir. n8n bunlardan birini dusururse
  client 409 ile fail-closed davranir.

## Ilgili

- [[adr-0003-google-oauth-broker-mvp]] - managed OAuth (Gmail/Sheets) deseni.
- [[adr-0010-json-surface-repair-normalizer]] - model intent + deterministik
  isleme felsefesi.
- [[agent-service]], [[known-issues]].
- [[adr-0022-customer-owned-n8n]], [[customer-owned-n8n]] - BYO instance ve
  credential ownership siniri.
