import { motion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const EASE = [0.16, 1, 0.3, 1] as const;

export function ReportAnimation() {
  return (
    <div
      className="relative flex h-full min-h-[340px] w-full flex-col items-center justify-center gap-2 lg:min-h-[400px]"
      style={{ fontFamily: SANS }}
    >
      {/* Envelope whoosh */}
      <motion.div
        initial={{ opacity: 0, y: -40, rotate: -8 }}
        whileInView={{
          opacity: [0, 1, 1, 0],
          y: [-40, -10, -10, 0],
          rotate: [-8, 0, 0, 0],
        }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 1.4, ease: EASE, times: [0, 0.3, 0.7, 1] }}
        className="absolute top-4 flex h-9 w-12 items-center justify-center rounded-md border border-[#e8e5e0] bg-white shadow-sm"
      >
        <svg width="20" height="14" viewBox="0 0 20 14" fill="none">
          <rect x="1" y="1" width="18" height="12" rx="1.5" stroke="#888" strokeWidth="1" />
          <path d="M1 2 L10 8 L19 2" stroke="#888" strokeWidth="1" fill="none" />
        </svg>
      </motion.div>

      {/* Email stack */}
      <div className="mt-8 flex w-full max-w-[380px] flex-col gap-2">
        {/* Daily email */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, ease: EASE, delay: 1.1 }}
          className="relative rounded-xl border border-[#e8e5e0] bg-white p-3 shadow-sm"
        >
          <div className="absolute right-3 top-3 h-2 w-2 rounded-full bg-blue-500" />
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[9px] font-semibold uppercase tracking-wide text-[#aaa]">
              Daily report
            </span>
            <span className="text-[9px] text-[#ccc]">6:00 AM</span>
          </div>
          <div className="mb-2 text-[12px] font-medium text-[#1a1a1a]">
            Monday's performance recap — CTR up 0.4pp
          </div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {[
              { label: "CTR", val: "2.8%", tone: "up" },
              { label: "ROAS", val: "3.4x", tone: "up" },
              { label: "Spend", val: "$412", tone: "flat" },
              { label: "Purchases", val: "14", tone: "up" },
            ].map((chip, i) => (
              <motion.div
                key={chip.label}
                initial={{ opacity: 0, scale: 0.8 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true, amount: 0.3 }}
                transition={{
                  duration: 0.3,
                  ease: EASE,
                  delay: 1.4 + i * 0.08,
                }}
                className="flex items-center gap-1 rounded-full bg-[#f4f3f0] px-2 py-[3px] text-[9px] font-medium"
              >
                <span className="text-[#888]">{chip.label}</span>
                <span className="text-[#1a1a1a]">{chip.val}</span>
                {chip.tone === "up" && <span className="text-emerald-600">↑</span>}
              </motion.div>
            ))}
          </div>
          {/* Element winners */}
          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true, amount: 0.3 }}
            transition={{ duration: 0.4, delay: 1.9 }}
            className="mt-2 border-t border-[#f0ede8] pt-2"
          >
            <div className="mb-1 text-[9px] font-semibold uppercase text-[#aaa]">
              Top element
            </div>
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-[#1a1a1a]">CTA · "Shop risk-free"</span>
              <span className="font-semibold text-emerald-600">+18% CTR</span>
            </div>
          </motion.div>
        </motion.div>

        {/* Weekly email */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, ease: EASE, delay: 2.1 }}
          className="relative rounded-xl border border-[#e8e5e0] bg-white p-3 shadow-sm"
        >
          <div className="absolute right-3 top-3 h-2 w-2 rounded-full bg-blue-500" />
          <div className="mb-1 flex items-center gap-2">
            <span className="text-[9px] font-semibold uppercase tracking-wide text-[#aaa]">
              Weekly report
            </span>
            <span className="text-[9px] text-[#ccc]">Mondays</span>
          </div>
          <div className="mb-2 text-[12px] font-medium text-[#1a1a1a]">
            Last week in review — 3 winners, 2 retired
          </div>
          <div className="flex h-[30px] items-end gap-[3px]">
            {[40, 62, 48, 78, 55, 88, 70].map((h, i) => (
              <motion.div
                key={i}
                initial={{ height: 0 }}
                whileInView={{ height: `${h}%` }}
                viewport={{ once: true, amount: 0.3 }}
                transition={{
                  duration: 0.5,
                  ease: EASE,
                  delay: 2.5 + i * 0.06,
                }}
                className={`flex-1 rounded-sm ${
                  i === 5
                    ? "bg-gradient-to-t from-emerald-600 to-emerald-400"
                    : "bg-gradient-to-t from-[#1a1816] to-[#555]"
                }`}
              />
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[8px] text-[#aaa]">
            <span>M</span>
            <span>T</span>
            <span>W</span>
            <span>T</span>
            <span>F</span>
            <span>S</span>
            <span>S</span>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
