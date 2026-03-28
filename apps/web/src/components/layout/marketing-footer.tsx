import Link from "next/link";
import { Logo } from "@/components/ui/logo";

const FOOTER_LINKS = {
  Product: [
    { label: "Features", href: "#features" },
    { label: "Pricing", href: "#pricing" },
    { label: "Changelog", href: "/changelog" },
    { label: "Roadmap", href: "/roadmap" },
  ],
  Company: [
    { label: "About", href: "/about" },
    { label: "Blog", href: "/blog" },
    { label: "Careers", href: "/careers" },
    { label: "Contact", href: "/contact" },
  ],
  Legal: [
    { label: "Privacy Policy", href: "/privacy" },
    { label: "Terms of Service", href: "/terms" },
    { label: "Cookie Policy", href: "/cookies" },
  ],
};

export function MarketingFooter() {
  return (
    <footer className="bg-charcoal text-white">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 gap-10 md:grid-cols-5">
          {/* Brand column */}
          <div className="md:col-span-2">
            <Logo variant="mono" className="h-7 text-white" />
            <p className="mt-4 text-[14px] leading-6 text-gray-400 max-w-xs">
              Build workflow automations by talking to AI. No code, no OAuth
              headaches — just describe what you need.
            </p>
          </div>

          {/* Link columns */}
          {Object.entries(FOOTER_LINKS).map(([section, links]) => (
            <div key={section}>
              <p className="text-[13px] font-medium text-white uppercase tracking-wide">
                {section}
              </p>
              <ul className="mt-4 space-y-2">
                {links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-[14px] text-gray-400 hover:text-white transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 border-t border-gray-800 pt-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-[13px] text-gray-500">
            &copy; {new Date().getFullYear()} Conduut. All rights reserved.
          </p>
          <p className="text-[13px] text-gray-600">
            Built for teams that move fast.
          </p>
        </div>
      </div>
    </footer>
  );
}
