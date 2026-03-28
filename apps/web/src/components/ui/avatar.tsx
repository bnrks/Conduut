import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const avatarVariants = cva(
  "relative inline-flex shrink-0 items-center justify-center rounded-full bg-conduut-50 text-conduut-700 font-medium overflow-hidden",
  {
    variants: {
      size: {
        sm: "h-8 w-8 text-[13px]",
        md: "h-10 w-10 text-[15px]",
        lg: "h-12 w-12 text-base",
      },
    },
    defaultVariants: {
      size: "md",
    },
  }
);

export interface AvatarProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof avatarVariants> {
  src?: string;
  alt?: string;
  fallback?: string;
}

export function Avatar({
  className,
  size,
  src,
  alt,
  fallback,
  ...props
}: AvatarProps) {
  return (
    <div className={cn(avatarVariants({ size }), className)} {...props}>
      {src ? (
        <img src={src} alt={alt || ""} className="h-full w-full object-cover" />
      ) : (
        <span>{fallback || "?"}</span>
      )}
    </div>
  );
}
