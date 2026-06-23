# ADR-0014: Workflow Sandbox Test + Self-Repair

Merkez: [[index]]

## Durum

Kabul edildi (2026-06-23). Implemente edildi (feature/workflow-sandbox-test).
[[adr-0010-json-surface-repair-normalizer]]'ı tamamlar: repair.py build-zamanı
**yapısal** onarım yapar; bu ADR **davranışsal/runtime** doğrulama ekler. İkisi
ayrı katmandır, biri diğerinin yerine geçmez. İlgili: [[known-issues]],
[[agent-service]].

## Bağlam

Agent bir workflow oluşturduktan sonra, workflow'un **çalışınca hata verip
vermediğini** veya **anlamlı çıktı üretip üretmediğini** build-zamanında bilmiyordu.
Runtime/execution hatası için otomatik bir self-healing mekanizması yoktu:
`execute_workflow` hatayı modele döndürüyordu ama hatayı yakalayıp düzeltip
yeniden deneyen zorlayıcı bir döngü yoktu (prompt'ta da yoktu). 2026-06-18 canlı
testinde agent execution hatasından sonra `MAX_MODEL_REQUESTS` limitine takılıp
kendini düzeltemedi. Tüm execution bug'ları (boş mail, `$json[0]`,
resourceLocator) agent self-healing ile değil, geliştiricinin `repair.py`'ye
kural eklemesiyle çözüldü.

**Temel gerginlik (kullanıcı tespiti):** Bir workflow'un hata verip vermediğini
anlamak için onu **çalıştırmak** gerekir; ama çalıştırmak çoğu zaman **gerçek bir
yan etki** üretir (gerçek mail, gerçek satır). n8n'in yerel "dry-run/mock" modu
yoktur. Yani "uçtan uca tam çalıştır" ile "dışarıya hiçbir şey gitmesin" aynı
anda, ekstra altyapı olmadan mümkün değildir.

## Karar

Build'in son adımında, **dışarıya gerçek etki göndermeyen** bir sandbox test turu
çalıştırılır; hata veya boş/yanlış çıktı yakalanırsa agent **kendi içinde** (en
fazla 2 tur) onarır; düzeltilemezse workflow "needs_attention" işaretlenir ve
dürüstçe bildirilir.

1. **Nötralizasyon (Yöntem A).** Test turunda yan-etkili (aksiyon) node'lar
   `disabled=true` yapılır; n8n onları atlar (pass-through) → gerçek mail/yazma
   olmaz. Gerçek veri yolu (webhook→fetch→transform→expression) gerçekten çalışır.
   Sınıflandırıcı: bilinen action tipleri (gmail send, sheets write, slack,
   telegram, discord, drive, notion, airtable) + HTTP non-GET. (`sandbox_nodes.py`)
2. **Klon-temelli izolasyon.** Gerçek workflow'a asla `disabled` sızmaz: workflow
   klonlanır (geçici n8n workflow), nötralize edilir, çalıştırılır ve **her
   durumda silinir** (`finally`). Manual/GET trigger in-memory webhook POST'a
   çevrilir; yalnız-schedule → test edilemez (skip).
3. **3 katmanlı geçme kriteri.** (a) çalışan hiçbir node hata atmadı; (b) nötralize
   edilen aksiyon node'una giden üst-çıktı boş değil (deterministik, yanlış-pozitif
   yok; belirsiz ifade çözümü LLM'e devredilir); (c) **LLM yargısı** — sabit ucuz
   Gemini Flash (`research.py` deseni, provider-bağımsız) niyet + would-be çıktıyı
   görüp "anlamlı sonuç üretir mi?" der.
4. **Self-repair döngüsü (ModelRetry).** Test başarısızsa bulgular yapılandırılmış
   `ModelRetry` ile modele geri beslenir → model `update_workflow` ile düzeltir →
   tekrar test. Bütçe `ctx.deps.workflow_test_attempts[workflow_id]` sayacıyla
   **en fazla 2 deneme**; gerçek bound budur (Agent `retries=4` sadece headroom).
   Bütçe dolunca `ModelRetry` atılmaz; `test_status="needs_attention"` + bulgu
   döner, agent durur ve kullanıcıya dürüstçe söyler.
5. **Tetikleme.** `create_workflow`/`update_workflow` sonunda, readiness temizse
   (eksik credential yok) ve `awaiting_user_input=false` ise otomatik koşar
   (`_should_run_sandbox_test` + `_test_and_gate`). Eksik credential varsa test'e
   hiç gelinmez (mevcut readiness gate önce çalışır).
   **Test-before-execute (2026-06-23 eklendi):** `execute_workflow` de gerçek
   çalıştırmadan önce, workflow daha önce test geçmemişse (`test_status != "passed"`,
   `_needs_pretest`) sandbox testini koşar. Bu, **kapsama boşluğunu** kapatır:
   create credential-blocked olunca test atlanıyordu, credential eklenince agent
   `update_workflow` yerine doğrudan `execute_workflow` çağırıp testi tamamen
   baypas ediyordu (canlı logda iki ardışık çalışmada gözlendi, 2026-06-23).
   Pretest başarısızsa `_test_and_gate` ile ModelRetry/self-repair; bütçe
   tükenirse gerçek execution **bloklanır** (needs_attention, çalıştırılmaz).
   `ModelRetry` execute_workflow'un generic `except`'i tarafından yutulmasın diye
   `except ModelRetry: raise` ile yeniden fırlatılır.
6. **Test harness'ı build'i bloklamaz.** Sandbox içindeki herhangi bir exception
   yakalanır, build normal sonucuyla döner.

## Sonuçlar

**Olumlu:** Geçmiş "boş mail" sınıfı bug'lar (üst node boş üretir) artık build
sırasında, gerçek mail gönderilmeden yakalanır ve agent kendi içinde düzeltir.
Yeni altyapı gerektirmez (mevcut tek shared n8n). LLM yargısı ifade-çözümleme
muhakemesini kapatır.

**Sınırlar / non-goals (V1):**
- **Gerçek API-tarafı hataları kapsam dışı** (auth reddi, uzak 4xx/5xx) — bunlar
  nötralize edilen node'un içinde olur; readiness/credential kontrolleri + gerçek
  ilk çalıştırma kapsar.
- **Echo-stub (Yöntem B) yok.** Bilinen platformların kilit param ifadelerini Set
  node ile çözüp birebir resolved değer görmek (en net "boş mail" tespiti) ileride
  curated+generic desenle eklenebilir.
- **Yalnız-schedule / çoklu-trigger** workflow'lar auto-test edilmez (skip).
- **Maliyet/gecikme:** her tamamlanmış build bir test turu (gerçek n8n execution +
  LLM yargısı) + olası onarım turları üretir; gate bunu yalnız tamamlanmış
  build'lerle sınırlar.
- **Frontend rozeti** (`test_status` dashboard'da) bu fazda yok; `test_status`
  Firestore metadata `resources` altında saklanır, rozet ayrı follow-up.

## İlgili dosyalar

- `apps/agent/src/agent/sandbox.py` — test motoru: örnek girdi, test-klonu,
  boş-çıktı kontrolü, LLM yargısı (`_run_judge_llm` izole), orkestrasyon
  (`run_sandbox_test`), `SandboxTestResult`.
- `apps/agent/src/agent/sandbox_nodes.py` — aksiyon-node sınıflandırıcı +
  `neutralize_action_nodes`.
- `apps/agent/src/agent/tools/sandbox_gate.py` — `_test_and_gate` + 2-deneme
  ModelRetry döngüsü + needs_attention/repair talimatları.
- `apps/agent/src/store.py` — `save_workflow_test_status` (metadata resources).
- `apps/agent/src/agent/tools/factory.py` — create/update entegrasyonu,
  `_should_run_sandbox_test`, `retries=4`, **`_needs_pretest` + execute_workflow
  test-before-execute wiring + `except ModelRetry: raise`**.
- Testler: `test_sandbox_nodes.py`, `test_sandbox.py`, `test_sandbox_gate.py`,
  `test_store_test_status.py`. **292 passed (5 Windows-tmp hatası alakasız); ruff temiz.**

## Canlı doğrulama (2026-06-23)

- **Sandbox motoru + n8n entegrasyonu:** `run_sandbox_test` gerçek n8n'e (:6180)
  karşı doğrudan çalıştırıldı. Boş senaryo → `passed=False` + boş-çıktı bulgusu;
  sağlıklı senaryo → `passed=True` (gerçek Gemini judge OK). HTTP node klonda
  `disabled:True` (dışarı çağrı yok), klonlar silindi, artık kalmadı. ✅
- **Canlı chat akışında bulunan kapsama boşluğu:** Kullanıcı iki ardışık görev
  çalıştırdı; ikisinde de workflow credential-blocked create → attach → doğrudan
  execute oldu. Sandbox testi **hiç tetiklenmedi** (logda 0 sandbox olayı). →
  **test-before-execute** eklendi (yukarı, Karar #5). Ayrıca her iki görevdeki
  asıl hata **Gmail OAuth refresh token süresi dolmuş** idi — sandbox'ın disable
  ettiği node'un auth hatası, yani V1 non-goal; sandbox bunu yakalamaz.

## Bekleyen

test-before-execute'in canlı doğrulaması: credential-ready / data-transform bir
workflow'da kasıtlı yapısal hata (boş gövde) → execute öncesi sandbox yakalar →
agent onarır. (Gmail auth hataları kapsam dışı kalmaya devam eder.)
