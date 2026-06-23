"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Canlı düşünce (thinking) paneli — GPT/Claude'daki gibi açılır-kapanır.
 * Cevap başlamadan açık ("Düşünüyor…"), cevap gelince otomatik kapanır
 * ("Düşünce"); kullanıcı tıklayınca durumu sabitler. İçerik ephemeral.
 */
export function ThinkingPanel({
  content,
  answerStarted,
}: {
  content: string;
  answerStarted: boolean;
}) {
  // null = otomatik (cevap başlamadıysa açık, başladıysa kapalı).
  // Kullanıcı tıklayınca açık/kapalı sabitlenir.
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const open = manualOpen ?? !answerStarted;

  return (
    <div className="mb-1.5 w-full">
      <button
        type="button"
        onClick={() => setManualOpen(!open)}
        aria-expanded={open}
        className={cn(
          "flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[12px] font-medium",
          "text-conduut-700 transition-colors hover:bg-conduut-50"
        )}
      >
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform duration-150",
            open && "rotate-90"
          )}
        />
        <span className={cn(!answerStarted && "animate-pulse")}>
          {answerStarted ? "Düşünce" : "Düşünüyor…"}
        </span>
      </button>
      {open && (
        <div className="mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-muted/40 px-3 py-2">
          <p className="whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-muted-foreground">
            {content}
          </p>
        </div>
      )}
    </div>
  );
}
