---
name: review
description: "Kod incelemesi yapar. Güvenlik, performans, mimari uyumluluk ve Conduut kurallarına uygunluk kontrol eder."
allowed-tools: Read, Glob, Grep, Bash
context: fork
agent: Explore
---

# Kod incelemesi: $ARGUMENTS

$ARGUMENTS olarak verilen dosya veya dizini incele.

## Kontrol listesi

### Güvenlik
- [ ] Hardcoded secret var mı? (API key, token, şifre)
- [ ] SQL injection riski var mı? (raw query kullanımı)
- [ ] OAuth token'ları düz metin mi tutuluyor?
- [ ] Container izolasyon kuralları ihlal ediliyor mu?
- [ ] Input validation eksik mi?

### Mimari uyumluluk
- [ ] Doğru katmanda mı? (route → service → model ayrımı)
- [ ] Dependency injection kullanılıyor mu? (FastAPI Depends)
- [ ] Async/await doğru kullanılıyor mu?
- [ ] Type hints var mı?
- [ ] n8n'e erişim sadece REST API üzerinden mi?

### Performans
- [ ] N+1 query sorunu var mı?
- [ ] Redis cache kullanılabilir mi?
- [ ] Gereksiz blocking I/O var mı?

### Test
- [ ] Yeni endpoint'in testi yazılmış mı?
- [ ] Edge case'ler düşünülmüş mü?
- [ ] Mock'lar doğru kullanılıyor mu?

## Çıktı formatı

Her bulgu için: CRITICAL / HIGH / MEDIUM / LOW seviyesi, dosya:satır, açıklama ve düzeltme önerisi.
