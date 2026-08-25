# Google Cloud Production Foundation

Merkez: [[index]]

Bu not, Conduut'un Google Cloud uzerindeki staging ve ileride production
temelini kurmak icin uygulanacak kanonik plandir. Ilk hedef mevcut
`conduut-1` icinde kontrollu bir `staging` temelidir. Production kaynaklari
staging pilotu ve kabul kapilari
gecilmeden olusturulmaz.

Ilgili kararlar: [[adr-0023-google-cloud-secret-and-runtime-foundation]],
[[customer-owned-n8n]], [[system-architecture]], [[agent-service]],
[[web-app]].

## Uygulama Durumu - 2026-08-25

- Faz 0 tamamlandi: BYO branch kontrolleri gecti, `main` fast-forward edilip
  origin'e gonderildi ve foundation branch'i guncel `main`den acildi.
- Faz 1-5'in repo temeli uygulandi: GSM/Firebase runtime hardening, ortak private
  agent BFF client'i, Terraform bootstrap/staging modulleri ve WIF image deploy
  workflow'u vardir.
- Local kanit: agent Ruff/format ve 808 pytest, web ESLint/TypeScript, registry
  Ruff, Compose config, Terraform bootstrap/staging init+validate ve scoped
  credential-pattern taramasi gecti. ESLint'te yalniz onceki dort `<img>`
  warning'i kaldi.
- Docker Desktop engine bu kontrolde kapali oldugu icin image build yeniden
  kosulamadi; CI iki image build'ini zorunlu tutar.
- Bootstrap canli uygulandi: private/uniform/versioned GCS state bucket remote
  backend'e import edildi; WIF pool/provider, `github-actions-deployer` service
  account ve yalniz `bnrks/Conduut` `main` ref binding'i olusturuldu. Apply
  `4 added, 0 changed, 0 destroyed`, sonraki plan `No changes` verdi.
- Faz 4'un secret-only canli adimi tamamlandi: staging remote state, sekiz bos
  regional statik secret container'i, iki runtime service account ve sinirli
  agent IAM binding'leri uygulandi. Sonraki plan `No changes` verdi; secret
  version/degeri eklenmedi.
- Faz 6'nin uygulama tarafi aciktir: statik secret seed, Artifact Registry,
  VPC/NAT, Cloud Run create, prefix-condition canary, private ingress negatif
  testleri ve rollback provasi yapilmamistir. Kullanici production/Cloud Run
  rollout istemedigi icin bu kaynaklar bilincli olarak bekler.
- `conduut-1` canli envanteri okundu: billing ve mevcut Firebase Web App aktif,
  `(default)` Firestore Native database `europe-west3` bolgesindedir. Gerekli
  API'ler etkinlestirildi. Secret-only exact plan `35 add, 0 change, 0 destroy`
  ile uygulandi; mevcut Firebase/Firestore, Cloud Run, Artifact Registry
  repository ve staging network kaynaklari plana girmedi.
- GitHub staging deploy job'u `STAGING_DEPLOY_ENABLED=true` olmadikca calismaz;
  flag hazirlik asamasinda unset kalir. `github-actions-deployer` henuz
  project-level role almaz; yalniz WIF impersonation binding'i vardir.
- `deploy_runtime_services`, `provision_artifact_registry` ve
  `provision_networking` varsayilan olarak false'tur. Runtime acilacaksa network
  flag'i zorunludur; Artifact Registry, Compute ve Cloud Run API'leri de ilgili
  flag acilmadan Terraform tarafindan etkinlestirilmez. Repository ve network
  kullanici onayi olmadan olusmaz.

## Hedef Sonuc

- `apps/web` public Cloud Run servisi olarak calisir.
- `apps/agent` public internetten erisilemeyen private Cloud Run servisi olur.
- Web BFF, agent'i kendi service account kimligiyle cagirir; kullanicinin
  Firebase ID token'i uygulama kimligi olarak ayrica korunur.
- Ilk staging, kullanicinin mevcut `conduut-1` Firebase Auth ve Firestore'unu
  kullanir; Terraform bu mevcut kaynaklari yeniden olusturmaz. Production veri
  izolasyonu staging pilotundan sonra ayri project/database karari gerektirir.
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
- Ilk staging tek `conduut-1` project'indedir; bootstrap/state, application
  runtime, Firebase ve tenant secret ayrimi IAM/resource sinirlariyla yapilir.
  Modul ileride Firebase ve tenant secrets icin ayri project ID destekler.
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
- Secret create yetkisi Secret Manager tarafindan parent project uzerinde
  degerlendirildigi icin tenant runtime'a yalniz
  `secretmanager.secrets.create` iceren ayri kosulsuz custom role verilir.
  Mevcut secret/version okuma, yazma ve silme yetkileri hashed prefix condition
  altinda kalir. Tek-project staging'de create yetkisinin blast radius'i
  `conduut-1` oldugu icin audit/quota canary production oncesi zorunludur.
- Agent'in statik secret'lari Cloud Run secret reference ile env/mount olarak
  okunur; tenant n8n key'leri Secret Manager API ile request aninda cozulur.
- Secret create IAM condition ile yeterince daraltilamiyorsa tenant secret'lar
  ayri bir GCP project'e ayrilir. Agent bu project'te project-wide exact custom
  role alir; statik platform secret'lari uygulama project'inde kalir.

### Deploy

- GitHub Actions, GitHub OIDC -> Workload Identity Pool/Provider -> deploy
  service account zincirini kullanir.
- Provider condition repository ve branch/ref'i sinirlar.
- Deploy service account yalniz Artifact Registry repository writer, mevcut
  Cloud Run servislerinde revision update ve gerekli runtime service-account
  act-as yetkilerine sahip olur. Foundation IAM/infra apply yetkisi almaz.
- Pull request akisi `fmt`, `validate`, test ve image build calistirir.
  Foundation plan/apply yetkili operator tarafindan yapilir; GitHub WIF akisi
  yalniz mevcut staging servislerine immutable image revision deploy eder.

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
5. Yeni version read-back sonrasi committed kabul edilir; onceki version'lardan
   birinin delayed-destruction cleanup'i gecici hata verirse rotation false
   negative dondurmez, PII-safe warning uretir ve yeni version aktif kalir.
6. Missing/permission/quota/network hatalarini secret degeri loglamadan
   siniflandir.
7. Fake-client unit testlerinin yanina staging canary testi ekle.

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
   Timeout controller response body/SSE omru bitene kadar acik kalir; yalniz
   header geldigi anda temizlenmez.
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
   - iki asamali runtime create kapisi (`deploy_runtime_services`).
3. Staging environment:
   - `europe-west3`,
   - mevcut `conduut-1` Firebase/Firestore baglantisi; create flag'leri kapali,
   - service limits ve env contract,
   - production'dan farkli isim/prefix/hostname.
4. Terraform ciktilari secret degeri icermez.

### Faz 5 - Build ve deploy pipeline

1. Agent ve web image'larini commit SHA ile tag'le.
2. PR: lint, type-check, unit test, Docker build, Terraform fmt/validate.
3. Main/staging deploy:
   - WIF ile GCP auth,
   - image push,
   - mevcut Cloud Run servislerine revision deploy,
   - revision health/readiness kontrolu,
   - smoke test basarisizsa onceki revision'a trafik rollback.
4. Static secret eksikse deploy veya readiness fail closed olur.

Foundation Terraform apply'i CI deploy kimliginin kapsami disindadir. Ilk
kurulumda operator once `deploy_runtime_services=false` ile API/IAM/network ve
secret container'larini olusturur, statik secret version'larini GSM'e dogrudan
ekler ve image'lari hazirlar; ancak sonra `deploy_runtime_services=true` ile
Cloud Run servislerini olusturur.

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
- Web: ESLint, TypeScript ve tum BFF route'larinin ortak client kullandigina
  yonelik kaynak taramasi. Repo'da web test runner'i bulunmadigi icin ortak
  client unit testi sonraki test-altyapisi isidir.
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
- Veri: ilk staging mevcut `conduut-1` Firestore'u kullanir; production
  izolasyonu ve migration bu foundation apply'inin disindadir.

## Urunlesme Oncesi Zorunlu Kapilar

- Agent distributed lock olmadan `max_instances > 1` yapilamaz.
- Secret audit/alert, budget/quota alert ve incident runbook tamamlanmalidir.
- Secret erisimleri tenant/audit korelasyonu ile PII-safe izlenmelidir.
- Production project, domain, retention, backup, DPA ve operasyon sahipligi
  ayrica onaylanmalidir.
- n8n hosted/embedded modele gecilirse lisans siniri yeniden yazili olarak
  dogrulanmalidir; bu temel yalniz customer-owned BYO modeli icindir.
