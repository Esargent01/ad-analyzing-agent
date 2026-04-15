import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

const SANS = "'Outfit', sans-serif";
const SERIF = "'DM Serif Display', serif";
const EASE = [0.16, 1, 0.3, 1] as const;

const ITEMS = [
  {
    q: "What does day 1 look like?",
    a: "You import the Meta campaign you want Kleiber to manage. We pull in your existing ads and creatives from your media library to seed the gene pool — no upload required. Your first daily report lands in your inbox within 24 hours; the first weekly report lands the following Monday.",
  },
  {
    q: "Which platforms does Kleiber support?",
    a: "Meta only for now (Facebook + Instagram). Google Ads and TikTok are on the roadmap. If you run on other platforms, tell us which one matters most — it shapes what we build next.",
  },
  {
    q: "How much control do I have over what gets generated?",
    a: "You can write rules for the creative-cycling agent — e.g. \"never test discount-led copy,\" \"always include our brand name in the headline,\" or \"keep CTAs under 5 words.\" Your media stays exactly as you uploaded it; only headlines, subheads, and CTAs get rewritten.",
  },
  {
    q: "Does anything happen without my approval?",
    a: "No. Every pause, scale, and launch lands in an approval queue. You get a notification, review it in about 60 seconds, and click approve — or reject. Nothing moves to Meta without your sign-off.",
  },
  {
    q: "Who is this built for?",
    a: "Early-stage advertisers and growing brands spending up to about $1k/month on Meta. If you're just starting out and don't have time to babysit creative testing, Kleiber is built for you. Large agencies and $50k+/mo brands — we'll get there, but not yet.",
  },
  {
    q: "What does it cost?",
    a: "Free during the beta. After launch, flat SaaS pricing — no percentage of ad spend, no per-variant fees. One predictable monthly bill.",
  },
] as const;

export function FAQ() {
  const [open, setOpen] = useState<number | null>(0);

  return (
    <section className="bg-white py-24 lg:py-28" style={{ fontFamily: SANS }}>
      <div className="mx-auto max-w-3xl px-6 sm:px-10">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.6, ease: EASE }}
          className="mb-10 text-center"
        >
          <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
            Before you hire the team
          </p>
          <h2
            className="text-[clamp(1.5rem,3vw,2.5rem)] leading-[1.15] tracking-tight text-[#1a1a1a]"
            style={{ fontFamily: SERIF }}
          >
            What directors ask first
          </h2>
        </motion.div>

        <div className="divide-y divide-[#e8e5e0] border-y border-[#e8e5e0]">
          {ITEMS.map((item, i) => {
            const isOpen = open === i;
            return (
              <motion.div
                key={item.q}
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.2 }}
                transition={{ duration: 0.4, ease: EASE, delay: i * 0.05 }}
              >
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : i)}
                  className="flex w-full items-center justify-between gap-4 py-5 text-left"
                >
                  <span className="text-[15px] font-medium text-[#1a1a1a]">
                    {item.q}
                  </span>
                  <motion.span
                    animate={{ rotate: isOpen ? 45 : 0 }}
                    transition={{ duration: 0.25, ease: EASE }}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[#e8e5e0] text-[14px] text-[#666]"
                  >
                    +
                  </motion.span>
                </button>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3, ease: EASE }}
                      className="overflow-hidden"
                    >
                      <p className="pb-5 pr-10 text-[14px] leading-relaxed text-[#666]">
                        {item.a}
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
