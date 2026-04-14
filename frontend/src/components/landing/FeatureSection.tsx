import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { viewportConfig } from "./animation-variants";

const SERIF = "'DM Serif Display', serif";

interface FeatureSectionProps {
  heading: string;
  description: string;
  figurePosition: "left" | "right";
  background: "cream" | "white";
  animation: ReactNode;
}

export function FeatureSection({
  heading,
  description,
  figurePosition,
  background,
  animation,
}: FeatureSectionProps) {
  const bg = background === "cream" ? "bg-[#f6f5f3]" : "bg-white";
  const textSlide = figurePosition === "left" ? { x: 30 } : { x: -30 };

  return (
    <section className={`${bg} py-24 lg:py-32`}>
      <div className="mx-auto max-w-7xl px-6 sm:px-10 lg:px-16">
        <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12 lg:gap-16">
          {/* Text — always first on mobile, alternates on desktop */}
          <motion.div
            className={`lg:col-span-5 ${
              figurePosition === "left" ? "lg:order-2" : "lg:order-1"
            }`}
            initial={{ opacity: 0, ...textSlide }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={viewportConfig}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          >
            <h2
              className="mb-4 text-[clamp(1.5rem,3vw,2.5rem)] tracking-tight text-[#1a1a1a]"
              style={{ fontFamily: SERIF }}
            >
              {heading}
            </h2>
            <p className="max-w-md text-[15px] leading-relaxed text-[#666]">
              {description}
            </p>
          </motion.div>

          {/* Animation figure — always second on mobile, alternates on desktop */}
          <div
            className={`lg:col-span-7 ${
              figurePosition === "left" ? "lg:order-first" : "lg:order-2"
            }`}
          >
            <div className="relative mx-auto min-h-[360px] max-w-[480px] overflow-hidden rounded-2xl bg-[#faf9f7] p-6 lg:min-h-[420px] lg:max-w-none xl:rounded-3xl">
              {animation}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
