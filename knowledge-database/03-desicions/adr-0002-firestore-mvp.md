# ADR 0002: Firestore MVP

Merkez: [[index]]

## Durum

Accepted for MVP.

## Baglam

`PROJECT.md` uzun vadede PostgreSQL 16, pgvector ve pgcrypto/Vault yaklasimini
onerir. Mevcut uygulama Firebase auth ile uyumlu sekilde Firestore kullaniyor.

## Karar

MVP'de app state Firestore'da tutulur:

- Conversations.
- Messages.
- Aktif LLM settings.
- Provider API key baglantilari.
- Favorite modeller.

Kod merkezi: `apps/agent/src/store.py`.

## Sonuclar

Avantajlar:

- Firebase auth ile hizli entegrasyon.
- MVP icin migration ve DB operasyon maliyeti dusuk.
- Conversation ve nested message modeli kolay.

Riskler:

- Provider API key'leri Firestore'da plain field olarak tutuluyor.
- Query ve transaction modeli ileride usage/billing icin sinirlayici olabilir.
- PostgreSQL/pgvector RAG hedefine geciste migration gerekecek.

## Sonraki Adim

Production'a yaklasirken credential saklama ayrilmali: en azindan encrypted
storage, idealde Vault veya baska secret manager. PostgreSQL'e gecis planlanirsa
Firestore koleksiyon semasi migrasyon notu olarak kaydedilmeli.

Ilgili notlar: [[agent-service]], [[system-architecture]], [[known-issues]].
