"use client";

import { useEffect, useState } from "react";

/**
 * Bir CSS media query'sini dinler ve eşleşme durumunu döner.
 *
 * SSR/hydration güvenliği: ilk render'da `defaultValue` döner (server ve client'ın
 * ilk render'ı aynı olur → hydration uyumsuzluğu yok), mount sonrası gerçek değere
 * geçer. Masaüstü tespiti için `defaultValue=true` vererek dar-ekran "flash"ını
 * önleriz (uygulama çoğunlukla masaüstünde açılır).
 */
export function useMediaQuery(query: string, defaultValue = false): boolean {
  const [matches, setMatches] = useState(defaultValue);

  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
