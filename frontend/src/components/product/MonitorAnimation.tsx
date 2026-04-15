import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const EASE = [0.16, 1, 0.3, 1] as const;

const PACKETS = ["CTR", "CPC", "Spend", "CVR", "ROAS"];

function Counter({ target, prefix = "", suffix = "", decimals = 0, delay = 0 }: { target: number; prefix?: string; suffix?: string; decimals?: number; delay?: number }) {
  const reduce = useReducedMotion();
  const [val, setVal] = useState(reduce ? target : 0);

  useEffect(() => {
    if (reduce) return;
    const start = performance.now() + delay * 1000;
    const duration = 900;
    let raf: number;
    const tick = (now: number) => {
      const elapsed = Math.max(0, now - start);
      const t = Math.min(1, elapsed / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, delay, reduce]);

  return <span>{prefix}{val.toFixed(decimals)}{suffix}</span>;
}

export function MonitorAnimation() {
  const reduce = useReducedMotion();

  return (
    <div
      className="relative flex h-full min-h-[320px] w-full items-center justify-center lg:min-h-[380px]"
      style={{ fontFamily: SANS }}
    >
      <div className="relative flex w-full max-w-[460px] items-center justify-between">
        {/* Meta card */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="flex h-[120px] w-[110px] flex-col items-center justify-center rounded-2xl border border-[#e8e5e0] bg-white shadow-sm"
        >
          <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-full bg-[#1877f2] text-[16px] font-bold text-white">
            f
          </div>
          <div className="text-[11px] font-medium text-[#666]">Meta Ads</div>
          <div className="mt-1 flex items-center gap-1 text-[9px] text-[#999]">
            <motion.span
              className="h-1.5 w-1.5 rounded-full bg-emerald-500"
              animate={reduce ? {} : { opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
            Live
          </div>
        </motion.div>

        {/* Connecting arrow with packets */}
        <div className="relative mx-2 h-[2px] flex-1">
          <svg
            className="absolute inset-0 h-full w-full"
            viewBox="0 0 100 2"
            preserveAspectRatio="none"
          >
            <motion.line
              x1="0"
              y1="1"
              x2="100"
              y2="1"
              stroke="#c9c5bd"
              strokeWidth="1"
              strokeDasharray="3 3"
              initial={{ pathLength: 0 }}
              whileInView={{ pathLength: 1 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.6, ease: EASE, delay: 0.3 }}
            />
          </svg>

          {!reduce &&
            PACKETS.map((label, i) => (
              <motion.div
                key={label}
                className="absolute top-1/2 -translate-y-1/2 rounded-full border border-[#e8e5e0] bg-white px-2 py-[3px] text-[10px] font-medium text-[#1a1a1a] shadow-sm"
                initial={{ left: "0%", opacity: 0 }}
                whileInView={{
                  left: ["0%", "100%"],
                  opacity: [0, 1, 1, 0],
                }}
                viewport={{ once: true, amount: 0.3 }}
                transition={{
                  duration: 1.8,
                  ease: "linear",
                  delay: 0.9 + i * 0.3,
                  repeat: Infinity,
                  repeatDelay: PACKETS.length * 0.3 + 0.5,
                }}
              >
                {label}
              </motion.div>
            ))}
        </div>

        {/* Kleiber dashboard card */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, ease: EASE, delay: 0.15 }}
          className="flex h-[160px] w-[140px] flex-col rounded-2xl border border-[#1a1816] bg-[#1a1816] p-3 text-white shadow-sm"
        >
          <div className="mb-2 flex items-center justify-between">
            <div className="text-[10px] font-semibold tracking-tight">Kleiber</div>
            <motion.div
              className="h-1.5 w-1.5 rounded-full bg-emerald-400"
              animate={reduce ? {} : { opacity: [1, 0.3, 1] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
          </div>

          {/* Mini metric rows */}
          <div className="mb-2 space-y-1">
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-white/50">CTR</span>
              <span className="font-mono font-semibold">
                <Counter target={2.8} suffix="%" decimals={1} delay={1.2} />
              </span>
            </div>
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-white/50">ROAS</span>
              <span className="font-mono font-semibold">
                <Counter target={3.4} suffix="x" decimals={1} delay={1.4} />
              </span>
            </div>
            <div className="flex items-center justify-between text-[9px]">
              <span className="text-white/50">Spend</span>
              <span className="font-mono font-semibold">
                $<Counter target={412} delay={1.6} />
              </span>
            </div>
          </div>

          {/* Sparkline */}
          <svg width="100%" height="30" viewBox="0 0 110 30" fill="none" className="mt-auto">
            <motion.path
              d="M2 24 L14 20 L26 22 L38 14 L50 16 L62 10 L74 12 L86 6 L98 8 L108 4"
              stroke="white"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
              initial={{ pathLength: 0 }}
              whileInView={{ pathLength: 1 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 1.2, ease: EASE, delay: 1 }}
            />
            <motion.path
              d="M2 24 L14 20 L26 22 L38 14 L50 16 L62 10 L74 12 L86 6 L98 8 L108 4 L108 30 L2 30 Z"
              fill="url(#sparkGradient)"
              fillOpacity="0.3"
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.6, delay: 2 }}
            />
            <defs>
              <linearGradient id="sparkGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="white" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </linearGradient>
            </defs>
          </svg>
        </motion.div>
      </div>

      {/* Day ticker */}
      <motion.div
        className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-2 rounded-full border border-[#e8e5e0] bg-white px-3 py-1 text-[10px] font-medium tracking-wide text-[#666] shadow-sm"
        initial={{ opacity: 0, y: 10 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.5, ease: EASE, delay: 2.2 }}
      >
        <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
          <circle cx="6" cy="6" r="4.5" stroke="#666" strokeWidth="1" />
          <path d="M6 3.5 V6 L8 7" stroke="#666" strokeWidth="1" strokeLinecap="round" />
        </svg>
        Polls every 4 hours
      </motion.div>
    </div>
  );
}
