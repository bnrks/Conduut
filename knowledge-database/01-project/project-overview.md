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

Bugun Conduut bir MVP: kullanici Firebase ile giris yapar, chat ekraninda
Conduut-managed LLM agent ile konusur ve agent shared n8n instance uzerinde
workflow olusturur.

Aktif production hedefi customer-owned n8n (BYO n8n) modelidir. Her kullanici
kendi VPS/cloud hesabinda kendi n8n instance'ini satin alir ve yonetir;
Conduut, iptal edilebilir public API erisimiyle AI workflow olusturma,
dogrulama, calistirma ve izleme katmani olur. Managed per-user container modeli
ertelenmistir. Bkz. [[customer-owned-n8n]],
[[adr-0022-customer-owned-n8n]] ve [[system-architecture]].

## Marka Notlari

- Marka adi: `Conduut`.
- Ton: minimal, modern, global pazara uygun Ingilizce SaaS dili.
- Ana renk: `#534AB7` Conduut Purple.
- Tipografi: Inter; kod icin JetBrains Mono veya Geist Mono.

Ilgili notlar: [[current-state]], [[customer-owned-n8n]], [[dashboard]],
[[chat-workflow-generation]].
