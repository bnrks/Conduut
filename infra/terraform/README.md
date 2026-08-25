# Google Cloud staging foundation

Bu dizin altyapi metadata'sini yonetir; secret degerlerini yonetmez. Terraform
state, plan veya variable dosyalarina secret degeri koymayin.

## Project sinirlari

Staging uc ayri project ister:

- application: Cloud Run, Artifact Registry, static secret container'lari ve
  serverless VPC,
- Firebase: Firebase Auth ve Firestore,
- tenant secrets: yalniz runtime tarafindan uretilen customer n8n API key'leri.

Bootstrap project remote state bucket, GitHub WIF provider ve deploy service
account'i tutar. Tum project'ler onceden olusturulmus ve billing'e baglanmis
olmalidir; bu Terraform root'u project satin almaz veya billing hesabi baglamaz.

## Ilk kurulum sirasi

Ilk foundation apply yetkili operator tarafindan yapilir. GitHub deploy kimligi
foundation IAM'ini degistiremez; yalniz image push eder ve mevcut Cloud Run
servislerinin image revision'ini gunceller.

1. `bootstrap/terraform.tfvars.example` dosyasini secret icermeyen gercek
   degerlerle yerel `terraform.tfvars` olarak kopyala.
2. `bootstrap` root'unda `terraform init`, `terraform plan`, `terraform apply`
   calistir. Ciktilardaki WIF provider ve deploy service account email'ini
   GitHub staging environment variable'larina yaz.
3. Staging backend config ve tfvars'i example dosyalarindan olustur.
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
dogrulanmalidir. Create, dedicated tenant-secret project'teki create-only
kosulsuz custom role'u; diger islemler hashed-prefix condition'li role'u
kullanir. Agent prefix disindaki bir secret'i okuyamamali veya silememelidir.
