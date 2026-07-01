import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Script from "next/script";
import { Toaster } from "sonner";
import { Providers } from "@/app/providers";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  weight: ["400", "500", "600"],
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500"],
});

// Theme'i ilk boyamadan ÖNCE senkron uygula (anti-FOUC).
// localStorage tercihini (yoksa "system") okuyup .dark class'ini <html>'e
// toggle eder. Boylece theme her sayfada tutarli olur ve Settings'e girince
// "aniden dark olma" bug'i olusmaz. useTheme sadece Settings toggle'i icin.
const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('conduut-theme')||'system';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})();`;

export const metadata: Metadata = {
  title: {
    default: "Conduut — Build automations by talking to AI",
    template: "%s | Conduut",
  },
  description:
    "Conduut turns your words into n8n workflows. Connect your apps, automate your work — no coding required.",
  icons: {
    icon: "/images/icons/conduut-icon.svg",
    shortcut: "/images/icons/conduut-icon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${mono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        {/* Theme init: beforeInteractive => ilk sunucu HTML'inin <head>'ine
            enjekte edilir, ilk boyamadan once senkron calisir (anti-FOUC). */}
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
        <Providers>{children}</Providers>
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              fontFamily: "var(--font-inter)",
            },
          }}
        />
      </body>
    </html>
  );
}
