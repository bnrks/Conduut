# Google Cloud Production Foundation

Merkez: [[index]]

Bu not, Conduut'un Google Cloud uzerindeki staging ve ileride production
temelini kurmak icin uygulanacak kanonik plandir. Ilk hedef tam izole bir
`staging` ortamidir. Production kaynaklari staging pilotu ve kabul kapilari
gecilmeden olusturulmaz.

Ilgili kararlar: [[adr-0023-google-cloud-secret-and-runtime-foundation]],
[[customer-owned-n8n]], [[system-architecture]], [[agent-service]],
[[web-app]].

## Hedef Sonuc

- `apps/web` public Cloud Run servisi olarak calisir.
- `apps/agent` public internetten erisilemeyen private Cloud Run servisi olur.
- Web BFF, agent'i kendi service account kimligiyle cagirir; kullanicinin
  Firebase ID token'i uygulama kimligi olarak ayrica korunur.
- Firebase Auth ve Firestore staging icin ayri bir GCP/Firebase project'te
  calisir.
- Customer-owned n8n API key'leri Firestore, Terraform state, GitHub, log,
  browser veya chat'e girmez; runtime'da Google Secret Manager'da tutulur.
- LLM provider key'leri, Google OAuth client secret ve connection encryption
  key gibi statik platform secret'lari da Google Secret Manager'da tutulur.
- Cloud Run servisleri JSON service-account key kullanmaz; attached service
  account ve Application Default Credentials (ADC) kullanir.
- Altyapi Terraform ile, deploy GitHub Actions Workload Identity Federation
  (WIF/OIDC) ile yonetilir. GitHub'da uzun omurlu GCP key tutulmaz.
- Local development `encrypted_file` backend'iyle devam eder.

## Degismez Guvenlik Sinirlari

1. Production/staging `customer_owned` modu secret backend hatasinda fail
   closed olur; `memory`, `encrypted_file` veya shared n8n fallback'i yapmaz.
2. Runtime service account'a `Owner`, `Editor` veya Secret Manager Admin
   verilmez.
3. Tenant secret adlari PII tasimaz ve ham Firebase UID/instance ID icermeyen,
   deterministik hash tabanli bir kimlik kullanir.
4. Secret degerleri Terraform variable/state, GitHub secret, Docker build arg,
   Firestore, log ve API response'larina yazilmaz.
5. Agent private kalir. Firebase token tek basina Cloud Run ingress'i acmaz;
   web service identity Cloud Run IAM katmanini, Firebase token uygulama auth
   katmanini gecer.
6. Mevcut local/VPS API key decrypt edilip tasinmaz. Staging kullanicisi n8n
   baglantisini UI uzerinden yeniden kurar.
7. Secret rotation yeni version okunmadan eski version'i yok etmez.

## Secret Siniflari ve Sahiplik

| Sinif | Ornek | Yazan | Okuyan | Saklama modeli |
|---|---|---|---|---|
| Tenant runtime | customer n8n API key | Agent | Agent | GSM runtime secret, hash adli |
| Platform runtime | LLM provider key | Operator | Agent | GSM statik secret |
| OAuth | Google OAuth client secret | Operator | Web/Agent ihtiyacina gore | GSM statik secret |
| Encryption | connection encryption key | Operator | Agent | GSM statik secret |
| Public config | Firebase web config, service URL | Terraform/deploy | Web | Secret degil, env/config |

Terraform secret container/metadata ve IAM'i olusturur; statik secret
degerlerini state'e almaz. Ilk degerler yetkili operator tarafindan dogrudan
GSM'e eklenir. Tenant secret degerlerini yalniz agent runtime API'si yazar.

## Hedef GCP Topolojisi

- Region: `europe-west3` (Frankfurt).
- Staging: ayri GCP project + ayri Firebase Auth + ayri Firestore.
- Cloud Run `web`:
  - public ingress,
  - container port `3000`,
  - concurrency `80`, min instance `0`, max instance `3`,
  - kendine ait service account.
- Cloud Run `agent`:
  - authenticated/private ingress,
  - container port `8000`,
  - request timeout `900s`,
  - concurrency `10`, min instance `0`, max instance `1`,
  - kendine ait runtime service account.
- Agent `max=1` ilk urunlesme siniridir: workflow mutation lock'lari su anda
  process-local'dir. Yatay olceklemeden once distributed lock zorunludur.
- Artifact Registry, Secret Manager, Firestore ve Cloud Run ayni bolgede
  tutulur.
- Terraform remote state icin versioning ve uniform bucket-level access acik
  ayri GCS bucket kullanilir.

## Kimlik ve Yetki Modeli

### Runtime

- Web service account yalniz private agent Cloud Run servisine
  `roles/run.invoker` alir.
- Agent service account Firestore icin gereken en dar veri yetkilerini ve
  tenant secret prefix'i icin gereken exact custom secret rolunu alir.
- Agent'in statik secret'lari Cloud Run secret reference ile env/mount olarak
  okunur; tenant n8n key'leri Secret Manager API ile request aninda cozulur.
- Secret create IAM condition ile yeterince daraltilamiyorsa tenant secret'lar
  ayri bir GCP project'e ayrilir. Agent bu project'te project-wide exact custom
  role alir; statik platform secret'lari uygulama project'inde kalir.

### Deploy

- GitHub Actions, GitHub OIDC -> Workload Identity Pool/Provider -> deploy
  service account zincirini kullanir.
- Provider condition repository ve branch/ref'i sinirlar.
- Deploy service account yalniz Artifact Registry push, Cloud Run deploy,
  gerekli service-account act-as ve Terraform kaynak yonetimi yetkilerine
  sahip olur.
- Pull request akisi `fmt`, `validate`, test ve `terraform plan` calistirir.
  Apply yalniz korumali environment/onay sonrasi staging'e yapilir.

## Uygulama Asamalari

### Faz 0 - Branch ve kanit kapisi

1. `codex/byo-n8n-v1` tam agent/web/registry/Compose kontrollerinden gecirilir.
2. `main` yalniz `--ff-only` ile ilerletilir ve origin'e gonderilir.
3. `codex/gcp-secret-manager-foundation` branch'i guncel `main`den acilir.
4. Bu dokuman kod degisikliginden once commit edilir.

### Faz 1 - Secret Store hardening

1. Tenant secret ref formatini PII-free deterministik hash'e cevir.
2. GSM secret create sirasinda `version_destroy_ttl=604800` (7 gun) tanimla.
3. Rotation sirasi:
   - yeni version ekle,
   - eklenen exact version'i okuyup dogrula,
   - Firestore ref degisikligi gerekiyorsa atomik olarak guncelle,
   - onceki version'lari `destroy` ile delayed destruction'a al.
4. Yeni version yazma/okuma basarisizsa eski version enabled kalir.
5. Missing/permission/quota/network hatalarini secret degeri loglamadan
   siniflandir.
6. Fake-client unit testlerinin yanina staging canary testi ekle.

### Faz 2 - Firebase ADC ve runtime config

1. Firebase init'e acik iki mod ekle:
   - local certificate (`serviceAccount.json`),
   - cloud ADC (`credentials.ApplicationDefault()` veya sertifikasiz
     `initialize_app` + explicit project ID).
2. Production/staging Cloud Run config'i ADC disinda boot etmesin.
3. Local compose ve Uvicorn akisini geriye uyumlu koru.
4. Config validation'da project ID, environment ve secret backend matrisini
   fail-fast dogrula.

### Faz 3 - Private Agent cagri katmani

1. Web BFF icin ortak server-only agent client olustur.
2. Cloud Run hedefi icin Google ID token'i hedef audience ile al ve
   `X-Serverless-Authorization: Bearer <google-id-token>` header'ina koy.
3. Kullanici Firebase token'ini mevcut
   `Authorization: Bearer <firebase-id-token>` header'inda koru.
4. Browser'a agent URL veya Google identity token gonderme.
5. Tum BFF route'larini ortak client'a tasi; timeout, SSE ve hata map'ini
   merkezi hale getir.
6. Unit testlerde iki auth katmaninin birlikte ve secret redaction ile
   calistigini kanitla.

### Faz 4 - Terraform staging foundation

Repo yapisi:

```text
infra/terraform/
  bootstrap/
  modules/conduut-environment/
  environments/staging/
```

1. Bootstrap:
   - Terraform state bucket,
   - Workload Identity Pool/Provider,
   - deploy service account ve dar IAM.
2. Environment module:
   - gerekli API'ler,
   - Artifact Registry,
   - web/agent service account'lari,
   - custom Secret Manager role ve IAM binding'leri,
   - statik secret container'lari (degersiz),
   - Cloud Run web/agent servisleri,
   - Cloud Run invoker binding,
   - log/metric/alert temelleri.
3. Staging environment:
   - `europe-west3`,
   - izole Firebase/Firestore project baglantisi,
   - service limits ve env contract,
   - production'dan farkli isim/prefix/hostname.
4. Terraform ciktilari secret degeri icermez.

### Faz 5 - Build ve deploy pipeline

1. Agent ve web image'larini commit SHA ile tag'le.
2. PR: lint, type-check, unit test, Docker build, Terraform fmt/validate/plan.
3. Main/staging deploy:
   - WIF ile GCP auth,
   - image push,
   - korumali staging apply/deploy,
   - revision health/readiness kontrolu,
   - smoke test basarisizsa onceki revision'a trafik rollback.
4. Static secret eksikse deploy veya readiness fail closed olur.

### Faz 6 - Canli staging pilotu

1. Yeni staging Firebase kullanicisi olustur.
2. UI'dan customer-owned test n8n baglantisi kur.
3. Secret'in Firestore/API/log/browser'da gorunmedigini, GSM'de olustugunu
   kanitla.
4. Agent restart/revision sonrasi baglantinin calistigini dogrula.
5. Key rotation yap; yeni version'i kullan, onceki version'in delayed
   destruction'a girdigini kanitla.
6. Agent public URL'una unauthenticated ve yalniz Firebase token ile erisimin
   reddedildigini; web BFF uzerinden cagrinin gectigini kanitla.
7. Basit build/read/run senaryosu ve bir n8n hata senaryosunda evidence/readback
   zincirini dogrula.

## Test Matrisi

- Agent: Ruff, format check, tum pytest; GSM unit/failure/rotation testleri.
- Web: ESLint, TypeScript; ortak BFF client auth/timeout/SSE testleri.
- Infra: `terraform fmt -check`, `init -backend=false`, `validate`, policy/IAM
  kontrolleri, `docker compose config`, iki image build.
- Security: repository secret scan, Terraform plan/state secret leakage
  kontrolu, Cloud Run IAM negatif testleri.
- Live staging: create/read/rotate/restart/disconnect, private ingress, WIF
  deploy, rollback smoke testi.

## Kabul Kriterleri

- Restart ve yeni Cloud Run revision sonrasi tenant n8n baglantisi calisir.
- Repoda, image'da ve CI'da static GCP service-account JSON yoktur.
- Raw secret Git, Terraform state/plan, Firestore, log, browser payload veya CI
  output'unda bulunmaz.
- Runtime hesaplarinda Admin/Owner/Editor yoktur.
- Agent unauthenticated internet cagrilarina kapali, web publictir.
- Cloud ortaminda `encrypted_file`, `memory` veya shared n8n fallback'i yoktur.
- Rotation yeni version'i dogrular ve eski version'lari 7 gun gecikmeli
  destruction'a alir.
- Staging pilotu ve negatif auth testleri gecmeden production apply yapilmaz.

## Rollback

- Uygulama: Cloud Run trafik yuzdesini son saglikli revision'a dondur.
- Secret rotation: yeni version dogrulanmadiysa eski enabled version'i koru;
  destroy planlanmissa 7 gunluk recovery penceresini kullan.
- Terraform: state/versioning ile once plan/readback yap; secret degerlerini
  Terraform'a geri alma.
- Veri: staging Firestore production'dan izoledir; production migration bu
  planda yoktur.

## Urunlesme Oncesi Zorunlu Kapilar

- Agent distributed lock olmadan `max_instances > 1` yapilamaz.
- Secret audit/alert, budget/quota alert ve incident runbook tamamlanmalidir.
- Secret erisimleri tenant/audit korelasyonu ile PII-safe izlenmelidir.
- Production project, domain, retention, backup, DPA ve operasyon sahipligi
  ayrica onaylanmalidir.
- n8n hosted/embedded modele gecilirse lisans siniri yeniden yazili olarak
  dogrulanmalidir; bu temel yalniz customer-owned BYO modeli icindir.
