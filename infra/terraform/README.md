# Google Cloud staging foundation

Bu dizin altyapi metadata'sini yonetir; secret degerlerini yonetmez. Terraform
state, plan veya variable dosyalarina secret degeri koymayin.

## Project sinirlari

Ilk staging kurulumu mevcut `conduut-1` project'ini kullanir. Ayni project'te
Cloud Run, Artifact Registry, Firebase/Auth/Firestore, statik secret'lar, tenant
secret'lari, serverless VPC, Terraform state bucket ve GitHub WIF bulunur.
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
2. State bucket henuz yokken `bootstrap` root'unda `terraform init
   -backend=false`, `terraform plan` ve ilk `terraform apply` ile local bootstrap
   state kullan. Bucket olustuktan sonra `backend.hcl.example` dosyasini
   gitignored `backend.hcl` olarak kopyala ve `terraform init -migrate-state
   -backend-config=backend.hcl` ile bootstrap state'ini GCS'e tasi. Migration
   tamamlanmadan local state dosyasini silme. Ciktilardaki WIF provider ve deploy
   service account email'ini GitHub staging environment variable'larina yaz.
3. Staging `backend.hcl` ve `terraform.tfvars` dosyalarini example'lardan
   olustur; ikisi de gitignored'dir. `terraform init
   -backend-config=backend.hcl` kullan. Mevcut Firebase/Firestore icin iki
   `manage_*` flag'i false kalir.
   `deploy_runtime_services=false` birak ve staging root'una apply et. Bu adim
   API/IAM/network/secret container'larini olusturur, Cloud Run'i olusturmaz.
4. Statik secret degerlerini yetkili operator olarak dogrudan Google Secret
   Manager'a ekle. Degerleri shell history, Git, CI output veya Terraform'a
   koyma. Her gerekli secret'in en az bir enabled version'i oldugunu Secret
   Manager metadata'sindan dogrula.
5. Agent ve web image'larini Artifact Registry'ye push et; tfvars image
   URI'lerini immutable tag/digest ile guncelle.
6. `deploy_runtime_services=true` yap, plan'i incele ve staging'e apply et.
7. Web public URL, agent internal ingress, web -> agent IAM/VPC cagrisi ve
   tenant secret canary testlerini tamamla.
8. Bundan sonra `.github/workflows/staging-foundation.yml` WIF ile image push
   edip mevcut Cloud Run servislerini gunceller; smoke failure onceki
   revision'lara trafik rollback yapar.

## Zorunlu GitHub staging variable'lari

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
  bunu kullanmaz, ayri `staging-serverless-vpc` planlar.
- Gercek project kimligiyle apply'siz plan sonucu `40 add, 0 change, 0 destroy`;
  Firebase, Firestore ve Cloud Run bu ilk planda degisiklik olarak yer almadi.
- Ayni project bootstrap plan'i `5 add, 0 change, 0 destroy` verdi; apply
  yapilmadi.
