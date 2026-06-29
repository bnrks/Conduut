# Agent Instructions

Merkez: [[index]]

Bu not, repo icindeki coding-agent talimatlarini haritalar. 2026-06-29 workspace
refactor Faz 2'de **konsolide edildi** (bkz. [[workspace-refactor]]): tek kanonik
rehber + ince Claude pointer; cift/stale dosyalar kaldirildi.

## Kanonik rehber: AGENTS.md

Root `AGENTS.md` artik **tum coding agent'lar** (Claude Code, Codex, ...) icin
kanonik repo rehberidir. Proje yapisi, teknoloji kararlari, kodlama kurallari,
dogrulama komutlari, mimari kurallar ve operasyonel notlar oradadir. Kod yazmadan
once mevcut worktree'nin kirli olabilecegi ve onceki degisikliklerin ezilmemesi
gerektigi varsayilir.

Her agent icin session baslangic sirasi:

1. Root `AGENTS.md`.
2. `knowledge-database/index.md`.
3. Kullanici gorevine gore ilgili Obsidian dugumu.
4. Gerekli kaynak kod dosyalari.

## Ana hafiza kurali (tum agent'lar)

Yaptigimiz her degisiklikten sonra ilgili `knowledge-database` dugumu veya
dugumleri **ayni gorevde** guncellenir. Bu sadece buyuk mimari kararlar icin
degil; code, config, feature, bug fix, dokumantasyon, debugging ve proje durumu
degisiklikleri icin de gecerlidir. Gerekirse yeni not eklenir, mevcut not
duzenlenir ve notlar Obsidian wikilink'leriyle birbirine baglanir.

Kullanici Conduut kodlarini sik sik okuyacak; amaci yapilan isi kontrol etmek,
anlamak ve proje hakimiyetini artirmaktir. Bu nedenle yeni veya degisen kodda
niyeti, veri akisini ya da sinir kosullarini anlamayi kolaylastiran kisa
aciklayici yorumlar tercih edilebilir. Yorumlar kodun zaten soyledigi seyi tekrar
etmemeli; ozellikle agent flow, auth, SSE stream, n8n side effect'leri, Firestore
scope'u, validation/retry davranisi ve MVP kisitlari gibi ileride yanlis
anlasilabilecek noktalari isaret etmelidir.

## Claude Code

Root `CLAUDE.md` artik **ince bir pointer**: AGENTS.md + `knowledge-database/index.md`'ye
yonlendirir, zorunlu hafiza kuralini ve hizli dogrulama komutlarini tutar. Eski
oturum-oturum "son oturum ozeti" gunlugu ve "Onemli dosyalar" haritasi arsive
tasindi: `knowledge-database/99-archive/claude-md-snapshot-2026-06-29.md`.

`.claude/` altinda Claude Code tooling'i:

- `.claude/agents/`: rol bazli subagent tanimlari — `backend.md`, `frontend.md`,
  `infra.md`.
- `.claude/skills/`: tekrar kullanilabilir is akislari — `setup-service`,
  `api-endpoint`, `db-migration`, `docker-container`, `n8n-node`, `review`.

`.codex/agents/` altinda ayni 3 rolun Codex karsiligi (`*.toml`) bulunur.

## Kaldirilanlar (2026-06-29 Faz 2)

- **Copilot talimatlari**: root `copilot-instructions.md` ve `.github/copilot-instructions.md`
  silindi (Copilot terk edildi; ayrica stale — Next 14, control-plane, eski LLM
  mimarisi anlatiyorlardi).
- **`.agents/skills/`**: `.claude/skills/`'in birebir kopyasiydi; silindi (gercek
  kaynak `.claude/skills/`).
- Riskli `.gitignore` `*.md` blanket kurali kaldirildi → AGENTS.md ve docs artik
  normal izlenir.

## Obsidian Vault

`knowledge-database` agent'lar arasi kalici hafizadir. Kisa sureli sohbet ozetleri
yerine, gelecekte karar ve uygulama davranisini etkileyecek bilgiler buraya
yazilir. `index.md` vault'un merkezi hub notudur; yeni session'larda once buradan
goreve uygun dugume gidilir.

Ilgili notlar: [[workspace-refactor]], [[current-state]], [[known-issues]],
[[system-architecture]].
