# Project Overview

Merkez: [[index]]

Conduut, kullanicilarin AI agent ile sohbet ederek n8n workflow'lari
olusturmasini, duzenlemesini ve calistirmasini hedefleyen bir otomasyon
platformudur.

## Deger Onerisi

Mevcut otomasyon araclari guclu, fakat OAuth kurulumu, API key yonetimi,
workflow JSON yapisi ve webhook konfigurasyonu teknik olmayan kullanicilar icin
zorlayici. Conduut bu teknik bariyeri sohbet tabanli bir agent arayuzuyle
azaltmayi hedefler.

## Hedef Kitle

- Startup'lar.
- Gelistiriciler.
- Operasyon ekipleri.
- n8n, Zapier veya Make kullanan ama kurulum maliyetini azaltmak isteyen
  kucuk ekipler.

## Urun Pozisyonu

Kisa vadede Conduut bir MVP: kullanici Firebase ile giris yapar, LLM provider
key'ini ekler, chat ekraninda agent ile konusur ve agent shared n8n instance
uzerinde workflow olusturur.

Uzun vadede hedef, her kullaniciya izole n8n container'i saglayan, OAuth
credential akisini merkezi yoneten, usage/billing/monitoring iceren bir SaaS
platformudur. Bkz. [[system-architecture]] ve `PROJECT.md`.

## Marka Notlari

- Marka adi: `Conduut`.
- Ton: minimal, modern, global pazara uygun Ingilizce SaaS dili.
- Ana renk: `#534AB7` Conduut Purple.
- Tipografi: Inter; kod icin JetBrains Mono veya Geist Mono.

Ilgili notlar: [[current-state]], [[dashboard]], [[chat-workflow-generation]].
