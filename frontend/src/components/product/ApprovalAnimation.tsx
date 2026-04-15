import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const EASE = [0.16, 1, 0.3, 1] as const;

const ROWS = [
  {
    icon: "⏸",
    label: "Pause Variant B",
    detail: "CTR down 38% · 5-day decline",
    tone: "pause",
  },
  {
    icon: "📈",
    label: "Scale Variant D",
    detail: "ROAS 3.4x · confidence 96%",
    tone: "scale",
  },
  {
    icon: "✨",
    label: "Launch V18–V20",
    detail: "3 fresh genomes queued",
    tone: "launch",
  },
  {
    icon: "⏸",
    label: "Pause Variant F",
    detail: "Fatigue detected · freq 6.2",
    tone: "pause",
  },
] as const;

export function ApprovalAnimation() {
  const reduce = useReducedMotion();
  const [approved, setApproved] = useState<number[]>(reduce ? [0, 1, 2, 3] : []);

  useEffect(() => {
    if (reduce) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    ROWS.forEach((_, i) => {
      timers.push(setTimeout(() => setApproved((a) => [...a, i]), 1400 + i * 550));
    });
    return () => timers.forEach(clearTimeout);
  }, [reduce]);

  const pending = ROWS.length - approved.length;

  return (
    <div
      className="flex h-full min-h-[340px] w-full flex-col items-center justify-center gap-2 px-2 lg:min-h-[400px]"
      style={{ fontFamily: SANS }}
    >
      <div className="mb-2 flex w-full max-w-[400px] items-center justify-between px-1">
        <span className="text-[11px] font-semibold uppercase tracking-[0.15em] text-[#999]">
          Approval queue
        </span>
        <motion.span
          key={pending}
          initial={{ scale: 1.2, color: "#f59e0b" }}
          animate={{ scale: 1, color: "#aaa" }}
          transition={{ duration: 0.3 }}
          className="text-[10px] font-medium"
        >
          {pending} pending
        </motion.span>
      </div>

      {ROWS.map((row, i) => {
        const isApproved = approved.includes(i);
        return (
          <motion.div
            key={row.label}
            initial={{ opacity: 0, y: 10 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }}
            transition={{ duration: 0.4, ease: EASE, delay: i * 0.12 }}
            className="relative flex w-full max-w-[400px] items-center gap-3 overflow-hidden rounded-xl border border-[#e8e5e0] bg-white py-2.5 pl-4 pr-3 shadow-sm"
          >
            {/* Left glow border */}
            <motion.div
              className={`absolute left-0 top-0 h-full w-[3px] ${
                row.tone === "scale"
                  ? "bg-emerald-500"
                  : row.tone === "launch"
                    ? "bg-blue-500"
                    : "bg-amber-500"
              }`}
              initial={{ opacity: 0.2 }}
              animate={{ opacity: isApproved ? 1 : 0.3 }}
              transition={{ duration: 0.4 }}
            />

            <span className="text-[14px]">{row.icon}</span>

            <div className="flex-1 min-w-0">
              <div className="truncate text-[12px] font-medium text-[#1a1a1a]">
                {row.label}
              </div>
              <div className="truncate text-[10px] text-[#888]">{row.detail}</div>
            </div>

            {/* Approve pill */}
            <motion.div
              animate={{
                backgroundColor: isApproved ? "#d1fae5" : "#f4f3f0",
              }}
              transition={{ duration: 0.4, ease: EASE }}
              className="flex items-center gap-1 rounded-full px-3 py-[5px] text-[11px] font-medium text-[#1a1a1a]"
            >
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                <motion.path
                  d="M2 6.5 L5 9.5 L10 3.5"
                  stroke="#059669"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: isApproved ? 1 : 0 }}
                  transition={{ duration: 0.3, ease: EASE }}
                />
              </svg>
              {isApproved ? "Approved" : "Approve"}
            </motion.div>
          </motion.div>
        );
      })}

      <motion.div
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.5, delay: 1 }}
        className="mt-1 text-[10px] text-[#999]"
      >
        Every call waits for the director's approval
      </motion.div>
    </div>
  );
}
