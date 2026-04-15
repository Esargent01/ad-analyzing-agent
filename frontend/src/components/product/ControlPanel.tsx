import { motion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const EASE = [0.16, 1, 0.3, 1] as const;

const YOU = [
  "Set the strategy — which campaigns the team manages",
  "Write the creative brief — rules for copy, tone, what's off-limits",
  "Sign off on every pause, scale, and launch",
  "Own the budget — Meta's spend cap is yours to set",
];

const KLEIBER = [
  "Runs the daily reporting desk — metrics pulled every 4 hours",
  "Staffs the creative department — new copy shipping weekly",
  "Runs the analytics function — statistical tests on every variant",
  "Writes your morning briefing and weekly board report",
];

export function ControlPanel() {
  return (
    <section className="bg-white py-24 lg:py-28" style={{ fontFamily: SANS }}>
      <div className="mx-auto max-w-6xl px-6 sm:px-10 lg:px-16">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.6, ease: EASE }}
          className="mb-12 text-center"
        >
          <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
            Roles & responsibilities
          </p>
          <h2
            className="mx-auto mb-4 max-w-2xl text-[clamp(1.5rem,3vw,2.5rem)] leading-[1.15] tracking-tight text-[#1a1a1a]"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            You direct. Your team delivers.
          </h2>
          <p className="mx-auto max-w-xl text-[14px] leading-relaxed text-[#666]">
            Think of it like any marketing org: the director owns the strategy
            and the sign-offs, the team owns the execution. No auto-pilot
            surprises, no decisions made without you.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-5">
          {/* You control */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.5, ease: EASE }}
            className="rounded-2xl border border-[#e8e5e0] bg-[#faf9f7] p-7"
          >
            <div className="mb-4 flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1a1816] text-[14px] text-white">
                ✓
              </div>
              <span className="text-[11px] font-semibold uppercase tracking-[0.15em] text-[#999]">
                The director (you)
              </span>
            </div>
            <ul className="space-y-3">
              {YOU.map((item, i) => (
                <motion.li
                  key={item}
                  initial={{ opacity: 0, x: -10 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, amount: 0.3 }}
                  transition={{ duration: 0.4, ease: EASE, delay: 0.1 + i * 0.08 }}
                  className="flex gap-2.5 text-[14px] leading-relaxed text-[#1a1a1a]"
                >
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[#1a1816]" />
                  {item}
                </motion.li>
              ))}
            </ul>
          </motion.div>

          {/* Kleiber handles */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.5, ease: EASE, delay: 0.1 }}
            className="rounded-2xl border border-[#1a1816] bg-[#1a1816] p-7 text-white"
          >
            <div className="mb-4 flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-[14px] text-[#1a1816]">
                ⚡
              </div>
              <span className="text-[11px] font-semibold uppercase tracking-[0.15em] text-white/50">
                The team (Kleiber)
              </span>
            </div>
            <ul className="space-y-3">
              {KLEIBER.map((item, i) => (
                <motion.li
                  key={item}
                  initial={{ opacity: 0, x: 10 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, amount: 0.3 }}
                  transition={{ duration: 0.4, ease: EASE, delay: 0.2 + i * 0.08 }}
                  className="flex gap-2.5 text-[14px] leading-relaxed text-white/90"
                >
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
                  {item}
                </motion.li>
              ))}
            </ul>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
