import { cn } from "@/lib/utils";

interface UsageMeterProps {
  label: string;
  current: number;
  max?: number;
  unit?: string;
  className?: string;
}

function getBarColor(ratio: number): string {
  if (ratio > 0.8) return "bg-error";
  if (ratio > 0.6) return "bg-warning";
  return "bg-success";
}

export function UsageMeter({
  label,
  current,
  max,
  unit,
  className,
}: UsageMeterProps) {
  const ratio = max ? Math.min(current / max, 1) : 0;
  const percent = Math.round(ratio * 100);
  const barColor = getBarColor(ratio);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between">
        <span className="text-[13px] text-muted-foreground">{label}</span>
        <span className="text-[13px] font-medium tabular-nums text-foreground">
          {current.toLocaleString()}
          {max != null ? (
            <span className="text-muted-foreground font-normal">
              {" "}/ {max === Infinity ? "∞" : max.toLocaleString()}
            </span>
          ) : null}
          {unit && (
            <span className="text-muted-foreground font-normal"> {unit}</span>
          )}
        </span>
      </div>
      {max != null && max !== Infinity && (
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", barColor)}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}
    </div>
  );
}
