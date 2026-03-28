---
name: docker-container
description: "n8n Docker container yapılandırması — Dockerfile, compose, izolasyon kuralları, kaynak limitleri."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# Docker container yapılandırması: $ARGUMENTS

n8n kullanıcı container'ları ile ilgili Docker dosyalarını oluşturur veya günceller.

## Conduut container kuralları (her zaman uygula)

```bash
# Zorunlu kısıtlamalar
--cpus=0.5
--memory=256m
--memory-swap=512m
--pids-limit=100
--network n8n-isolated          # internal, internet yok
--security-opt no-new-privileges
--cap-drop ALL
--read-only
--tmpfs /tmp:rw,size=100m
--restart unless-stopped

# n8n env variables
N8N_BASIC_AUTH_ACTIVE=false
N8N_DIAGNOSTICS_ENABLED=false
N8N_PERSONALIZATION_ENABLED=false
N8N_TEMPLATES_ENABLED=false
```

## Docker network yapısı

- `n8n-isolated`: internal=true, container'lar birbirini göremez
- `n8n-external`: webhook proxy + node agent, dış erişim var

## Dikkat

- Container'a internet erişimi verme
- Kullanıcı verilerini volume ile kalıcı yap
- Her container'ın kendi N8N_ENCRYPTION_KEY'i olmalı
- Port aralığı: 5678-6678 (düğüm başına)
