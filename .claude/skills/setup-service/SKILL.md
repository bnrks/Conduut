---
name: setup-service
description: "Yeni bir FastAPI mikroservis iskeleti oluşturur. Dockerfile, pyproject.toml, temel dosya yapısı ve health check endpoint'i ile."
allowed-tools: Read, Write, Edit, Bash
---

# Yeni servis oluştur: $ARGUMENTS

apps/$ARGUMENTS/ altında bir FastAPI mikroservis iskeleti kur.

## Oluşturulacak dosyalar

1. `apps/$ARGUMENTS/pyproject.toml` — ruff, pytest, bağımlılıklar (fastapi, uvicorn, pydantic, sqlalchemy, httpx, structlog)
2. `apps/$ARGUMENTS/src/__init__.py`
3. `apps/$ARGUMENTS/src/main.py` — FastAPI app, lifespan, CORS, health endpoint
4. `apps/$ARGUMENTS/src/config.py` — Pydantic BaseSettings (env variables)
5. `apps/$ARGUMENTS/src/models/__init__.py`
6. `apps/$ARGUMENTS/src/schemas/__init__.py`
7. `apps/$ARGUMENTS/src/routes/__init__.py`
8. `apps/$ARGUMENTS/src/services/__init__.py`
9. `apps/$ARGUMENTS/src/dependencies.py` — DB session, Redis bağlantısı
10. `apps/$ARGUMENTS/tests/__init__.py`
11. `apps/$ARGUMENTS/tests/test_health.py` — Health endpoint testi
12. `apps/$ARGUMENTS/Dockerfile` — Multi-stage build (python:3.12-slim)

## Kurallar

- Health endpoint: GET /health → {"status": "ok", "service": "$ARGUMENTS"}
- Config: tüm değerler env variable'dan (CONDUUT_ prefix)
- Structlog JSON loglama
- Async lifespan (startup/shutdown)

İskeleti oluşturduktan sonra `cd apps/$ARGUMENTS && pip install -e . && pytest` ile doğrula.
