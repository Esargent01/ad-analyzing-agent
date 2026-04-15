import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const SERIF = "'DM Serif Display', serif";
const EASE = [0.16, 1, 0.3, 1] as const;

const STEPS = [
  { icon: "📡", label: "Poll metrics", detail: "Every 4 hours from Meta" },
  { icon: "📊", label: "Run tests", detail: "Two-proportion z-tests, 95% conf." },
  { icon: "🧬", label: "Generate genomes", detail: "New copy from your gene pool" },
  { icon: "📬", label: "Queue proposals", detail: "Pause, scale, and launch decisions" },
  { icon: "✅", label: "Wait for approval", detail: "You review in 60 seconds" },
  { icon: "🚀", label: "Deploy & report", detail: "Ship to Meta, email the recap" },
] as const;

export function DailyLoop() {
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setActive((i) => (i + 1) % STEPS.length), 2000);
    return () => clearInterval(t);
  }, [reduce]);

  return (
    <section
      className="bg-[#f6f5f3] py-24 lg:py-28"
      style={{ fontFamily: SANS }}
    >
      <div className="mx-auto max-w-6xl px-6 sm:px-10 lg:px-16">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.6, ease: EASE }}
          className="mb-12 text-center"
        >
          <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
            A day in the department
          </p>
          <h2
            className="mx-auto mb-4 max-w-2xl text-[clamp(1.5rem,3vw,2.5rem)] leading-[1.15] tracking-tight text-[#1a1a1a]"
            style={{ fontFamily: SERIF }}
          >
            What your team does before you clock in
          </h2>
          <p className="mx-auto max-w-xl text-[14px] leading-relaxed text-[#666]">
            Six steps, running every day. Your team handles the work; you
            arrive to a briefing and a stack of decisions ready for sign-off.
          </p>
        </motion.div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6 lg:gap-4">
          {STEPS.map((step, i) => (
            <motion.div
              key={step.label}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.5, ease: EASE, delay: i * 0.08 }}
              className="relative"
            >
              <motion.div
                animate={{
                  borderColor: active === i ? "#1a1816" : "#e8e5e0",
                  backgroundColor: active === i ? "#1a1816" : "#ffffff",
                  color: active === i ? "#ffffff" : "#1a1a1a",
                }}
                transition={{ duration: 0.4, ease: EASE }}
                className="flex h-full flex-col rounded-2xl border p-4 shadow-sm"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-[20px]">{step.icon}</span>
                  <span
                    className={`text-[10px] font-semibold tabular-nums ${
                      active === i ? "text-white/60" : "text-[#aaa]"
                    }`}
                  >
                    0{i + 1}
                  </span>
                </div>
                <div className="mb-1 text-[13px] font-semibold leading-tight">
                  {step.label}
                </div>
                <div
                  className={`text-[11px] leading-snug ${
                    active === i ? "text-white/60" : "text-[#888]"
                  }`}
                >
                  {step.detail}
                </div>
              </motion.div>

              {/* Connector dot */}
              {i < STEPS.length - 1 && (
                <div className="pointer-events-none absolute -right-2 top-1/2 hidden h-[1px] w-4 -translate-y-1/2 bg-[#d4cfc5] lg:block" />
              )}
            </motion.div>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, delay: 0.8 }}
          className="mt-8 flex items-center justify-center gap-2 text-[12px] text-[#999]"
        >
          <motion.span
            className="h-1.5 w-1.5 rounded-full bg-emerald-500"
            animate={reduce ? {} : { opacity: [1, 0.3, 1] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
          Your team works every day — weekly board report drops Mondays
        </motion.div>
      </div>
    </section>
  );
}
