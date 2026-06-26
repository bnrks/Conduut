# Claude (Sonnet 4.6) → DeepSeek Geçişi — Kapsamlı Karşılaştırma (2026-06)

> Bağlam: [[model-cost-research-2026-06]] araştırması + canlı bake-off sonucu. Medium/Hard
> tier'ı Claude Sonnet 4.6'dan DeepSeek V4'e taşıma kararı için her boyutta karşılaştırma.
> Fiyatlar: Sonnet `claude-api` skill ile doğrulandı; DeepSeek first-party docs.
> İlişkili: [[adr-0011-conduut-managed-tiered-models]]. Tarih: 2026-06-26.

## 1. Maliyet — geçişin asıl gerekçesi 🟢 DeepSeek

| Per 1M token | Sonnet 4.6 | DeepSeek V4 Pro | DeepSeek V4 Flash |
|---|---|---|---|
| Input (cache-miss) | $3.00 | $0.435 | $0.14 |
| Output | $15.00 | $0.87 | $0.28 |
| Cache **read** | $0.30 (0.1×) | **$0.0028** | $0.0028 |
| Cache **write** | $3.75 (1.25×, 5dk) | — | — |

Gözlemlenen tipik MEDIUM build (~66k in, ~%95 cached, ~2.3k out), like-for-like:
- **Cache'li (gerçek):** DeepSeek-pro ~$0.0036/run vs Sonnet ~$0.063/run → **~17.5x ucuz**
- **Cache'siz (taban):** ~$0.031 vs ~$0.23 → **~7.6x ucuz**

DeepSeek cache-read'i Sonnet'ten **~100x ucuz** ($0.0028 vs $0.30); agent'ın her turda büyük
system prompt + registry göndermesi DeepSeek'te neredeyse bedava. **Bu boyutta ezici kazanan.**

## 2. Tool-call güvenilirliği 🟡 Sonnet daha sağlam (guard'la kapatıldı)

- Sonnet: kaya gibi sağlam, hiç sorun yok.
- DeepSeek **#1244**: ara sıra (~%11) tool-call'ı düz metin yazıp degenerate loop'a giriyor.
  Bu oturumda **canlı bir kez gerçekleşti** (conv 979e17c9). Mitigasyon: **reliability guard**
  (buffer+retry+replay, [[model-cost-research-2026-06]] §7d). Bir band-aid; production frekansı
  hâlâ bilinmiyor → **en büyük teknik risk.**

## 3. Build kalitesi 🟢 Denk

DeepSeek makul, doğru workflow'lar kuruyor (AI Agent sub-node port wiring, IF/branch, Respond to
Webhook — hepsi doğru). **Kritik içgörü:** bake-off'taki fail'lerin çoğu DeepSeek değil, **Conduut'un
repair/sandbox bug'larıydı** (3 catch-22 — düzeltildi); Sonnet de aynılarına düşerdi. DeepSeek ara
sıra 1-2 sandbox self-repair turu istiyor (Sonnet tek seferde), ama self-repair kapatıyor → sonuç
doğru. Pratikte denk.

## 4. Hız 🟢 DeepSeek
Kullanıcı: "baya hızlı." Thinking-OFF router/flash düşük latency.

## 5. UX / streaming 🟡 Sonnet doğal
- Thinking: Sonnet native panel; DeepSeek config gerekti (router OFF / pro ON) + content'e sızma riski.
- Canlı yazma: Sonnet gerçek stream; DeepSeek **buffered→replay** (guard nedeniyle "simüle stream",
  gerçek değil — garbage'ı gizlemenin bedeli). Kabul edilebilir gerileme.

## 6. Operasyonel / uyumluluk 🟡
- API: ikisi de olgun/kolay (DeepSeek OpenAI-uyumlu).
- DeepSeek **bakiye yönetimi** (402 görüldü); thinking-modu quirk'i (forced tool_choice 400 — çözüldü).
- ⚠️ **Çinli sağlayıcı** — data residency / compliance ürün için ayrı değerlendirilmeli.

## 7. Geçişin mühendislik bedeli (bu branch)

| DeepSeek'e özgü kalıcı yük | Genel iyileştirme (tüm modeller) |
|---|---|
| deepseek provider + PROFILE_DEEPSEEK | 3 catch-22 fix (repair/sandbox) |
| thinking config (router OFF / pro ON) | anti-thrash guard |
| **reliability guard (#1244)** — ekstra karmaşıklık | cost-logging |
| | output modal (dashboard) |

Geçiş çabasının ~yarısı aslında tüm modellere fayda sağlayan Conduut bug-fix'leriydi.

## 8. Risk register
- 🔴 #1244 production frekansı bilinmiyor (guard band-aid).
- 🟡 Buffered streaming = UX gerilemesi.
- 🟡 Bakiye/402 operasyonel dikkat.
- 🟡 Çinli sağlayıcı — compliance/data residency.
- 🟢 Cache-bağımlı maliyet — taban yine ~7x ucuz, güvenli.

## 9. Verdict

| Boyut | Kazanan |
|---|---|
| Maliyet | 🟢 DeepSeek (~7–17x) |
| Hız | 🟢 DeepSeek |
| Build kalitesi | 🟢 Denk |
| Tool-call güvenilirlik | 🟡 Sonnet (guard'la kapatıldı) |
| Streaming UX | 🟡 Sonnet |
| Operasyonel/uyumluluk | 🟡 Sonnet |

**Özet:** DeepSeek'e geçiş **maliyette ezici, kalitede denk, güvenilirlik+UX'te yönetilebilir
gerilemeli.** MVP/maliyet-öncelikli bu aşamada mantıklı bir bahis — ama #1244 ve compliance izlenmeli.
`default`/`gpt` profilleri duruyor → sorun çıkarsa tek-switch geri dönülebilir; ya da **hibrit**
(SIMPLE→DeepSeek, HARD→Sonnet) yapılabilir. Branch'te kalıp bir süre kullanmak kararı
geri-döndürülebilir tutuyor. İyiyse ADR-0015 ile kalıcılaştır.
