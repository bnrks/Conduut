---
name: db-migration
description: "Alembic migration oluşturur. Tablo ekleme, sütun değiştirme, indeks oluşturma."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Veritabanı migration: $ARGUMENTS

$ARGUMENTS olarak verilen değişikliği uygulayan bir Alembic migration oluştur.

## Adımlar

1. Mevcut modelleri oku (apps/{servis}/src/models/)
2. SQLAlchemy modelini güncelle veya oluştur
3. Migration oluştur: `cd apps/{servis} && alembic revision --autogenerate -m "$ARGUMENTS"`
4. Oluşan migration dosyasını kontrol et (upgrade + downgrade)
5. Migration'ı çalıştır: `alembic upgrade head`
6. Doğrula: `alembic current`

## Kurallar

- Her migration dosyasında downgrade fonksiyonu olmalı (geri alınabilir)
- UUID primary key kullan (gen_random_uuid)
- TIMESTAMPTZ kullan (timezone-aware)
- İndeksleri unutma (foreign key'ler, sık sorgulanan sütunlar)
- Enum değerleri PostgreSQL native ENUM yerine VARCHAR kullan (migration kolaylığı)
- Mevcut verileri bozmayacak şekilde migration yaz (nullable ekle, sonra backfill, sonra not null)
