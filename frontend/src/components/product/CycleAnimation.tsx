import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const EASE = [0.16, 1, 0.3, 1] as const;

type Card = {
  id: string;
  label: string;
  headline: string;
  cta: string;
  state: "fresh" | "tired" | "new";
};

const WEEK_A: Card[] = [
  { id: "a1", label: "V12", headline: "Sleep better tonight", cta: "Shop now", state: "fresh" },
  { id: "a2", label: "V13", headline: "30% off summer sale", cta: "Grab deal", state: "tired" },
  { id: "a3", label: "V14", headline: "Trusted by 10k moms", cta: "Learn more", state: "fresh" },
  { id: "a4", label: "V15", headline: "Limited stock left", cta: "Buy today", state: "tired" },
];

const WEEK_B: Card[] = [
  { id: "a1", label: "V12", headline: "Sleep better tonight", cta: "Shop now", state: "fresh" },
  { id: "b2", label: "V16", headline: "Wake up refreshed", cta: "Try risk-free", state: "new" },
  { id: "a3", label: "V14", headline: "Trusted by 10k moms", cta: "Learn more", state: "fresh" },
  { id: "b4", label: "V17", headline: "Built for side sleepers", cta: "See my size", state: "new" },
];

export function CycleAnimation() {
  const reduce = useReducedMotion();
  const [week, setWeek] = useState(0);

  useEffect(() => {
    if (reduce) {
      setWeek(1);
      return;
    }
    const loop = () => {
      setWeek((w) => (w === 0 ? 1 : 0));
    };
    const t = setInterval(loop, 4500);
    const initial = setTimeout(loop, 2000);
    return () => {
      clearInterval(t);
      clearTimeout(initial);
    };
  }, [reduce]);

  const cards = week === 0 ? WEEK_A : WEEK_B;

  return (
    <div
      className="relative flex h-full min-h-[340px] w-full flex-col items-center justify-center gap-4 py-4 lg:min-h-[400px]"
      style={{ fontFamily: SANS }}
    >
      {/* Header row: week label + legend */}
      <div className="flex w-full max-w-[400px] items-center justify-between px-2">
        <div className="relative h-5 min-w-[90px] text-[11px] font-semibold uppercase tracking-[0.15em] text-[#999]">
          <AnimatePresence mode="wait">
            <motion.span
              key={week}
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="absolute left-0 whitespace-nowrap"
            >
              Week {12 + week}
            </motion.span>
          </AnimatePresence>
        </div>
        <div className="flex gap-2 text-[9px] text-[#999]">
          <div className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Active
          </div>
          <div className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
            Retiring
          </div>
        </div>
      </div>

      {/* Cards row */}
      <div className="flex gap-2.5">
        <AnimatePresence mode="popLayout">
          {cards.map((card, i) => (
            <motion.div
              key={card.id}
              layout
              initial={{ opacity: 0, x: 40, scale: 0.9 }}
              animate={{
                opacity: card.state === "tired" ? 0.45 : 1,
                x: 0,
                scale: 1,
              }}
              exit={{ opacity: 0, x: -40, scale: 0.9 }}
              transition={{ duration: 0.5, ease: EASE, delay: i * 0.06 }}
              className={`relative flex h-[150px] w-[78px] flex-col overflow-hidden rounded-xl border shadow-sm ${
                card.state === "tired"
                  ? "border-red-200 bg-red-50/60"
                  : "border-[#e8e5e0] bg-white"
              }`}
            >
              {/* Media thumbnail (stays the same across cycles) */}
              <div
                className={`relative h-[54px] w-full ${
                  card.state === "tired"
                    ? "bg-gradient-to-br from-red-100 to-red-50"
                    : "bg-gradient-to-br from-[#d4c9b8] to-[#8b7a5e]"
                }`}
              >
                <div className="absolute inset-0 flex items-center justify-center text-[9px] font-medium text-white/80">
                  media
                </div>
              </div>

              {/* Headline */}
              <div className="flex-1 px-1.5 py-1.5">
                <div className="mb-1 truncate text-[8px] font-medium leading-tight text-[#1a1a1a]">
                  {card.headline}
                </div>
                <div className="truncate text-[7px] text-[#888]">{card.cta}</div>
              </div>

              {/* Label footer */}
              <div className="flex items-center justify-between border-t border-[#e8e5e0] px-1.5 py-1">
                <span className="text-[8px] font-semibold text-[#1a1a1a]">
                  {card.label}
                </span>
                {card.state === "tired" ? (
                  <span className="rounded-full bg-red-500/10 px-1 py-[1px] text-[7px] font-medium uppercase text-red-600">
                    tired
                  </span>
                ) : card.state === "new" ? (
                  <motion.span
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="rounded-full bg-emerald-500/10 px-1 py-[1px] text-[7px] font-medium uppercase text-emerald-700"
                  >
                    new
                  </motion.span>
                ) : (
                  <span className="rounded-full bg-emerald-500/10 px-1 py-[1px] text-[7px] font-medium uppercase text-emerald-700">
                    active
                  </span>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Callout: what actually changes */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.5, ease: EASE, delay: 0.8 }}
        className="flex flex-wrap items-center justify-center gap-1.5 px-4 text-[10px]"
      >
        <span className="text-[#999]">Kleiber rewrites</span>
        <span className="rounded-full bg-[#1a1816] px-2 py-[2px] font-medium text-white">
          headline
        </span>
        <span className="rounded-full bg-[#1a1816] px-2 py-[2px] font-medium text-white">
          subhead
        </span>
        <span className="rounded-full bg-[#1a1816] px-2 py-[2px] font-medium text-white">
          CTA
        </span>
        <span className="text-[#999]">· your media stays</span>
      </motion.div>
    </div>
  );
}
