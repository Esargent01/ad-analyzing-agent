import { motion, useReducedMotion } from "framer-motion";
import { viewportConfig } from "./animation-variants";

const SANS = "'Outfit', sans-serif";

const slots = [
  {
    name: "Headline",
    values: ["Summer Sale 50%", "Free Shipping Today", "Limited Time Offer"],
    selected: 0,
    color: "#f5ebe0",
  },
  {
    name: "CTA",
    values: ["Shop Now", "Claim Offer", "Get Started"],
    selected: 1,
    color: "#e8f0e8",
  },
  {
    name: "Media",
    values: ["hero-video.mp4", "lifestyle-shot.jpg", "product-360.mp4"],
    selected: 2,
    color: "#e0eaf5",
  },
  {
    name: "Audience",
    values: ["Women 25-34", "Retargeting 30d", "Lookalike 1%"],
    selected: 0,
    color: "#f5e8f0",
  },
];

export function GenomeAnimation() {
  const reduced = useReducedMotion();

  return (
    <motion.div
      className="flex h-full flex-col items-center justify-center gap-6"
      initial="hidden"
      whileInView="visible"
      viewport={viewportConfig}
      style={{ fontFamily: SANS }}
    >
      {/* Gene pool columns */}
      <motion.div
        className="flex gap-3"
        variants={{
          hidden: {},
          visible: { transition: { staggerChildren: 0.1 } },
        }}
      >
        {slots.map((slot, slotIdx) => (
          <motion.div
            key={slot.name}
            className="flex flex-col gap-1.5"
            variants={{
              hidden: { opacity: 0, y: 15 },
              visible: {
                opacity: 1,
                y: 0,
                transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
              },
            }}
          >
            <span className="mb-1 text-center text-[10px] font-semibold uppercase tracking-wider text-[#999]">
              {slot.name}
            </span>
            {slot.values.map((val, valIdx) => (
              <motion.div
                key={val}
                className="rounded-lg border px-2.5 py-1.5 text-[11px] leading-tight"
                style={{
                  backgroundColor:
                    valIdx === slot.selected ? slot.color : "#faf9f7",
                  borderColor:
                    valIdx === slot.selected ? "#1a1a1a" : "#e8e5e0",
                  maxWidth: 120,
                }}
                variants={{
                  hidden: {},
                  visible:
                    valIdx === slot.selected
                      ? {
                          scale: [1, 1.08, 1.04],
                          borderColor: "#1a1a1a",
                          transition: {
                            delay: reduced ? 0 : 0.6 + slotIdx * 0.2,
                            duration: 0.4,
                          },
                        }
                      : {
                          opacity: 0.5,
                          transition: {
                            delay: reduced ? 0 : 0.8 + slotIdx * 0.2,
                            duration: 0.3,
                          },
                        },
                }}
              >
                {val}
              </motion.div>
            ))}
          </motion.div>
        ))}
      </motion.div>

      {/* Arrow */}
      <motion.div
        className="text-[#ccc]"
        variants={{
          hidden: { opacity: 0 },
          visible: {
            opacity: 1,
            transition: { delay: reduced ? 0 : 1.4, duration: 0.3 },
          },
        }}
      >
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M12 5v14m0 0l-5-5m5 5l5-5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </motion.div>

      {/* Assembled genome card */}
      <motion.div
        className="w-full max-w-[340px] rounded-xl border-2 border-[#e8e5e0] bg-white p-4 shadow-sm"
        variants={{
          hidden: { opacity: 0, y: 10 },
          visible: {
            opacity: 1,
            y: 0,
            borderColor: "#1a1a1a",
            transition: {
              delay: reduced ? 0 : 1.6,
              duration: 0.5,
              borderColor: { delay: reduced ? 0 : 2.0, duration: 0.3 },
            },
          },
        }}
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[12px] font-semibold text-[#1a1a1a]">
            Variant V12
          </span>
          <motion.span
            className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700"
            variants={{
              hidden: { opacity: 0, scale: 0.8 },
              visible: {
                opacity: 1,
                scale: 1,
                transition: { delay: reduced ? 0 : 2.2, duration: 0.3 },
              },
            }}
          >
            Ready
          </motion.span>
        </div>
        <div className="flex flex-col gap-1.5">
          {slots.map((slot) => (
            <div key={slot.name} className="flex items-center gap-2">
              <span className="w-16 text-[10px] font-medium text-[#999]">
                {slot.name}
              </span>
              <span
                className="rounded px-2 py-1 text-[11px]"
                style={{ backgroundColor: slot.color }}
              >
                {slot.values[slot.selected]}
              </span>
            </div>
          ))}
        </div>
      </motion.div>
    </motion.div>
  );
}
