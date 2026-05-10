import { cn } from "@/lib/utils";

interface ServiceLogoProps {
  service: string;
  className?: string;
}

function GmailLogo({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={className}
      focusable="false"
    >
      <path
        fill="#EA4335"
        d="M4.5 5h15A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5H17v-8.2l-5 3.75-5-3.75V19H4.5A1.5 1.5 0 0 1 3 17.5v-11A1.5 1.5 0 0 1 4.5 5Z"
      />
      <path fill="#C5221F" d="M7 10.8V19H4.5A1.5 1.5 0 0 1 3 17.5v-11l4 4.3Z" />
      <path fill="#34A853" d="M17 10.8V19h2.5a1.5 1.5 0 0 0 1.5-1.5v-11l-4 4.3Z" />
      <path fill="#FBBC04" d="M3 6.5 12 13l9-6.5V9l-9 6.5L3 9V6.5Z" />
      <path fill="#FFFFFF" d="M5 7.35 12 12.4l7-5.05V17h-1.5v-6.9L12 14.2l-5.5-4.1V17H5V7.35Z" />
    </svg>
  );
}

function SheetsLogo({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={className}
      focusable="false"
    >
      <path fill="#0F9D58" d="M6 2h8.25L20 7.75V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z" />
      <path fill="#87CEAC" d="M14 2v4.75A1.25 1.25 0 0 0 15.25 8H20L14 2Z" />
      <path fill="#FFFFFF" d="M7.5 10h9v7.5h-9V10Zm1.25 1.25v1.5h2.2v-1.5h-2.2Zm3.45 0v1.5h3.05v-1.5H12.2Zm-3.45 2.75v2.25h2.2V14h-2.2Zm3.45 0v2.25h3.05V14H12.2Z" />
    </svg>
  );
}

export function ServiceLogo({ service, className }: ServiceLogoProps) {
  const normalized = service.toLowerCase();
  const logoClassName = cn("h-6 w-6", className);

  if (normalized.includes("sheets") || normalized.includes("spreadsheet")) {
    return <SheetsLogo className={logoClassName} />;
  }
  if (normalized.includes("gmail") || normalized.includes("mail")) {
    return <GmailLogo className={logoClassName} />;
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
