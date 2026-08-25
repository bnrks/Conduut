# Google Cloud staging foundation

Bu dizin altyapi metadata'sini yonetir; secret degerlerini yonetmez. Terraform
state, plan veya variable dosyalarina secret degeri koymayin.

## Project sinirlari

Ilk staging kurulumu mevcut `conduut-1` project'ini kullanir. Hedef mimaride
Cloud Run, Artifact Registry, Firebase/Auth/Firestore, statik secret'lar, tenant
secret'lari, serverless VPC, Terraform state bucket ve GitHub WIF ayni
project'tedir; bunlar asamali flag'ler ile ayri ayri acilir.
Terraform mevcut Firebase project'ini ve `(default)` Firestore database'ini
olusturmaz; `manage_firebase_project=false` ve
`manage_firestore_database=false` kalir.

Modul ileride Firebase veya tenant secrets icin ayri project ID kabul eder.
Production izolasyonu staging pilotu sonrasinda ayrica degerlendirilir. Tek
project modelinde create-only tenant secret role'u project genelinde yeni
secret container'i olusturabilir; mevcut secret/version erisimi hashed prefix
condition ile sinirlidir.

## Ilk kurulum sirasi

Ilk foundation apply yetkili operator tarafindan yapilir. GitHub deploy kimligi
foundation IAM'ini degistiremez; yalniz image push eder ve mevcut Cloud Run
servislerinin image revision'ini gunceller.

1. `bootstrap/terraform.tfvars.example` dosyasini yerel `terraform.tfvars`
   olarak kopyala. `bootstrap_project_id=conduut-1`,
   `github_repository=bnrks/Conduut` ve ayni project'te API sahipligini iki
   state'e bolmemek icin `manage_project_services=false` kullan.
2. Backend bucket Terraform'un kendi backend'i olacagi icin ilk kez GCP CLI ile
   `europe-west3`, uniform bucket-level access, public access prevention ve
   versioning acik olarak olustur. `backend.hcl.example` dosyasini gitignored
   `backend.hcl` olarak kopyala; `terraform init -backend-config backend.hcl`
   calistir ve bucket'i `google_storage_bucket.terraform_state` adresine import
   et. Bundan sonra bootstrap plan/apply remote state kullanir. Ciktilardaki WIF
   provider ve deploy service account email'ini GitHub staging environment
   variable'larina yaz.
3. Staging `backend.hcl` ve `terraform.tfvars` dosyalarini example'lardan
   olustur; ikisi de gitignored'dir. `terraform init
   -backend-config=backend.hcl` kullan. Mevcut Firebase/Firestore icin iki
   `manage_*` flag'i false kalir.
   `deploy_runtime_services=false`, `provision_artifact_registry=false` ve
   `provision_networking=false` birak ve staging root'una apply et. Bu adim
   API yonetimi, sinirli IAM, runtime service account'lari ve bos secret
   container'larini olusturur; Cloud Run, image repository veya VPC/NAT
   olusturmaz. Artifact Registry, Compute ve Cloud Run API'leri de kendi
   provisioning flag'leri acilmadan Terraform tarafindan etkinlestirilmez.
4. Statik secret degerlerini yetkili operator olarak dogrudan Google Secret
   Manager'a ekle. Degerleri shell history, Git, CI output veya Terraform'a
   koyma. Her gerekli secret'in en az bir enabled version'i oldugunu Secret
   Manager metadata'sindan dogrula.
5. Uygulama yayinina acik onay verildiginde
   `provision_artifact_registry=true` yapip repository plan/apply et. Agent ve
   web image'larini push et; tfvars image URI'lerini immutable tag/digest ile
   guncelle.
6. `provision_networking=true` ve `deploy_runtime_services=true` yap, plan'i
   incele ve staging'e apply et.
7. Web public URL, agent internal ingress, web -> agent IAM/VPC cagrisi ve
   tenant secret canary testlerini tamamla.
8. Bundan sonra `.github/workflows/staging-foundation.yml` WIF ile image push
   edip mevcut Cloud Run servislerini gunceller; smoke failure onceki
   revision'lara trafik rollback yapar.

## Zorunlu GitHub staging variable'lari

- `STAGING_DEPLOY_ENABLED` (`true` olmadikca push image/Cloud Run deploy job'u
  calismaz; hazirlik asamasinda unset/false kalir)
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `GCP_PROJECT_ID`
- `GCP_FIREBASE_PROJECT_ID`
- `GCP_REGION`
- `GCP_ARTIFACT_REPOSITORY`
- `PUBLIC_WEB_URL`
- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_APP_ID`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`

Firebase web config public client configuration'dir. Platform API key, OAuth
client secret, encryption key ve tenant n8n API key GitHub'a girmez.

Bu foundation hazirligi Cloud Run rollout'u degildir. Kullanici urun deploy'una
acik onay verene kadar `STAGING_DEPLOY_ENABLED` set edilmez ve
`deploy_runtime_services=false` kalir.

## Canli dogrulama kapisi

Local/CI `terraform validate` gerekli ama yeterli degildir. Ilk staging apply
sonrasinda tenant secret IAM modeli canary create/read/rotate/destroy ile
dogrulanmalidir. Create, `conduut-1` icindeki create-only kosulsuz custom role'u;
diger islemler hashed-prefix condition'li role'u kullanir. Agent prefix
disindaki bir secret'i okuyamamali veya silememelidir.

## Canli proje durumu - 2026-08-25

- Billing, Firebase Web App ve `europe-west3` Native Firestore zaten aktiftir.
- Cloud Run, Artifact Registry, Secret Manager, Compute, IAM, IAM Credentials
  ve STS API'leri etkinlestirildi.
- Compute API etkinlestirmesi `default` auto-mode VPC olusturdu; foundation
  bunu kullanmaz, ayri `staging-serverless-vpc` planlar. Secret-only modul
  artik Compute API'yi `provision_networking=true` olmadan etkinlestirmez;
  mevcut `default` VPC ayri envanter/silme karari bekler.
- Secret-only exact plan `35 add, 0 change, 0 destroy` olarak incelendi;
  Cloud Run, Artifact Registry repository, VPC/subnet/router/NAT ve deployer
  project IAM binding'i planda yer almadi.
- `conduut-1-terraform-state` bucket'i private/uniform/versioned olarak
  olusturuldu, GCS backend'e import edildi ve remote state
  `bootstrap/default.tfstate` altinda dogrulandi.
- Exact bootstrap apply `4 added, 0 changed, 0 destroyed` ile WIF pool/provider,
  `github-actions-deployer` service account ve yalniz `bnrks/Conduut` `main`
  ref impersonation binding'ini olusturdu. Sonraki plan `No changes` verdi.
- Deploy service account henuz project-level role almaz; yalniz kendi uzerindeki
  `roles/iam.workloadIdentityUser` binding'i vardir. GitHub repository variable
  listesi bostur ve `STAGING_DEPLOY_ENABLED` set edilmemistir.
- Secret-only staging foundation uygulandi ve sonraki plan `No changes` verdi.
  Bes regional statik secret container'i tutulur: DeepSeek, Google research,
  Google OAuth client ID/secret ve connection encryption key. Hicbirinde secret
  version/deger yoktur. `staging-agent` ve `staging-web` service account'lari
  olusturuldu; agent yalniz `roles/datastore.user`, iki sinirli custom secret
  role'u ve bes secret-ozel accessor binding'i aldi. Kullanilmayan bos
  Anthropic, OpenAI ve OpenRouter container'lari kaldirildi. Staging runtime
  profili, kalan provider secret'lariyla tutarli olacak sekilde Terraform
  root'unda `deepseek` olarak sabitlenir; Google API key yalniz research/judge
  yardimci yollarina ayrilir.
- Cloud Run service, image, VPC/subnet/router/NAT veya Artifact Registry
  repository olusturulmadi. Deploy service account project-level role almadi;
  `STAGING_DEPLOY_ENABLED` unset kalir.
- Staging remote state
  `gs://conduut-1-terraform-state/environments/staging/default.tfstate`
  altinda dogrulandi.
