# Conduut — Claude Code Rehberi

Conduut, kullanıcıların AI agent ile sohbet ederek n8n workflow'ları oluşturmasını sağlayan bir platformdur.

> **Bu dosya kasıtlı olarak incedir.** Tüm coding agent'lar için **kanonik proje
> rehberi `AGENTS.md`**'dir: proje yapısı, teknoloji kararları, kodlama kuralları,
> doğrulama komutları, mimari kurallar ve operasyonel notlar oradadır. **Önce onu oku.**

---

## Oturum başlangıç protokolü

1. **`AGENTS.md`** — kanonik repo rehberi (gerçek durum, kurallar, komutlar).
2. **`knowledge-database/index.md`** — kalıcı proje hafızası (Obsidian vault hub).
   Görevle ilgili notu buradan seç ve **iş yapmadan önce** aç
   (ör. mimari için [[system-architecture]], agent için [[agent-service]],
   kararlar için ilgili `adr-*`, devam eden temizlik için [[workspace-refactor]]).
3. Göreve özgü kaynak dosyalar.

@knowledge-database/index.md

---

## Hafıza güncelleme kuralı (zorunlu)

Her önemli değişiklikten (feature, bug fix, mimari karar, test sonucu, config) sonra
ilgili `knowledge-database` notunu **aynı görevde** güncelle. Gerekirse yeni not aç ve
Obsidian wikilink (`[[not-adı]]`) ile `index.md`'ye bağla. Yeni ADR'leri
`03-decisions/` klasörüne ekle.
Notlar Türkçe öncelikli, teknik tanımlayıcılar İngilizce.

**Bu dosya artık oturum-oturum "son oturum özeti" günlüğü TUTMAZ.** O kronoloji ve
eski "Önemli dosyalar" haritası knowledge-database'e taşındı; inceltme öncesi tam
geçmiş arşivde: `knowledge-database/99-archive/claude-md-snapshot-2026-06-29.md`.
Oturum çıktısını ve önemli değişiklikleri knowledge-database notlarına yaz, bu dosyayı
tekrar şişirme.

---

## Doğrulama komutları (hızlı referans)

- Frontend: `cd apps/web && pnpm lint && pnpm exec tsc --noEmit`
  (web paketinde `test`/`typecheck` npm script'i yok; açık komutları kullan.)
- Python servisleri: `cd apps/{servis} && ruff check . && ruff format --check . && pytest`
- n8n registry: `cd packages/n8n-registry && ruff check .`
- Tüm proje: `docker compose config` ve `docker compose build`

---

## Referans dokümanlar

- **`AGENTS.md`** — kanonik agent rehberi (önce bunu oku).
- `knowledge-database/` — kalıcı proje hafızası: ADR'ler (`03-decisions/`),
  feature notları, mimari, mevcut durum. Merkez: `knowledge-database/index.md`.
- `PROJECT.md` — uzun vadeli ürün/mimari vizyon (DB şeması, akışlar, maliyet).
- `BRAND.md` — renk paleti, font, logo.
