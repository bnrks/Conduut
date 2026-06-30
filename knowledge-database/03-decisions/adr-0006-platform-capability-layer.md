# ADR-0006: Platform Capability Layer ve Google V1

Merkez: [[index]]

## Durum

Kabul edildi.

## Baglam

Conduut'un urun yonu yalnizca "n8n workflow builder" olmak degil, kullanicinin
bagladigi platformlari chat uzerinden yoneten bir agent olmaktir. n8n bu
modelde kalici otomasyonlari calistiran adapter/execution backend'lerinden
biridir. Agent'in Gmail veya Sheets gibi servislerde hem anlik islem yapmasi
hem de ayni capability'leri workflow'a donusturmesi gerekir.

Eski modelde Google connection metadata'si `google.gmail.send`,
`google.sheets.write` gibi genis capability etiketleri ve n8n credential id'si
tasiyordu. Bu, "Sheet ID yoksa agent neden olusturamiyor?" gibi urun
beklentilerini karsilamiyordu; agent direct API token'ina sahip olmadigi icin
n8n workflow disindaki platform operasyonlarini yapamiyordu.

## Karar

Backend'e platform capability registry eklendi. Registry capability, scope,
risk, confirmation ihtiyaci, direct API destegi ve workflow destegini merkezi
olarak tanimlar. Google V1 kapsaminda Gmail ve Sheets desteklenir.

Canonical capability adlari servis aksiyonuna gore ayrildi:

- `gmail.message.send`, `gmail.message.read`, `gmail.message.modify`,
  `gmail.message.trash`, `gmail.message.delete_permanently`.
- `sheets.spreadsheet.create`, `sheets.sheet.manage`, `sheets.range.read`,
  `sheets.range.update`, `sheets.range.clear`, `sheets.row.append`.

Kullaniciya tek tek scope yerine permission pack gosterilir:

- Gmail: `gmail.basic`, `gmail.send`, `gmail.read`, `gmail.organize`,
  `gmail.full_control`.
- Sheets: `sheets.app_files`, `sheets.full_access`.

Google OAuth authorize route'u `permission_pack` veya
`requested_capabilities` alabilir. Callback mevcut n8n credential yaratma
davranisini korur; ayrica `CONDUUT_CONNECTION_ENCRYPTION_KEY` varsa Google
refresh token'i sifrelenip Firestore connection metadata'sina yazilir ve
`direct_api_enabled=true` olur. Env yoksa direct API kapali kalir, fakat n8n
credential tabanli workflow davranisi bozulmaz.

Agent tool set'ine `run_platform_action` eklendi. Bu tool direct Gmail/Sheets
client'larini kullanarak anlik platform islemleri yapar; eksik izin varsa
side-effect olmadan `oauth_prompt` dondurur. Platform action audit log'u
`users/{uid}/platform_action_audit/{id}` altina payload veya secret saklamadan
servis, capability, hedef resource, durum, request id ve zaman bilgisi yazar.

`create_workflow_from_plan` artik Sheets append planinda spreadsheet bilgisi
yoksa, `spreadsheet_title` gibi niyet parametresi varsa direct Sheets API ile
spreadsheet'i bir kez olusturur, olusan id'yi workflow planina enjekte eder ve
workflow metadata `resources` alaninda saklar. Boylece workflow her run'da yeni
Sheet olusturmaz.

Frontend Connections sayfasi servis kartlarinda permission pack yonetimini
gosterir. Chat `oauth_prompt` attachment'i `requiredCapabilities`,
`permissionPack` ve `riskLevel` tasiyabilir; web authorize BFF route'u bu
bilgileri agent'a iletir.

## Sonuclar

- Agent platform yonetimi icin n8n'e bagimli kalmaz; direct action ve workflow
  compiler ayni capability registry'den beslenir.
- n8n credential auto-attach geriye donuk korunur; eski
  `google.gmail.*`/`google.sheets.*` capability etiketleri alias olarak
  desteklenir.
- Destructive aksiyonlar risk/confirmation metadata'siyle ayrilir. Gmail
  permanent delete default akista yoktur; trash/modify daha dusuk riskli
  aksiyonlardir.
- MVP token saklama encrypted Firestore'dur. Production'da Vault veya Secret
  Manager'a tasima gerekecek.
- Google Drive tam dosya yonetimi bu karar kapsaminda degildir; Sheets
  `drive.file` ve Sheets API scope'lari yalnizca Sheets V1 icin kullanilir.

Ilgili notlar: [[agent-service]], [[chat-workflow-generation]],
[[system-architecture]], [[dashboard]].
