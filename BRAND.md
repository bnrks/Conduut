# Conduut — Brand Kit

---

## Logo Kararları

### Wordmark (Ana logo)
- Font: **Inter** (1. tercih) veya **Geist Sans** (2. tercih)
- Ağırlık: Medium (500)
- Letter-spacing: -0.8px (tight)
- Tüm küçük harf: `conduut`
- "uu" harfleri **mor (#534AB7)**, geri kalan harfler **charcoal (#18181B)**
- Koyu arka planda: "uu" → **lavanta (#AFA9EC)**, geri kalan → **beyaz (#FFFFFF)**
- Tek renkli kullanım (mor zemin): tamamı beyaz

### İkon (Favicon / App icon)
- İki paralel dikey çubuk — "uu" harflerinin soyutlanmış hali
- Çubuklar beyaz, zemin mor (#534AB7)
- Köşe yuvarlaklığı: 22% (iOS app icon standardı)

---

## Logo Üretim Prompt'ları

### Prompt 1 — Wordmark (AI görsel üretim için)

```
Minimalist wordmark logo for a tech startup called "conduut". 
All lowercase letters. The letters "uu" in the middle of the word 
are colored in purple (#534AB7), the rest of the letters are dark 
charcoal (#18181B). Clean sans-serif font similar to Inter or 
Geist, medium weight, tight letter-spacing. White background. 
No icon, no symbol, just the text. Modern SaaS aesthetic similar 
to Stripe, Linear, or Vercel branding. Vector, flat, no gradients, 
no shadows, no 3D effects.
```

### Prompt 2 — Wordmark (koyu zemin varyasyonu)

```
Minimalist wordmark logo for "conduut" on a dark background 
(#18181B). All lowercase. The letters "uu" are colored in 
soft lavender purple (#AFA9EC), remaining letters are white. 
Clean geometric sans-serif font like Inter. Medium weight, 
tight letter-spacing. Flat design, no gradients, no effects. 
Tech startup branding style.
```

### Prompt 3 — İkon / Favicon

```
Minimal app icon for a tech brand called "conduut". Square icon 
with rounded corners (22% radius). Solid purple background 
(#534AB7). Two thin parallel vertical white bars centered in the 
icon, representing the "uu" in the brand name and symbolizing 
parallel data channels or conduits. Bars have small rounded 
ends. Clean, geometric, flat design. No text. No gradients. 
Similar aesthetic to the Stripe or Linear app icons.
```

### Prompt 4 — İkon + Wordmark (yatay kompozisyon)

```
Horizontal logo lockup for tech startup "conduut". On the left: 
a small square icon with rounded corners, solid purple (#534AB7) 
background, containing two thin parallel vertical white bars. 
On the right: the wordmark "conduut" in a clean sans-serif font 
(Inter/Geist), all lowercase, medium weight, with the "uu" 
letters colored in purple (#534AB7) and the rest in dark 
charcoal (#18181B). White background. Generous spacing between 
icon and text. Minimal, modern, flat design. Vector style.
```

### Prompt 5 — Alternatif ikon (bağlantı/akış konsepti)

```
Minimal square app icon with rounded corners for tech brand 
"conduut". Purple background (#534AB7). White design: two 
parallel horizontal lines entering from the left side, curving 
and merging into a single point/dot on the right side. 
Represents data flow merging through a conduit. Clean, 
geometric, flat. No text. Inspired by plumbing/pipeline 
diagrams but highly abstracted and minimal.
```

### Prompt 6 — Sosyal medya profil resmi

```
Square social media profile picture for tech company "conduut". 
Solid purple (#534AB7) background. Centered white wordmark 
"conduut" in clean sans-serif font, all lowercase, medium 
weight. Or alternatively: just the two parallel vertical white 
bars icon mark. Minimal, clean, recognizable at small sizes. 
No gradients, no borders, no effects.
```

---

## Renk Paleti

### Ana Renkler

| Renk | Hex | Kullanım |
|------|-----|----------|
| **Conduut Purple** | `#534AB7` | Primary marka rengi, CTA butonlar, "uu" vurgusu |
| **Purple Dark** | `#3C3489` | Hover, aktif durum, koyu varyasyon |
| **Purple Light** | `#EEEDFE` | Arka plan vurgusu, badge, tag |
| **Purple 200** | `#AFA9EC` | Koyu zemin üzerinde "uu", devre dışı buton |

### Nötr Tonlar

| Renk | Hex | Kullanım |
|------|-----|----------|
| **Charcoal** | `#18181B` | Ana metin, wordmark, başlıklar |
| **Gray 700** | `#3F3F46` | Sekonder başlıklar |
| **Gray 500** | `#71717A` | Sekonder metin, açıklama |
| **Gray 400** | `#A1A1AA` | Placeholder, devre dışı |
| **Gray 200** | `#E4E4E7` | Kenarlık, ayırıcı |
| **Gray 100** | `#F4F4F5` | Yüzey, kart arka planı |
| **White** | `#FFFFFF` | Sayfa arka planı |

### Durum Renkleri

| Renk | Hex | Kullanım |
|------|-----|----------|
| **Success** | `#0F6E56` | Bağlı, aktif, başarılı |
| **Success Light** | `#E1F5EE` | Başarı arka planı |
| **Warning** | `#BA7517` | Bekliyor, dikkat |
| **Warning Light** | `#FAEEDA` | Uyarı arka planı |
| **Error** | `#A32D2D` | Hata, kopuk, başarısız |
| **Error Light** | `#FCEBEB` | Hata arka planı |

### CSS Değişkenleri

```css
:root {
  /* Primary */
  --color-primary: #534AB7;
  --color-primary-dark: #3C3489;
  --color-primary-light: #EEEDFE;
  --color-primary-on-dark: #AFA9EC;

  /* Neutral */
  --color-charcoal: #18181B;
  --color-gray-700: #3F3F46;
  --color-gray-500: #71717A;
  --color-gray-400: #A1A1AA;
  --color-gray-200: #E4E4E7;
  --color-gray-100: #F4F4F5;
  --color-white: #FFFFFF;

  /* Status */
  --color-success: #0F6E56;
  --color-success-light: #E1F5EE;
  --color-warning: #BA7517;
  --color-warning-light: #FAEEDA;
  --color-error: #A32D2D;
  --color-error-light: #FCEBEB;
}
```

### Tailwind Config

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        conduut: {
          50: '#EEEDFE',
          100: '#CECBF6',
          200: '#AFA9EC',
          400: '#7F77DD',
          500: '#534AB7',
          700: '#3C3489',
          900: '#26215C',
        },
      },
    },
  },
};
```

---

## Tipografi

### Font Ailesi

| Öncelik | Font | Kaynak | Not |
|---------|------|--------|-----|
| 1 | **Inter** | [Google Fonts](https://fonts.google.com/specimen/Inter) | En yaygın, tüm ağırlıklar mevcut |
| 2 | **Geist Sans** | [Vercel](https://vercel.com/font) | Next.js ile native entegrasyon |
| Mono | **JetBrains Mono** veya **Geist Mono** | Google Fonts / Vercel | Kod blokları, terminal |

### Ağırlıklar

| Ağırlık | Kullanım |
|---------|----------|
| 400 Regular | Gövde metin, açıklamalar |
| 500 Medium | Başlıklar, logo, buton metni, etiketler |

Sadece 2 ağırlık — 600 veya 700 kullanma.

### Boyutlar

| Eleman | Boyut | Satır yüksekliği |
|--------|-------|-------------------|
| Logo wordmark | 28-32px | — |
| H1 | 28px | 1.3 |
| H2 | 22px | 1.3 |
| H3 | 18px | 1.4 |
| Body | 15-16px | 1.6 |
| Small / caption | 13px | 1.5 |
| Code | 14px | 1.5 |

---

## Logo Kullanım Kuralları

### Minimum boyut
- Wordmark: minimum 80px genişlik
- İkon: minimum 24x24px

### Boşluk (clear space)
- Logo etrafında minimum "u" harfi yüksekliği kadar boşluk bırak

### Yapılmaması gerekenler
- Logo'yu eğme, döndürme, esnetme
- "uu" dışındaki harfleri renklendirme
- Gradient veya gölge ekleme
- Logo'yu desenli/fotoğraflı arka plana koyma (yeterli kontrast olmadıkça)

### Arka plan varyasyonları

| Arka plan | "cond" + "t" | "uu" |
|-----------|-------------|------|
| Beyaz / açık | Charcoal #18181B | Purple #534AB7 |
| Koyu / siyah | White #FFFFFF | Lavanta #AFA9EC |
| Purple #534AB7 | White #FFFFFF | White #FFFFFF |

---

## Dosya Formatları (oluşturulacak)

```
brand/
├── logo/
│   ├── conduut-wordmark-light.svg       ← Açık zemin
│   ├── conduut-wordmark-dark.svg        ← Koyu zemin
│   ├── conduut-wordmark-mono-white.svg  ← Tek renk beyaz
│   ├── conduut-wordmark-mono-black.svg  ← Tek renk siyah
│   ├── conduut-icon-purple.svg          ← İkon (mor zemin)
│   ├── conduut-icon-dark.svg            ← İkon (koyu zemin)
│   ├── conduut-lockup-horizontal.svg    ← İkon + wordmark
│   └── conduut-favicon.ico
├── colors/
│   └── palette.css
├── fonts/
│   └── (Inter veya Geist — Google Fonts / Vercel'den)
└── guidelines/
    └── BRAND.md                          ← Bu dosya
```
