"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "./use-auth";

export interface ModelOption {
  id: string;
  name: string;
}

export interface ProviderOption {
  provider: string;
  masked_key: string;
}

export function useModelSelector() {
  const { user } = useAuth();
  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [loadingModels, setLoadingModels] = useState(false);
  // favorites: { provider: Set<model_id> }
  const [favorites, setFavorites] = useState<Record<string, Set<string>>>({});

  const getToken = useCallback(async () => {
    if (!user) throw new Error("not authenticated");
    return user.getIdToken();
  }, [user]);

  // Load providers + favorites on mount
  useEffect(() => {
    if (!user) return;
    void (async () => {
      try {
        const token = await getToken();
        const [provRes, favRes] = await Promise.all([
          fetch("/api/settings/llm/providers", { headers: { Authorization: `Bearer ${token}` } }),
          fetch("/api/settings/favorites", { headers: { Authorization: `Bearer ${token}` } }),
        ]);

        if (provRes.ok) {
          const data = (await provRes.json()) as { providers: ProviderOption[] };
          setProviders(data.providers || []);
          if (data.providers.length > 0 && !selectedProvider) {
            setSelectedProvider(data.providers[0]!.provider);
          }
        }

        if (favRes.ok) {
          const data = (await favRes.json()) as { favorites: Record<string, string[]> };
          const sets: Record<string, Set<string>> = {};
          for (const [p, ms] of Object.entries(data.favorites || {})) {
            sets[p] = new Set(ms);
          }
          setFavorites(sets);
        }
      } catch {}
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // Fetch models when provider changes
  const fetchModels = useCallback(
    async (provider: string) => {
      if (!user || !provider) return;
      setLoadingModels(true);
      setModels([]);
      setSelectedModel("");
      try {
        const token = await getToken();
        const res = await fetch(
          `/api/settings/llm/providers/${encodeURIComponent(provider)}/models`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (!res.ok) return;
        const data = (await res.json()) as { models: ModelOption[] };
        setModels(data.models || []);
        // Seçili model: favori varsa ilk favori, yoksa ilk model
        const favSet = favorites[provider];
        const firstFav = data.models.find((m) => favSet?.has(m.id));
        setSelectedModel(firstFav?.id ?? data.models[0]?.id ?? "");
      } catch {}
      finally { setLoadingModels(false); }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user, favorites]
  );

  useEffect(() => {
    if (selectedProvider) void fetchModels(selectedProvider);
  }, [selectedProvider, fetchModels]);

  const toggleFavorite = useCallback(
    async (provider: string, modelId: string) => {
      const isFav = favorites[provider]?.has(modelId);
      const token = await getToken();
      const res = await fetch(
        `/api/settings/favorites/${encodeURIComponent(provider)}/${encodeURIComponent(modelId)}`,
        { method: isFav ? "DELETE" : "POST", headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) return;
      const data = (await res.json()) as { favorites: Record<string, string[]> };
      const sets: Record<string, Set<string>> = {};
      for (const [p, ms] of Object.entries(data.favorites || {})) {
        sets[p] = new Set(ms);
      }
      setFavorites(sets);
    },
    [favorites, getToken]
  );

  const isFavorite = useCallback(
    (provider: string, modelId: string) => favorites[provider]?.has(modelId) ?? false,
    [favorites]
  );

  return {
    providers,
    selectedProvider,
    setSelectedProvider,
    models,
    selectedModel,
    setSelectedModel,
    loadingModels,
    favorites,
    toggleFavorite,
    isFavorite,
  };
}
