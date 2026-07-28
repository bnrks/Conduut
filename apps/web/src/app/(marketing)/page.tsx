import { Hero } from "@/components/marketing/hero";
import { HowItWorks } from "@/components/marketing/how-it-works";
import { Features } from "@/components/marketing/features";
import { Pricing } from "@/components/marketing/pricing";

export default function HomePage() {
  return (
    <>
      <Hero />
      <HowItWorks />
      <Features />
      <Pricing />
    </>
  );
}
