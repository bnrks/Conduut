"use client";

import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export interface BulkActionBarProps {
  count: number;
  total: number;
  allSelected: boolean;
  busy?: boolean;
  onSelectAll: () => void;
  onClear: () => void;
  onDelete: () => void;
  onCancel: () => void;
}

export function BulkActionBar({
  count,
  total,
  allSelected,
  busy = false,
  onSelectAll,
  onClear,
  onDelete,
  onCancel,
}: BulkActionBarProps) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-2.5">
      <span className="text-[13px] font-medium tabular-nums text-foreground">
        {count} selected
      </span>
      <button
        type="button"
        onClick={allSelected ? onClear : onSelectAll}
        disabled={busy || total === 0}
        className="text-[13px] font-medium text-conduut-500 transition-colors hover:underline disabled:pointer-events-none disabled:opacity-50"
      >
        {allSelected ? "Clear" : `Select all (${total})`}
      </button>
      <div className="ml-auto flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={onDelete}
          disabled={busy || count === 0}
        >
          {busy ? <Spinner size="sm" /> : <Trash2 className="h-4 w-4" />}
          Delete
        </Button>
      </div>
    </div>
  );
}
