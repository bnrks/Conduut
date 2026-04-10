"use client";

import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { SendHorizontal, ChevronDown, Search, Check, Star } from "lucide-react";
import { useAutoResizeTextarea } from "@/hooks/use-auto-resize-textarea";
import { cn } from "@/lib/utils";
import type { ModelOption, ProviderOption } from "@/hooks/use-model-selector";

export interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  value: string;
  onChange: (value: string) => void;
  providers?: ProviderOption[];
  selectedProvider?: string | null;
  onProviderChange?: (provider: string) => void;
  models?: ModelOption[];
  selectedModel?: string | null;
  onModelChange?: (model: string) => void;
  loadingModels?: boolean;
  lockedModel?: boolean;
  isFavorite?: (provider: string, modelId: string) => boolean;
  onToggleFavorite?: (provider: string, modelId: string) => void;
}

/* ── Provider pill dropdown ───────────────────────────────────────────── */
function ProviderDropdown({
  providers,
  selected,
  onChange,
}: {
  providers: ProviderOption[];
  selected: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1 rounded-md px-2 py-1",
          "text-[12px] font-medium transition-all duration-150",
          "border border-transparent hover:border-[#E4E4E7] hover:bg-[#F4F4F5]",
          open ? "border-[#E4E4E7] bg-[#F4F4F5]" : "",
          selected ? "text-[#534AB7]" : "text-[#71717A]"
        )}
      >
        <span className="max-w-[80px] truncate">{selected || "Provider"}</span>
        <ChevronDown
          className={cn("h-3 w-3 shrink-0 transition-transform duration-150", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 mb-1.5 z-50 min-w-[140px] overflow-hidden rounded-lg border border-[#E4E4E7] bg-white shadow-lg shadow-black/5">
          {providers.map((p) => (
            <button
              key={p.provider}
              type="button"
              onClick={() => { onChange(p.provider); setOpen(false); }}
              className={cn(
                "flex w-full items-center justify-between gap-2 px-3 py-2",
                "text-[13px] transition-colors hover:bg-[#F4F4F5]",
                p.provider === selected ? "text-[#534AB7] font-medium" : "text-[#3F3F46]"
              )}
            >
              <span>{p.provider}</span>
              {p.provider === selected && <Check className="h-3 w-3 shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Single model row ──────────────────────────────────────────────────── */
function ModelRow({
  m, selected, provider, isFavorite, onToggleFavorite, onSelect,
}: {
  m: ModelOption;
  selected: string;
  provider: string;
  isFavorite?: (provider: string, modelId: string) => boolean;
  onToggleFavorite?: (provider: string, modelId: string) => void;
  onSelect: (id: string) => void;
}) {
  const fav = isFavorite?.(provider, m.id) ?? false;
  return (
    <div
      className={cn(
        "group flex w-full items-center gap-2 px-3 py-2 transition-colors hover:bg-[#F4F4F5]",
        m.id === selected ? "bg-[#EEEDFE]" : ""
      )}
    >
      <button
        type="button"
        onClick={() => onSelect(m.id)}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
      >
        <div className="min-w-0 flex-1">
          <p className={cn("truncate text-[13px]", m.id === selected ? "font-medium text-[#534AB7]" : "text-[#3F3F46]")}>
            {m.name}
          </p>
          {m.name !== m.id && (
            <p className="truncate text-[11px] text-[#A1A1AA]">{m.id}</p>
          )}
        </div>
        {m.id === selected && <Check className="h-3 w-3 shrink-0 text-[#534AB7]" />}
      </button>
      {/* Star toggle */}
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onToggleFavorite?.(provider, m.id); }}
        className={cn(
          "shrink-0 rounded p-0.5 transition-all",
          fav
            ? "text-amber-400 hover:text-amber-500"
            : "text-transparent group-hover:text-[#D4D4D8] hover:!text-amber-400"
        )}
        title={fav ? "Remove from favorites" : "Add to favorites"}
      >
        <Star className={cn("h-3.5 w-3.5", fav ? "fill-amber-400" : "fill-transparent")} />
      </button>
    </div>
  );
}

/* ── Model dropdown with search ───────────────────────────────────────── */
function ModelDropdown({
  models,
  selected,
  onChange,
  loading,
  provider,
  isFavorite,
  onToggleFavorite,
}: {
  models: ModelOption[];
  selected: string;
  onChange: (v: string) => void;
  loading: boolean;
  provider: string;
  isFavorite?: (provider: string, modelId: string) => boolean;
  onToggleFavorite?: (provider: string, modelId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => searchRef.current?.focus(), 50);
    else setQuery("");
  }, [open]);

  const favoriteModels = models.filter((m) => isFavorite?.(provider, m.id));
  const allFiltered = query.trim()
    ? models.filter((m) => m.name.toLowerCase().includes(query.toLowerCase()) || m.id.toLowerCase().includes(query.toLowerCase()))
    : models;
  // When searching, show all results; otherwise split favorites / rest
  const showFavorites = !query.trim() && favoriteModels.length > 0;
  const favSet = new Set(favoriteModels.map((m) => m.id));
  const restModels = showFavorites ? allFiltered.filter((m) => !favSet.has(m.id)) : allFiltered;

  const selectedLabel = models.find((m) => m.id === selected)?.name ?? selected;
  const selectedIsFav = isFavorite?.(provider, selected);

  if (loading) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1">
        <div className="h-2 w-2 rounded-full bg-[#534AB7]/30 animate-pulse" />
        <span className="text-[12px] text-[#A1A1AA]">Loading…</span>
      </div>
    );
  }

  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1 rounded-md px-2 py-1",
          "text-[12px] transition-all duration-150",
          "border border-transparent hover:border-[#E4E4E7] hover:bg-[#F4F4F5]",
          open ? "border-[#E4E4E7] bg-[#F4F4F5]" : "",
          selected ? "text-[#18181B]" : "text-[#71717A]"
        )}
      >
        {selectedIsFav && <Star className="h-3 w-3 shrink-0 fill-amber-400 text-amber-400" />}
        <span className="max-w-[220px] truncate">
          {selected ? selectedLabel : "Select model"}
        </span>
        <ChevronDown
          className={cn("h-3 w-3 shrink-0 text-[#A1A1AA] transition-transform duration-150", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 mb-1.5 z-50 w-72 rounded-lg border border-[#E4E4E7] bg-white shadow-lg shadow-black/5 overflow-hidden">
          {/* Search */}
          <div className="flex items-center gap-2 border-b border-[#E4E4E7] px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-[#A1A1AA]" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search models…"
              className="flex-1 bg-transparent text-[13px] text-[#18181B] placeholder:text-[#A1A1AA] focus:outline-none"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="text-[#A1A1AA] hover:text-[#71717A] text-[11px]"
              >
                ✕
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-60 overflow-y-auto">
            {allFiltered.length === 0 ? (
              <p className="px-3 py-3 text-[12px] text-[#A1A1AA] text-center">No models found</p>
            ) : (
              <>
                {/* Favorites section */}
                {showFavorites && (
                  <>
                    <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-amber-500 flex items-center gap-1">
                      <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
                      Favorites
                    </div>
                    {favoriteModels.map((m) => (
                      <ModelRow
                        key={`fav-${m.id}`}
                        m={m}
                        selected={selected}
                        provider={provider}
                        isFavorite={isFavorite}
                        onToggleFavorite={onToggleFavorite}
                        onSelect={(id) => { onChange(id); setOpen(false); setQuery(""); }}
                      />
                    ))}
                    {restModels.length > 0 && (
                      <div className="mx-3 my-1 border-t border-[#E4E4E7]" />
                    )}
                  </>
                )}

                {/* All / filtered models */}
                {restModels.map((m) => (
                  <ModelRow
                    key={m.id}
                    m={m}
                    selected={selected}
                    provider={provider}
                    isFavorite={isFavorite}
                    onToggleFavorite={onToggleFavorite}
                    onSelect={(id) => { onChange(id); setOpen(false); setQuery(""); }}
                  />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main ChatInput ───────────────────────────────────────────────────── */
export function ChatInput({
  onSend,
  disabled,
  value,
  onChange,
  providers = [],
  selectedProvider = "",
  onProviderChange,
  models = [],
  selectedModel = "",
  onModelChange,
  loadingModels = false,
  lockedModel = false,
  isFavorite,
  onToggleFavorite,
}: ChatInputProps) {
  const { ref, resize } = useAutoResizeTextarea(120);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    onChange("");
    setTimeout(() => resize(), 0);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isEmpty = value.trim().length === 0;
  const hasProviders = providers.length > 0;

  return (
    <div className="border-t border-border bg-background px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div
          className={cn(
            "rounded-xl border border-border bg-card",
            "focus-within:border-conduut-500 focus-within:ring-2 focus-within:ring-conduut-500/20",
            "transition-all duration-150"
          )}
        >
          {/* Selector bar */}
          {(hasProviders || lockedModel) && (
            <div className="flex items-center gap-0.5 border-b border-[#E4E4E7] px-2 py-1.5">
              {lockedModel ? (
                <div className="flex items-center gap-1 px-2 py-1 rounded text-xs text-[#71717A] select-none">
                  <span>{selectedProvider}</span>
                  {selectedModel && (
                    <>
                      <span className="text-[#E4E4E7]">/</span>
                      <span>{selectedModel}</span>
                    </>
                  )}
                  <span className="ml-1 text-[10px] text-[#A1A1AA] border border-[#E4E4E7] rounded px-1">locked</span>
                </div>
              ) : (
                <>
                  <ProviderDropdown
                    providers={providers}
                    selected={selectedProvider ?? ""}
                    onChange={onProviderChange ?? (() => {})}
                  />
                  {selectedProvider && (
                    <>
                      <span className="text-[#E4E4E7] select-none">/</span>
                      <ModelDropdown
                        models={models}
                        selected={selectedModel ?? ""}
                        onChange={onModelChange ?? (() => {})}
                        loading={loadingModels}
                        provider={selectedProvider}
                        isFavorite={isFavorite}
                        onToggleFavorite={onToggleFavorite}
                      />
                    </>
                  )}
                </>
              )}
            </div>
          )}

          {/* Textarea + send */}
          <div className="flex items-end gap-2 px-3 py-2">
            <textarea
              ref={ref}
              value={value}
              onChange={(e) => { onChange(e.target.value); resize(); }}
              onKeyDown={handleKeyDown}
              placeholder="Message Conduut..."
              rows={1}
              disabled={disabled}
              className={cn(
                "flex-1 resize-none bg-transparent text-[15px] text-foreground",
                "placeholder:text-muted-foreground",
                "focus:outline-none disabled:opacity-50",
                "leading-relaxed py-1"
              )}
              style={{ maxHeight: 120 }}
            />
            <button
              onClick={handleSend}
              disabled={isEmpty || disabled}
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                "bg-conduut-500 text-white",
                "hover:bg-conduut-700 active:scale-95",
                "transition-all duration-150",
                "disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100"
              )}
              aria-label="Send message"
            >
              <SendHorizontal className="h-4 w-4" />
            </button>
          </div>
        </div>
        <p className="mt-1.5 text-center text-[11px] text-muted-foreground">
          Conduut can make mistakes. Review important automations before activating.
        </p>
      </div>
    </div>
  );
}
