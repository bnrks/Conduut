# ADR-0022: Customer-Owned n8n Production Provider

Merkez: [[index]]

## Durum

Kabul edildi ve V1 kodu `codex/byo-n8n-v1` dalinda uygulandi (2026-08-03).
Production pilotu ve operasyonel rollout bekliyor.

## Baglam

Conduut MVP, tum kullanicilar icin tek shared n8n instance kullanir
([[adr-0001-shared-n8n-mvp]]). Onceki uzun vadeli tasarim Conduut'un her
kullanici icin ayri n8n container'i provision etmesini, control-plane ve
node-agent gelistirmesini ongoruyordu. Bu model en sade son kullanici deneyimini
saglasa da ticari n8n lisansi, yuksek altyapi/operasyon sorumlulugu ve urun
talebi kanitlanmadan buyuk platform yatirimi gerektirir.

Alternatif modelde her kullanici kendi VPS/cloud hesabinda kendi self-hosted
n8n instance'ini satin alir ve yonetir. Conduut kullanicinin verdigi HTTPS URL
ve iptal edilebilir API key ile public n8n API'sine baglanan ucuncu taraf AI
workflow yonetim katmani olur.

2026-08-03 tarihli repo disi n8n lisans yazismasi bu sinirlar altinda modelin
OEM/Embed veya yalniz public API entegrasyonu nedeniyle Enterprise lisansi
gerektiriyor gibi gorunmedigini belirtmistir. Yazisma repo'da kanonik lisans
kaniti olarak tutulmaz; bu ADR hukuki gorus veya lisans garantisi degildir.
Degerlendirme kullanicinin instance ile altyapi sahipligini korumasina baglidir.

## Karar

Aktif production hedefi **customer-owned n8n (BYO n8n)** modelidir:

- Kullanici VPS/cloud ve n8n instance'inin sahibidir ve faturasini dogrudan
  oder.
- Kullanici n8n owner/admin erisimini, workflow'larini, credential'larini,
  execution verisini ve backup'larini kontrol eder.
- Conduut n8n'i host etmez, yeniden satmaz, dagitmaz, white-label etmez veya n8n
  UI/editorunu gommez.
- Conduut authenticated `user_id` ile customer-owned n8n target'ini cozer ve
  public API uzerinden agent fonksiyonlarini calistirir.
- Kullanici API erisimini iptal edebilir ve n8n'i Conduut olmadan kullanabilir.
- Shared n8n yalniz local development, automated tests ve migration adapter'i
  olarak kalir; production tenancy siniri degildir.
- Managed per-tenant container/control-plane/node-agent modeli ertelenmistir.
  Yeniden ele alinmasi yeni lisans teyidi ve ayri ADR gerektirir.

Teknik tasarim ve migration fazlari [[customer-owned-n8n]] notunda tanimlanir.

## Lisans Guardrail'leri

Asagidaki degisikliklerden once yeni lisans incelemesi gerekir:

- Conduut'un musteri adina n8n host etmesi veya VPS faturasini ustlenmesi.
- n8n image/kurulumunu Conduut ticari urununun parcasi olarak dagitmasi.
- n8n editor/canvas/UI'nin Conduut icine gomulmesi veya white-label edilmesi.
- Conduut'un musteriye n8n erisimi satan managed service'e donusmesi.
- Kullanicinin cloud hesabinda otomatik provisioning'in mevcut customer-owned
  sinirlari degistirmesi.

Enterprise-only n8n ozellikleri ilgili kullanicinin kendi lisans
sorumlulugudur; Conduut bunlari Community instance'ta acmaya calismaz.

## Sonuclar

### Pozitif

- Conduut baslangicta n8n compute, volume, backup ve container operasyonu
  tasimaz.
- Her kullanicinin n8n verisi ve blast radius'i kendi altyapi hesabinda ayrilir.
- Mevcut n8n kullanan teknik kullanicilar hizli baglanabilir.
- Data residency ve customer-controlled/on-prem yonu guclenir.
- Ayni provider abstraction ileride managed secenek eklemeyi engellemez.

### Negatif

- Kullanici onboarding'i managed modele gore daha zordur.
- n8n surumu, TLS, network, webhook ve provider konfigurasyonlari parcalanir.
- Conduut musteri VPS'si icin SLA veremez; support siniri daha karmasiktir.
- Agent registry ve workflow compatibility icin dar bir supported version
  matrisi gerekir.
- Kullanici n8n editorunden degisiklik yaparak Conduut metadata'siyle drift
  olusturabilir.
- Public remote URL/API key, SSRF ve secret-management gereksinimi dogurur.

## Uygulama Guardrail'leri

- Production'da raw HTTP n8n origin kabul edilmez; HTTPS zorunludur.
- API key Firestore/log/browser/LLM context'inde tutulmaz; secret ref kullanilir.
- Workflow ve credential kimligi `instance_id` olmadan yetkilendirilmez.
- Production resolver hatasinda shared n8n'e fallback yapilmaz.
- Browser n8n public API'sine dogrudan baglanmaz; tum islemler agent backend'den
  gecer.
- Desteklenmeyen n8n surumu fail-open workflow write/activate yapmaz.

## Alternatifler

### Conduut-managed per-tenant container

En iyi sifir-kurulum UX'ini saglar; fakat lisans, control-plane, node-agent,
backup, monitoring, capacity ve incident sorumlulugu nedeniyle simdilik
ertelendi.

### Shared multi-user n8n

Local/dev MVP icin basit; workflow/credential/execution ownership izolasyonu
olmadigi icin production icin reddedildi.

### n8n editorunu embed etmek

Conduut'un chat-first urun yonune uymaz ve OEM/Embed lisans sinirina girer;
reddedildi.

## Ilgili

- [[customer-owned-n8n]]
- [[adr-0001-shared-n8n-mvp]]
- [[system-architecture]]
- [[current-state]]
- [[execution-history]]
- [[known-issues]]
