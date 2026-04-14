import { motion, useReducedMotion, useInView } from "framer-motion";
import { useRef, useEffect, useState } from "react";

const SANS = "'Outfit', sans-serif";

const variants = [
  { name: "Variant A", ctr: 2.1, barWidth: 42, color: "#e0eaf5" },
  { name: "Variant B", ctr: 3.8, barWidth: 76, color: "#e8f0e8", winner: true },
  { name: "Variant C", ctr: 1.4, barWidth: 28, color: "#f5e8f0" },
];

function CountingNumber({ target, delay }: { target: number; delay: number }) {
  const [value, setValue] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.5 });
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setValue(target);
      return;
    }
    const timeout = setTimeout(() => {
      const duration = 1200;
      const start = performance.now();
      const step = (now: number) => {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        setValue(Number((target * eased).toFixed(1)));
        if (progress < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }, delay);
    return () => clearTimeout(timeout);
  }, [inView, target, delay, reduced]);

  return <span ref={ref}>{value.toFixed(1)}%</span>;
}

export function TestingAnimation() {
  const reduced = useReducedMotion();

  return (
    <motion.div
      className="flex h-full flex-col items-center justify-center gap-4"
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, amount: 0.1 }}
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: 0.15, delayChildren: 0.2 } },
      }}
      style={{ fontFamily: SANS }}
    >
      {variants.map((v, i) => (
        <motion.div
          key={v.name}
          className="w-full max-w-[340px] rounded-xl border bg-white p-4 shadow-sm"
          style={{
            borderColor: v.winner ? "transparent" : "#e8e5e0",
          }}
          variants={{
            hidden: { opacity: 0, y: 20 },
            visible: {
              opacity: v.winner ? 1 : 0.7,
              y: 0,
              transition: {
                duration: 0.5,
                opacity: { delay: reduced ? 0 : v.winner ? 0 : 2.0, duration: 0.4 },
              },
            },
          }}
        >
          {/* Winner border animation */}
          {v.winner && (
            <motion.div
              className="pointer-events-none absolute inset-0 rounded-xl border-2 border-emerald-500"
              variants={{
                hidden: { opacity: 0 },
                visible: {
                  opacity: 1,
                  transition: { delay: reduced ? 0 : 1.8, duration: 0.3 },
                },
              }}
            />
          )}
          <div className="relative">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[13px] font-medium text-[#1a1a1a]">
                {v.name}
              </span>
              <div className="flex items-center gap-2">
                <span className="text-[14px] font-semibold tabular-nums text-[#1a1a1a]">
                  <CountingNumber
                    target={v.ctr}
                    delay={reduced ? 0 : 600 + i * 150}
                  />
                </span>
                <span className="text-[11px] text-[#999]">CTR</span>
              </div>
            </div>

            {/* Progress bar */}
            <div className="h-3 w-full overflow-hidden rounded-full bg-[#f5f5f3]">
              <motion.div
                className="h-full rounded-full"
                style={{ backgroundColor: v.color }}
                variants={{
                  hidden: { width: 0 },
                  visible: {
                    width: `${v.barWidth}%`,
                    transition: {
                      delay: reduced ? 0 : 0.6 + i * 0.15,
                      duration: 1.2,
                      ease: [0.16, 1, 0.3, 1],
                    },
                  },
                }}
              />
            </div>

            {/* Winner badge */}
            {v.winner && (
              <motion.div
                className="mt-2 flex justify-end"
                variants={{
                  hidden: { opacity: 0, x: 10 },
                  visible: {
                    opacity: 1,
                    x: 0,
                    transition: { delay: reduced ? 0 : 2.2, duration: 0.4 },
                  },
                }}
              >
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-[11px] font-medium text-emerald-700">
                  <svg
                    className="h-3 w-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4.5 12.75l6 6 9-13.5"
                    />
                  </svg>
                  Winner (p &lt; 0.05)
                </span>
              </motion.div>
            )}
          </div>
        </motion.div>
      ))}

      {/* Impressions note */}
      <motion.p
        className="mt-2 text-center text-[11px] text-[#bbb]"
        variants={{
          hidden: { opacity: 0 },
          visible: {
            opacity: 1,
            transition: { delay: reduced ? 0 : 2.5, duration: 0.3 },
          },
        }}
      >
        Based on 12,400+ impressions per variant
      </motion.p>
    </motion.div>
  );
}
