"use client";

import { useCallback, useMemo, useState } from "react";

export interface MultiSelect {
  selecting: boolean;
  selectedIds: Set<string>;
  selectedCount: number;
  isSelected: (id: string) => boolean;
  toggle: (id: string) => void;
  selectAll: (ids: string[]) => void;
  clear: () => void;
  enter: () => void;
  exit: () => void;
}

export function useMultiSelect(): MultiSelect {
  const [selecting, setSelecting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  const isSelected = useCallback((id: string) => selectedIds.has(id), [selectedIds]);

  const toggle = useCallback((id: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback((ids: string[]) => {
    setSelectedIds(new Set(ids));
  }, []);

  const clear = useCallback(() => setSelectedIds(new Set()), []);

  const enter = useCallback(() => setSelecting(true), []);

  const exit = useCallback(() => {
    setSelecting(false);
    setSelectedIds(new Set());
  }, []);

  return useMemo(
    () => ({
      selecting,
      selectedIds,
      selectedCount: selectedIds.size,
      isSelected,
      toggle,
      selectAll,
      clear,
      enter,
      exit,
    }),
    [selecting, selectedIds, isSelected, toggle, selectAll, clear, enter, exit]
  );
}
