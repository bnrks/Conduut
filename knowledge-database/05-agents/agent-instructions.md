# Agent Instructions

Merkez: [[index]]

Bu not, repo icindeki farkli coding agent talimatlarini haritalar.

## Codex

Root `AGENTS.md`, Codex icin guncel rehberdir. Kod yazmadan once mevcut
worktree'nin kirli olabilecegi ve onceki Claude/Copilot degisikliklerinin
ezilmemesi gerektigi varsayilir.

Codex icin session baslangic sirasi zorunludur:

1. Root `AGENTS.md`.
2. `knowledge-database/index.md`.
3. Kullanici gorevine gore ilgili Obsidian dugumu.
4. Gerekli kaynak kod dosyalari.

Codex icin ana hafiza kurali: yaptigimiz her degisiklikten sonra ilgili
`knowledge-database` dugumu veya dugumleri guncellenir. Bu sadece buyuk
mimari kararlar icin degil; code, config, feature, bug fix, dokumantasyon,
debugging ve proje durumu degisiklikleri icin de gecerlidir. Gerekirse yeni
not eklenir, mevcut not duzenlenir ve notlar Obsidian wikilink'leriyle
birbirine baglanir.

Kullanici Conduut kodlarini sik sik okuyacak; amaci yapilan isi kontrol etmek,
anlamak ve proje hakimiyetini artirmaktir. Bu nedenle yeni veya degisen kodda
niyeti, veri akisini ya da sinir kosullarini anlamayi kolaylastiran kisa
aciklayici yorumlar tercih edilebilir. Yorumlar kodun zaten soyledigi seyi
tekrar etmemeli; ozellikle agent flow, auth, SSE stream, n8n side effect'leri,
Firestore scope'u, validation/retry davranisi ve MVP kisitlari gibi ileride
okurken yanlis anlasilabilecek noktalari isaret etmelidir.

## Claude

Root `CLAUDE.md`, onceki Claude Code oturumlarindan gelen en kapsamli guncel
ozeti icerir. Ozellikle 2026-04-13 tarihli n8n registry ve agent entegrasyonu
notlari onemlidir.

`.claude/agents` altinda rol bazli talimatlar bulunur:

- `backend.md`: Python/FastAPI servisleri.
- `frontend.md`: Next.js frontend.
- `infra.md`: Docker, Traefik, monitoring ve VPS yonetimi.

`.claude/skills` altinda tekrar kullanilabilir is akislari vardir:

- `setup-service`
- `api-endpoint`
- `db-migration`
- `docker-container`
- `n8n-node`
- `review`

Bu dosyalar tarihsel baglamdir; kullanmadan once mevcut kodla dogrula.

## Copilot

Iki Copilot talimat kaynagi var:

- Root `copilot-instructions.md`.
- `.github/copilot-instructions.md`.

Bunlar bazi yerlerde planlanan mimariyi veya eski dosya yollarini anlatir.
Ornegin `apps/control-plane` ve bazi `src/api/*` path'leri mevcut repo ile
uyusmayabilir. Bu nedenle Copilot notlari dogrudan kaynak gercek olarak
kullanilmamalidir.

## Obsidian Vault

`knowledge-database` agent'lar arasi kalici hafiza olmalidir. Kisa sureli
sohbet ozetleri yerine, gelecekte karar ve uygulama davranisini etkileyecek
bilgiler buraya yazilmalidir.

`index.md` vault'un merkezi hub notudur. Yeni sessionlarda once bu nottan
goreve uygun dugume gidilir.

Ilgili notlar: [[current-state]], [[known-issues]], [[system-architecture]].
