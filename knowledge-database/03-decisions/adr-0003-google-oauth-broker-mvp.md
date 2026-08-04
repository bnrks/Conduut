# ADR 0003: Google OAuth Broker MVP

Merkez: [[index]]

## Durum

Accepted - 2026-05-03.

## Baglam

Conduut'un Gmail otomasyonlarini test edebilmesi icin kullanicinin n8n
editor'una girip credential olusturmasi iyi bir urun akisi degil. n8n
self-hosted ortamda Google OAuth icin Google Cloud OAuth client, callback URL ve
credential data gerektiriyor. MVP'de tek shared n8n instance var; per-user n8n
container, Vault ve OAuth proxy henuz yok.

## Karar

V1 Google Gmail connection icin Conduut kendi OAuth broker'i olacak. Google
Sheets workflow pilotu sonrasi ayni broker Google Sheets icin ikinci managed
connection olarak genisletildi:

- Kullanici web UI'da `Connect Google` der.
- Agent `state` ve PKCE `code_verifier` uretir, Firestore
  `oauth_states/{state}` dokumanina yazar.
- Google callback Next route'una gelir, Next agent callback endpoint'ine code ve
  state iletir.
- Agent Google token exchange yapar, userinfo okur ve n8n public API ile servis
  bazinda `gmailOAuth2` veya `googleSheetsOAuth2Api` credential olusturur.
- Firestore sadece connection metadata tutar; access/refresh token n8n
  credential store icinde kalir.

Scope V1 icin bilincli olarak read/send ile sinirlidir:

- `openid`
- `email`
- `profile`
- `https://www.googleapis.com/auth/gmail.send`
- `https://www.googleapis.com/auth/gmail.readonly`

Gmail message/thread/label `get` ve `getAll` operasyonlari ile send/reply
operasyonlari bu connection ile otomatik attach edilebilir. Delete, mark read,
mark unread ve modify gerektiren operasyonlar V1 connection ile otomatik attach
edilmez.

Google Sheets connection ayri `google_sheets` id'siyle tutulur ve n8n
`googleSheetsOAuth2Api` credential'i olusturur. Sheets authorization scope'lari:

- `openid`
- `email`
- `profile`
- `https://www.googleapis.com/auth/drive.file`
- `https://www.googleapis.com/auth/spreadsheets`
- `https://www.googleapis.com/auth/drive.metadata`

## Sonuclar

Pozitif:

- Kullanici n8n editor'una gitmeden Gmail read/send workflow'larini
  calistirabilir.
- Chat'teki Gmail Trigger ile Gmail read/send eksik credential durumu gercek
  OAuth prompt'a baglanir; Gmail Trigger read capability ister.
- Chat'teki Google Sheets eksik credential durumu da gercek OAuth prompt'a
  baglanir ve agent readiness akisi credential'i workflow node'una otomatik
  attach edebilir.
- Firestore raw Google token saklamaz.
- OAuth tabanli n8n credential semalari genel credential formu olarak
  gosterilmez. Managed olmayan bir OAuth tipi icin broker destegi yoksa chat
  secret/server URL alanlari toplamak yerine destek varsa Connections'a, yoksa
  dogrudan n8n OAuth yapilandirmasina yonlendirir.

Sinirlar:

- Shared n8n instance production izolasyonu degildir; credential'lar n8n'de
  encrypted olsa da ayni instance uzerindedir.
- Reconnect V1'de kullanici basina servis bazinda tek aktif `google/gmail` ve
  `google/sheets` connection'ini yeniler; eski n8n credential best-effort
  silinir.
- Public production'da Gmail sensitive scope verification gerekebilir.

Ilgili notlar: [[agent-service]], [[dashboard]], [[chat-workflow-generation]],
[[known-issues]], [[adr-0001-shared-n8n-mvp]].

## BYO Gecis Notu (2026-08-03)

[[adr-0022-customer-owned-n8n]] sonrasi OAuth broker korunur; degisen hedef
n8n'dir. Authorization baslatilirken `instance_id` signed OAuth state'e
baglanmali, callback credential'i resolver'in sectigi customer-owned n8n'e
enjekte etmelidir. Callback aninda kullanicinin aktif instance'i degisse bile
credential baska instance'a yazilamaz. Firestore connection metadata'si ve
`n8n_credential_id` de `instance_id` tasimalidir. Ayrinti:
[[customer-owned-n8n]].
