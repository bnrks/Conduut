---
name: api-endpoint
description: "Mevcut bir FastAPI servisine yeni endpoint ekler. Route, schema, service ve test dosyalarını oluşturur."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# API endpoint ekle: $ARGUMENTS

$ARGUMENTS olarak verilen servis ve endpoint bilgisine göre (örn: "agent POST /api/workflows") gerekli dosyaları oluştur.

## Adımlar

1. İlgili servisin mevcut route'larını oku (apps/{servis}/src/routes/)
2. Pydantic request/response şemalarını oluştur (apps/{servis}/src/schemas/)
3. Service layer fonksiyonunu yaz (apps/{servis}/src/services/)
4. Route dosyasına endpoint'i ekle
5. main.py'deki router include'ları güncelle (gerekirse)
6. Test yaz (apps/{servis}/tests/)

## Kurallar

- Her endpoint'in Pydantic şeması olmalı (request + response)
- Service layer iş mantığını taşır, route sadece yönlendirir
- Dependency injection: veritabanı session, mevcut kullanıcı vb. Depends() ile
- HTTP status code'ları doğru kullan (201 create, 204 delete, 404 not found)
- Hata durumları için HTTPException
- Docstring: ne yapar, ne döndürür

Endpoint'i oluşturduktan sonra `cd apps/{servis} && ruff check . && pytest -x` ile doğrula.
