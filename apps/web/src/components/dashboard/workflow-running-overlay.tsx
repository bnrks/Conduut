"use client";

interface WorkflowRunningOverlayProps {
  workflowName: string;
}

// Temsili (gerçek workflow yapısı DEĞİL) sabit 5-node DAG — bkz. spec.
const EDGES = [
  "M24,60 L94,32",
  "M24,60 L94,88",
  "M94,32 L164,60",
  "M94,88 L164,60",
  "M164,60 L212,60",
];

const SPARK_BEGINS = ["0s", "0.2s", "0.65s", "0.85s", "1.25s"];

const NODES = [
  { cx: 24, cy: 60, delay: "0s" },
  { cx: 94, cy: 32, delay: "0.25s" },
  { cx: 94, cy: 88, delay: "0.45s" },
  { cx: 164, cy: 60, delay: "0.7s" },
  { cx: 212, cy: 60, delay: "0.95s" },
];

/**
 * Tekli workflow çalıştırma sırasında ekran ortasında gösterilen, temsili
 * "otomasyon çalışıyor" animasyonu. Gerçek ilerleme verisi taşımaz; tamamen
 * presentational. Temaya duyarlı: açık temada mor, koyu temada (.dark) lavanta.
 */
export function WorkflowRunningOverlay({ workflowName }: WorkflowRunningOverlayProps) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4 backdrop-blur-sm"
      role="status"
      aria-live="polite"
      aria-label={`Running workflow ${workflowName}`}
    >
      <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-7 text-center shadow-2xl">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-conduut-500 dark:text-conduut-200">
          Conduut
        </p>

        <svg
          viewBox="0 0 235 120"
          className="mx-auto mt-4 h-[120px] w-[235px] max-w-full"
          aria-hidden="true"
        >
          {EDGES.map((d, i) => (
            <path
              key={`edge-${i}`}
              d={d}
              fill="none"
              strokeWidth={2}
              className="stroke-conduut-100 dark:stroke-conduut-200/30"
            />
          ))}

          <g className="motion-reduce:hidden">
            {EDGES.map((d, i) => (
              <circle key={`spark-${i}`} r={3} className="fill-conduut-500 dark:fill-white">
                <animateMotion
                  dur="1.3s"
                  begin={SPARK_BEGINS[i]}
                  repeatCount="indefinite"
                  path={d}
                />
              </circle>
            ))}
          </g>

          {NODES.map((n, i) => (
            <circle
              key={`node-${i}`}
              cx={n.cx}
              cy={n.cy}
              r={7}
              style={{
                animationDelay: n.delay,
                transformBox: "fill-box",
                transformOrigin: "center",
              }}
              className="fill-conduut-500 [animation:conduut-node-pulse_1.7s_ease-in-out_infinite] [filter:drop-shadow(0_0_6px_rgba(83,74,183,0.55))] motion-reduce:[animation:none] dark:fill-conduut-200 dark:[filter:drop-shadow(0_0_7px_rgba(175,169,236,0.85))]"
            />
          ))}
        </svg>

        <p className="mt-3 text-[15px] font-medium text-foreground">
          Running &ldquo;{workflowName}&rdquo;
        </p>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Your automation is running
          <span aria-hidden="true">
            <span className="[animation:conduut-dot-blink_1.4s_infinite] motion-reduce:[animation:none]">.</span>
            <span className="[animation:conduut-dot-blink_1.4s_infinite_0.2s] motion-reduce:[animation:none]">.</span>
            <span className="[animation:conduut-dot-blink_1.4s_infinite_0.4s] motion-reduce:[animation:none]">.</span>
          </span>
        </p>
      </div>
    </div>
  );
}
