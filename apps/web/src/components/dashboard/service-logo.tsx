import Image from "next/image";
import { cn } from "@/lib/utils";

interface ServiceLogoProps {
  service: string;
  className?: string;
}

function ImageLogo({
  src,
  className,
}: {
  src: string;
  className?: string;
}) {
  return (
    <Image
      src={src}
      alt=""
      aria-hidden="true"
      width={24}
      height={24}
      className={cn("object-contain", className)}
    />
  );
}

export function ServiceLogo({ service, className }: ServiceLogoProps) {
  const normalized = service.toLowerCase();
  const logoClassName = cn("h-6 w-6", className);

  if (normalized.includes("sheets") || normalized.includes("spreadsheet")) {
    return (
      <ImageLogo
        src="/images/icons/sheets_png.png"
        className={logoClassName}
      />
    );
  }
  if (normalized.includes("gmail") || normalized.includes("mail")) {
    return (
      <ImageLogo
        src="/images/icons/gmail_png.png"
        className={logoClassName}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex h-6 w-6 items-center justify-center rounded-md bg-conduut-50 text-[12px] font-semibold text-conduut-700",
        className
      )}
    >
      {service.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
