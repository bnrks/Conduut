# Workspace Refactor (Disardan Ice)

Merkez: [[index]]

Kullanici workspace genelinde refactor + temizlik karari aldi (2026-06-29).
Yaklasim: **disardan ice** — once root dizin, sonra `apps/`, `packages/` vb.
Bu not turlari ve ertelenen kalemleri takip eder.

## Faz 1 — Root dizin temizligi (2026-06-29) ✅

Karar: buyuk/yanlis-yer binary'leri **git geçmisine dokunmadan** takipten cikar
(history rewrite YOK), tasi; bu tur yalniz dosya/dizin temizligi + `.gitignore`.
Agent-yonerge konsolidasyonu bilincli olarak ertelendi.

Yapilanlar:
- `conduut1.png`..`conduut5.png` (~24 MB) → `git rm --cached` + `brand/concepts/`'e
  tasindi (brand/concepts gitignore'da). Kodda/compose'da referans yoktu.
- `workflow-batch-run-test.xlsx` → `git rm --cached` + `apps/agent/tests/fixtures/`'e
  tasindi. **Hicbir otomatik test kullanmiyor** (tek `.xlsx` referansi frontend
  `accept` attribute'u); manuel batch-run ornek dosyasi.
- `conduut-claude-code-config.tar.gz` → `git rm --cached`, kokte birakildi (ignored).
  Kullanici config yedegi; silinmedi.
- `.gitignore`'a eklendi: `.ruff_cache/`, `brand/concepts/`, `*.xlsx`, `*.tar.gz`.

Sonuc: kok dizinden 7 binary takipten cikti. Yerel main'e commit + ff-merge
edildi (`0d6f973`); push EDILMEDI.

## Faz 2 — Agent-yonerge konsolidasyonu (2026-06-29) ✅

Karar: **AGENTS.md tek kanonik kaynak + CLAUDE.md ince pointer + history arsive**;
ayrica cift/stale dosyalari sil ve `.gitignore *.md` blanket kuralini duzelt.

Yapilanlar:
- **AGENTS.md** (root) tum coding agent'lar icin kanonik rehbere donustu
  (Codex'e ozel cerceve genellestirildi). Stale gercekler duzeltildi: silinen
  `.github` referansi, BYO LLM/providers/favorites (ADR-0011 ile kaldirilmisti),
  eklenen `fetch_credentials.py` operasyonel adimi. **Artik git'te izleniyor**
  (`*.md` kurali kalkinca).
- **CLAUDE.md** 553 satir → ~55 satir **ince pointer**: AGENTS.md +
  knowledge-database'e yonlendirir, zorunlu hafiza kurali + hizli dogrulama
  komutlari. Tam eski icerik arsivde:
  `knowledge-database/99-archive/claude-md-snapshot-2026-06-29.md` (552 satir,
  hicbir sey kaybolmadi). CLAUDE.md artik "son oturum ozeti" gunlugu tutmaz.
- **Silindi:** root `copilot-instructions.md` (stale, Copilot terk edildi;
  `.github/copilot-instructions.md`'yi kullanici zaten silmisti) ve `.agents/skills/`
  (`.claude/skills/`'in 6/6 birebir kopyasi). Her ikisi untracked'ti.
- **`.gitignore`:** riskli `*.md` blanket + `!knowledge-database/**` negasyonu +
  `copilot-instructions.md` kurali kaldirildi; `serviceAccount.json`, Obsidian
  workspace ve claude-mem stub ignore'lari korundu.
- Meta-haritalar guncellendi: `05-agents/agent-instructions.md` (yeniden yazildi),
  vault `knowledge-database/AGENTS.md`.

Not (ertelenen mikro-is): eski "Onemli dosyalar" dosya-haritasi (CLAUDE.md'de
~45 satir) simdilik yalniz arsivde; istenirse [[agent-service]] notuna canli
referans olarak tasinabilir.

## Faz 3 — apps/agent temizlik + refactor (2026-06-30) ✅

Bag­lam: en buyuk servis (`apps/agent`, 238 dosya). 3 paralel read-only analiz
subagent'i (olu-kod/kullanim izleme, kaynak yapi, test/tooling) ile haritalandi;
karar **tam paket**, davranis korunarak, her faz ayri commit + `ruff`+`pytest`
gate. Baseline **400 passed / 5 Windows-tmp errors** → bitis **381 passed / 0
errors** (24 test compiler'larla kasitli kaldirildi; 5 eski hata C3'te cozuldu).

- **Phase A** (`17ef06c`) — olu/clutter sil: `loop.py` (vestigial shim, 0 importer),
  bos `src/services/` + `src/agent/workflow_intent/`, `.ruff_cache`/`egg-info`/`evals/`/
  dead `.xlsx`; `data/.gitignore`'a `credentials.json` (gercek ignore boslugu);
  Dockerfile yorumu (fetch adimlari).
- **Phase D** (`987bd95`) — superseded IR compiler'lari kaldir: `graph_compiler.py`
  (723) + `blocks.py` (243) + `spec_compiler.py` (977) + test'leri + `tools/__init__`
  vestigial re-export + `schemas.py` olu IR tipleri (WorkflowPlan/Spec/ActionSpec/
  StepSpec/TriggerSpec/GraphNode/GraphEdge/WorkflowGraph) + `actions.py`
  `provision_spreadsheet_for_workflow`. ADR-0010 ile 2+ haftadir model yuzeyinde
  degildi; ~2200 satir olu kod. (`PlatformActionPlan`/`WorkflowInputField`/
  `WorkflowOutputField` canli, korundu.)
- **Phase B1** (`d5d7d6c`) — `store.py` (1067) → `store/` paketi (7 modul,
  koleksiyon-bazli, re-export `__init__` ile **0 cagri-yeri degisimi**); dead
  `workflow_credentials` cluster dusuruldu. Public isim yuzeyi diff'le dogrulandi.
- **Phase B2** (`b1d95a8`) — `tools/validation.py` → `tools/build_pipeline.py`
  (gercekte build pipeline; core `agent/validation.py` ile isim cakismasi);
  `_iter_connection_targets` dedup (core'dan import).
- **Phase B3** (`bd72a46`) — runner history blogu → `agent/history.py` (saf
  fonksiyonlar; runner'a re-import → `runner.<name>` ve testler degismeden calisir).
  runner.py 796→609.
- **Phase C3** (`918964c`) — **5 pre-existing Windows-tmp hatasi cozuldu** (yeni
  `tests/conftest.py`): (1) autouse fixture `configure_logging`'in sizdirdigi
  `RotatingFileHandler`'i her testten sonra kapatir (kok-neden: acik handle dosyayi
  kilitleyip tmp_path temizligini bozuyordu); (2) `PYTEST_DEBUG_TEMPROOT` projeye-ozel
  sistem-temp alt-dizinine yonlendirilir (kilitli paylasilan `pytest-of-<user>`
  dizininden kacar, repo disi). Suite ilk kez tam yesil.
- **Phase C1** (`93eda21`) — `test_tools.py` (2042) → 4 odakli dosya
  (`test_workflow_build` 12, `test_workflow_runner` 9, `test_readiness_connections`
  14, `test_presentation` 9 = 44 test, verbatim tasindi).

**Ertelenen — Phase C2** (test-helper dedup): genis 62-site `monkeypatch`
(n8n/store fake) + `AgentDeps` (25×) + fake-Firestore dedup'i **bilincli ertelendi**.
Gerekce: saf cleanup (davranis/dogruluk kazanci yok), yuksek churn, ve "birebir
ayni" denilen fake sinflari aslinda varyantli (artifact `_FakeDocRef.get` farkli)
→ guvenli dedup riske/efora degmez. conftest zaten C3'te gercek paylasilan altyapi
kazandi. Gelecek tur icin acik.

Notlar: CLAUDE.md #13'teki `apps/agent/apps/` bos ic-ice dizini **zaten yok**
(yalniz `apps/web/apps/` web turunda kontrol edilecek). `pytest-cache-files-*` (4)
Windows izin-kilidi yuzunden silinemedi (gitignored, zararsiz). Subagent-driven:
B1 + C1 backend subagent'lara devredildi (kesin spec + pytest-gate), sonuclar
re-export/isim-diff ile **bagimsiz dogrulandi** + her faz yerel pytest ile teyit.

## Faz 4 — docs/ turu (2026-06-30) ✅

Karar: `docs/superpowers/` spec+plan dosyalari **tamamlanmis calisma taslagi**;
kalici karar zaten ADR'lerde → git'e alinmaz (kullanici onayi). docs/ disinda
baska icerik yok.

Yapilanlar:
- Kural-oncesi commit'lenmis **6 spec/plan dosyasi takipten cikarildi**
  (`git rm --cached`); `docs/superpowers/` Faz 2 ignore kuralinda kaldi → 20
  dosyanin tamami uniform yerel. Yerel kopyalar diskte korundu.
- **Dangling ADR/not linkleri sadelestirildi**: adr-0016, adr-0017, [[web-app]],
  [[agent-platform-self-awareness]], [[model-cost-research-2026-06]]'daki
  `Spec:/Plan: docs/...` pointer'lari kaldirildi (artik git'te olmayan dosyalara
  isaret ediyorlardi; karar ADR govdesinde duruyor). 99-archive snapshot'ina
  dokunulmadi (donmus tarihsel kayit).

## Faz 5 — knowledge-database temizlik (2026-06-30/07-01) ✅

Karar: kullanici "en onemli yer" dedi → dogruluk onceligi, icerik kaybetmeden.
Uc workstream:

**KB-1 — organizasyon:** yanlis-yazimli `03-desicions/` → `03-decisions/` rename
(kurallarin bekledigi "ozel migration"; AGENTS.md / CLAUDE.md / vault AGENTS.md
path ref'leri guncellendi; wikilink'ler basename oldugu icin etkilenmedi).
Root-seviye notlar klasorlendi: `model-cost-research` + `claude-vs-deepseek` →
`08-research/`; `agent-platform-self-awareness` → `02-architecture/`; parked
`new-engine-plan` → `99-archive/`. Root artik yalniz `index.md` + `AGENTS.md`.

**KB-2 — graph hijyeni:** tek gercek kirik wikilink duzeltildi (`known-issues`
`[[per-user-container-credentials]]` aslinda Claude-memory dosyasiydi, vault notu
degil → duz referans). Kalan "kirik"lar false-positive (JSON ornekleri, arsivdeki
`new-engine-plan` basename ile cozulur, `[[not-adi]]` placeholder).

**KB-3 — staleness reconcile (tam):** ADR'ler haric 8 icerik notu guncel kodla
hizalandi (subagent-destekli + review; bir subagent sonda stall etti ama edit'leri
tamamdi — bitirdim/dogruladim):
- `current-state.md`, `agent-service.md` (derin — IR compiler / BYO / settings
  bolumleri "DIKKAT" blockquote'lariyla tarihsellendi), `chat-workflow-generation.md`,
  `system-architecture.md`, `web-app.md`, `feature-backlog.md`, `known-issues.md`
  + `issue-backlog.md` (cozulen/obsolete issue'lar isaretlendi, gercekten acik
  olanlar korundu — orn. per-user credential injection).
- Superseded ADR'ler net isaretlendi: [[adr-0005-workflow-spec-compiler]],
  [[adr-0008-typed-workflow-intent-engine]], [[adr-0009-workflow-graph-compiler]]
  (hepsi [[adr-0010-json-surface-repair-normalizer]] tarafindan). `index.md`
  Kararlar girisleri de guncellendi.
- Markdown hijyeni: liste-item gibi render olan wrapped `+ ` satirlari duzeltildi
  (adr-0012, known-issues, model-cost-research, chat-workflow-generation).

Not: `.claude/settings.local.json`'daki eski `03-desicions/**` Read-permission
glob'u local/gitignored — dokunulmadi (en fazla bir kez yeniden izin sorar).

## Faz 6 — packages/ turu (2026-07-01) ✅

Kapsam: `packages/n8n-registry` (tek paket; planlanan `packages/shared` yok).
Paket zaten saglikli/iyi-yapili (1331 satir, 9 test yesil) → cleanup minor:
- **Clutter:** `.ruff_cache` + stale `src/n8n_registry.egg-info` silindi (ignored;
  `pytest-cache-files-*` Windows izin-kilitli, birakildi).
- **Olu kod (~18 satir):** `NodeRegistry.is_loaded` property + `_loaded` field +
  `load_from_files` metodu kaldirildi. Hicbir cagiran yoktu (agent
  `initialize_from_n8n` kullaniyor; `load_from_files` docstring'i "test/offline"
  diyordu ama testler de kullanmiyordu). Monorepo-ici paket → kullanilmayan
  public API = olu.
- **Tutarlilik:** `CredentialTypeInfo` `__init__.__all__`'a eklendi (agent zaten
  `n8n_registry.models`'den import ediyordu); stale `tools.py` yorumu → `tools paketi`.
- Not: `data/credentials.json` gitignore boslugu zaten Faz 3'te kapatilmisti.

Dogrulama: n8n-registry 9 passed, agent 381 passed (bagimli suite), ruff temiz.

## Ertelenen kalemler (sonraki turlar)

- ~~Agent-yonerge konsolidasyonu~~ ✅ Faz 2'de yapildi (yukari bak).
- ~~`.gitignore` `*.md` blanket kurali~~ ✅ Faz 2'de kaldirildi.
- **`README.md` bos** (sadece `# Conduut`) — icerik turu, temizlik degil; ertelendi.
- **Phase C2 (test-helper dedup)** — Faz 3'te bilincli ertelendi (yukari bak);
  dusuk-getiri/yuksek-churn, gelecek tur icin acik.
- ~~`agent-service.md` derin reconcile~~ ✅ Faz 5 (KB-3)'te tamamlandi.
- **Ic-katman bos dizinler**: `apps/agent/apps/` **zaten yok** (Faz 3'te dogrulandi);
  `apps/web/apps/` web turunda kontrol edilecek (CLAUDE.md eksikler #13).
- ~~`docs/superpowers/` tracking tutarsizligi~~ ✅ Faz 4'te cozuldu (uniform yerel).

Ilgili: [[current-state]], [[known-issues]], [[agent-instructions]].
