import { cn } from "@/lib/utils";

export interface LogoProps extends React.SVGAttributes<SVGSVGElement> {
  variant?: "full" | "icon" | "mono";
}

export function Logo({ variant = "full", className, ...props }: LogoProps) {
  if (variant === "icon") {
    return (
      <svg
        viewBox="0 0 40 40"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={cn("h-8 w-8", className)}
        {...props}
      >
        <rect width="40" height="40" rx="9" fill="#534AB7" />
        <rect x="14" y="10" width="3.5" height="20" rx="1.75" fill="white" />
        <rect x="22.5" y="10" width="3.5" height="20" rx="1.75" fill="white" />
      </svg>
    );
  }

  if (variant === "mono") {
    return (
      <svg
        viewBox="0 0 140 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={cn("h-7", className)}
        {...props}
      >
        <text
          x="0"
          y="26"
          fontFamily="var(--font-inter), Inter, sans-serif"
          fontSize="28"
          fontWeight="500"
          letterSpacing="-0.8"
          fill="currentColor"
        >
          conduut
        </text>
      </svg>
    );
  }

  // Full wordmark: "cond" foreground + "uu" purple + "t" foreground.
  // foreground tema-duyarlı: light'ta koyu (#18181b), dark'ta açık (#fafafa),
  // böylece "cond"/"t" her iki temada da okunur, "uu" mor vurgu olarak kalır.
  return (
    <svg
      viewBox="0 0 150 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("h-7", className)}
      role="img"
      aria-label="Conduut"
      {...props}
    >
      <text
        x="0"
        y="26"
        fontFamily="var(--font-inter), Inter, sans-serif"
        fontSize="28"
        fontWeight="500"
        letterSpacing="-0.8"
      >
        <tspan fill="var(--color-foreground, #18181B)">cond</tspan>
        <tspan fill="var(--color-conduut-500, #534AB7)">uu</tspan>
        <tspan fill="var(--color-foreground, #18181B)">t</tspan>
      </text>
    </svg>
  );
}
