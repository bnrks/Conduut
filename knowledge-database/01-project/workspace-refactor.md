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

## Ertelenen kalemler (sonraki turlar)

- ~~Agent-yonerge konsolidasyonu~~ ✅ Faz 2'de yapildi (yukari bak).
- ~~`.gitignore` `*.md` blanket kurali~~ ✅ Faz 2'de kaldirildi.
- **`README.md` bos** (sadece `# Conduut`) — icerik turu, temizlik degil; ertelendi.
- **Ic-katman bos dizinler**: `apps/agent/apps/` ve `apps/web/apps/` bos ic-ice
  dizinler (CLAUDE.md eksikler #13) — `apps/` turunda silinecek.
- **`docs/superpowers/` tracking tutarsizligi**: 6 spec/plan git'te izleniyor ama
  bazi CLAUDE.md notlari bunlari "gitignored/local" sayiyor — netlestirilecek.

Ilgili: [[current-state]], [[known-issues]], [[agent-instructions]].
