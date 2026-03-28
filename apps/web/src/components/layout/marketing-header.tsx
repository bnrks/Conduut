"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { buttonVariants } from "@/components/ui/button";
import { MARKETING_NAV } from "@/config/navigation";
import { cn } from "@/lib/utils";

export function MarketingHeader() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", handler, { passive: true });
    handler();
    return () => window.removeEventListener("scroll", handler);
  }, []);

  return (
    <header
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-200",
        scrolled
          ? "bg-white/90 backdrop-blur-md border-b border-gray-200 shadow-sm"
          : "bg-transparent"
      )}
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex-shrink-0">
            <Logo variant="full" className="h-7" />
          </Link>

          {/* Center nav — desktop */}
          <nav className="hidden md:flex items-center gap-6">
            {MARKETING_NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="text-[15px] text-gray-500 hover:text-charcoal transition-colors"
              >
                {item.label}
              </a>
            ))}
          </nav>

          {/* Right CTAs — desktop */}
          <div className="hidden md:flex items-center gap-3">
            <Link
              href="/login"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
            >
              Log in
            </Link>
            <Link
              href="/register"
              className={cn(buttonVariants({ variant: "default", size: "sm" }))}
            >
              Start Free
            </Link>
          </div>

          {/* Mobile hamburger */}
          <button
            className="md:hidden p-2 rounded-lg text-gray-500 hover:text-charcoal hover:bg-gray-100 transition-colors"
            onClick={() => setMobileOpen((v) => !v)}
            aria-label="Toggle menu"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileOpen && (
        <div className="md:hidden border-t border-gray-200 bg-white/95 backdrop-blur-md">
          <div className="mx-auto max-w-6xl px-4 sm:px-6 py-4 flex flex-col gap-3">
            {MARKETING_NAV.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="text-[15px] text-gray-600 hover:text-charcoal py-1 transition-colors"
                onClick={() => setMobileOpen(false)}
              >
                {item.label}
              </a>
            ))}
            <div className="flex flex-col gap-2 pt-2 border-t border-gray-100">
              <Link
                href="/login"
                className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                onClick={() => setMobileOpen(false)}
              >
                Log in
              </Link>
              <Link
                href="/register"
                className={cn(buttonVariants({ variant: "default", size: "sm" }))}
                onClick={() => setMobileOpen(false)}
              >
                Start Free
              </Link>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
