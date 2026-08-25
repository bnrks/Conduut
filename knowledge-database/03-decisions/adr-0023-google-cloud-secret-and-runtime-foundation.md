# ADR-0023: Google Cloud Secret ve Runtime Foundation

Merkez: [[index]]

- Durum: Kabul edildi, uygulama asamasinda
- Tarih: 2026-08-25
- Ilgili: [[google-cloud-production-foundation]], [[customer-owned-n8n]],
  [[adr-0022-customer-owned-n8n]]

## Baglam

Customer-owned n8n uygulamasi request-scoped target ve secret-store sinirini
kurdu, fakat production runtime, IAM, deploy ve secret lifecycle'i repo icinde
tanımlı degildi. Local encrypted file kalici gelistirme icin yeterli olsa da
Cloud Run gibi ephemeral ve cok revision'li bir ortam icin uygun degildir.
Karar oncesinde Firebase Admin de yerel JSON sertifikasina bagliydi.

## Karar

Conduut staging foundation Google Cloud uzerinde Terraform ile kurulacak:

- Web public, agent private Cloud Run servisi olacak.
- Runtime attached service account + ADC kullanacak; static service-account
  JSON key kullanilmayacak.
- Tenant n8n API key'leri ve platform secret'lari Google Secret Manager'da
  tutulacak; degerler Terraform state'e girmeyecek.
- Tenant secret create yetkisi create-only kosulsuz custom role'a; mevcut
  secret/version islemleri hashed-prefix condition'li ayri role'a bolunecek.
- Web -> agent cagrisi Cloud Run ID token'i ve Firebase ID token'i iki ayri
  header'da tasiyacak.
- GitHub Actions GCP'ye WIF/OIDC ile baglanacak.
- Ilk staging kullanicinin mevcut `conduut-1` project'ini ve mevcut Firebase/
  Firestore'unu kullanacak; Terraform bunlari yeniden olusturmayacak. Logical
  sinirlar IAM ve resource bazinda korunacak, regional kaynaklar
  `europe-west3` bolgesinde tutulacak. Modul daha sonra ayri Firebase veya
  tenant-secret project ID kabul etmeye devam edecek.
- Foundation Terraform apply'i operator yetkisidir. GitHub WIF deploy kimligi
  yalniz image push, mevcut Cloud Run revision update ve gerekli runtime
  service-account act-as yetkilerini alacak.
- Agent ilk asamada process-local mutation lock nedeniyle en fazla bir Cloud
  Run instance ile sinirlanacak.
- Secret version rotation yeni version readback sonrasi eski version'lari yedi
  gun gecikmeli destruction'a alacak.

## Sonuclar

- Local dev `encrypted_file` ile calismaya devam eder; cloud fail closed olur.
- Tek-project staging daha az operasyon yukune karsilik tenant create rolunun
  project-geneli blast radius'ini ve mevcut Firestore ile veri paylasimini kabul
  eder; production oncesi izolasyon karari yeniden acilacaktir.
- Ilk altyapi kurulumu bootstrap ve statik secret seed adimlari gerektirir.
- Cloud Run create, secret degerleri Terraform state'e alinmadan seed
  edilebilsin diye iki asamali `deploy_runtime_services` kapisi kullanir.
- Agent yatay olceklemesi distributed lock gelene kadar sinirlidir.
- Production apply staging pilotu tamamlanana kadar kapsam disidir.
- Tam uygulama ve kabul plani
  [[google-cloud-production-foundation]] notunda tutulur.
