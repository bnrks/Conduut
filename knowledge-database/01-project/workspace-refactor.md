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

Sonuc: kok dizinden 7 binary takipten cikti (commit edilince repo yeni commit'lerde
temiz; geçmis hala tasir — kullanici tercihi). Degisiklikler staged, **commit
EDILMEDI** (kullanici onayina birakildi).

## Ertelenen kalemler (sonraki turlar)

- **Agent-yonerge konsolidasyonu** (ayri tur): `CLAUDE.md` 544 satir / 72 KB
  sismis (cogu eski oturum ozeti, her oturum context'e yukleniyor); kok
  `copilot-instructions.md` ile `.github/copilot-instructions.md` **iki FARKLI**
  untracked kopya; agent tanimlari uc yerde dagilmis (`.claude/agents/*.md`,
  `.codex/agents/*.toml`, `.agents/skills/`). Tek dogruluk kaynagi + harita gerek.
- **`.gitignore` satir 32 `*.md` blanket kurali** (riskli): knowledge-database
  haric TUM markdown'i yok sayiyor → `AGENTS.md`/copilot dosyalari izlenmiyor,
  gelecekte eklenecek herhangi bir `.md` (docs/ADR) **sessizce kaybolur**. Bu
  kurali degistirmek dogrudan agent-yonerge dosyalarinin tracking'ini etkiledigi
  icin agent-doc turuyla birlikte ele alinacak.
- **`README.md` bos** (sadece `# Conduut`) — icerik turu, temizlik degil; ertelendi.
- **Ic-katman bos dizinler**: `apps/agent/apps/` ve `apps/web/apps/` bos ic-ice
  dizinler (CLAUDE.md eksikler #13) — `apps/` turunda silinecek.
- **`docs/superpowers/` tracking tutarsizligi**: 6 spec/plan git'te izleniyor ama
  bazi CLAUDE.md notlari bunlari "gitignored/local" sayiyor — netlestirilecek.

Ilgili: [[current-state]], [[known-issues]], [[agent-instructions]].
