import { Logo } from "@/components/ui/logo";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex">
      {/* Left panel — desktop only */}
      <div className="hidden lg:flex lg:w-1/2 bg-conduut-50 flex-col items-center justify-center p-12 relative overflow-hidden">
        {/* Decorative background circles */}
        <div
          aria-hidden
          className="absolute -top-24 -left-24 h-96 w-96 rounded-full bg-conduut-100/60"
        />
        <div
          aria-hidden
          className="absolute -bottom-32 -right-20 h-80 w-80 rounded-full bg-conduut-200/40"
        />
        <div
          aria-hidden
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[500px] w-[500px] rounded-full bg-conduut-100/30"
        />

        {/* Content */}
        <div className="relative z-10 flex flex-col items-center gap-6 text-center max-w-sm">
          <Logo variant="full" className="h-9" />
          <p className="text-lg font-medium text-conduut-700 leading-snug">
            Build automations by talking to AI
          </p>
          <p className="text-sm text-conduut-500/80 leading-relaxed">
            Connect your apps, automate your work — no coding required.
          </p>

          {/* Decorative pill badges */}
          <div className="flex flex-wrap justify-center gap-2 mt-2">
            {[
              "Google Sheets",
              "Gmail",
              "Slack",
              "Notion",
              "GitHub",
              "Discord",
            ].map((service) => (
              <span
                key={service}
                className="inline-flex items-center rounded-full bg-white/80 border border-conduut-200/60 px-3 py-1 text-xs font-medium text-conduut-700"
              >
                {service}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel — form area */}
      <div className="flex flex-1 flex-col items-center justify-center p-6 bg-white">
        <div className="w-full max-w-sm">{children}</div>
      </div>
    </div>
  );
}
