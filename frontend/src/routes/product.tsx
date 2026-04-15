import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";

import { api } from "@/lib/api/client";
import { FeatureSection } from "@/components/landing/FeatureSection";
import { MonitorAnimation } from "@/components/product/MonitorAnimation";
import { CycleAnimation } from "@/components/product/CycleAnimation";
import { ApprovalAnimation } from "@/components/product/ApprovalAnimation";
import { ReportAnimation } from "@/components/product/ReportAnimation";
import { ControlPanel } from "@/components/product/ControlPanel";
import { DailyLoop } from "@/components/product/DailyLoop";
import { FAQ } from "@/components/product/FAQ";
import { fadeInUp, staggerContainer } from "@/components/landing/animation-variants";

const SERIF = "'DM Serif Display', serif";
const SANS = "'Outfit', sans-serif";

const STATS = [
  { value: "4.2%", label: "Avg CTR lift" },
  { value: "3.8x", label: "ROAS improvement" },
  { value: "-62%", label: "Time to optimize" },
  { value: "12k+", label: "Variants tested" },
];

const TRUST_PILLS = [
  { icon: "🎁", label: "Free during beta" },
  { icon: "📱", label: "Meta campaigns" },
  { icon: "📬", label: "Daily briefings, weekly reports" },
  { icon: "✋", label: "Nothing ships without your sign-off" },
];

export function ProductRoute() {
  const [navEmail, setNavEmail] = useState("");
  const [status, setStatus] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [navOpen, setNavOpen] = useState(false);
  const navInputRef = useRef<HTMLInputElement>(null);

  const submitEmail = async (addr: string) => {
    const normalized = addr.trim().toLowerCase();
    if (!normalized || !normalized.includes("@")) {
      setErrorMsg("Please enter a valid email address.");
      setStatus("error");
      return;
    }
    setStatus("submitting");
    try {
      await api.post("/api/beta-signup", { email: normalized });
      setStatus("success");
    } catch {
      setErrorMsg("Something went wrong. Please try again.");
      setStatus("error");
    }
  };

  const onNavSubmit = (e: FormEvent) => {
    e.preventDefault();
    submitEmail(navEmail);
  };

  return (
    <div style={{ fontFamily: SANS }} className="min-h-screen bg-[#faf9f7]">
      {/* ── Nav ─────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-30 flex items-center justify-between border-b border-[#e8e5e0] bg-[#faf9f7]/90 px-6 py-5 backdrop-blur-sm sm:px-10 lg:px-16">
        <Link
          to="/"
          className="text-[22px] tracking-tight text-[#1a1a1a] no-underline"
          style={{ fontFamily: SERIF }}
        >
          Kleiber
        </Link>

        <div className="flex items-center gap-3">
          <AnimatePresence>
            {navOpen && status !== "success" && (
              <motion.form
                onSubmit={onNavSubmit}
                noValidate
                className="flex items-center"
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: "auto", opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                style={{ overflow: "hidden" }}
              >
                <input
                  ref={navInputRef}
                  type="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  value={navEmail}
                  onChange={(e) => {
                    setNavEmail(e.target.value);
                    if (status === "error") setStatus("idle");
                  }}
                  className="h-9 w-48 rounded-full border border-[#e8e5e0] bg-white px-4 text-[13px] text-[#1a1a1a] placeholder:text-[#aaa] focus:outline-none focus:ring-2 focus:ring-[#1a1a1a]/10"
                  style={{ fontFamily: SANS }}
                />
              </motion.form>
            )}
          </AnimatePresence>
          {status === "success" ? (
            <span className="rounded-full bg-emerald-100 px-4 py-2 text-[13px] font-medium text-emerald-700">
              You're on the list!
            </span>
          ) : (
            <button
              type={navOpen ? "submit" : "button"}
              disabled={status === "submitting"}
              onClick={() => {
                if (!navOpen) {
                  setNavOpen(true);
                  setTimeout(() => navInputRef.current?.focus(), 350);
                } else {
                  submitEmail(navEmail);
                }
              }}
              className="h-9 whitespace-nowrap rounded-full bg-[#1a1a1a] px-5 text-[13px] font-medium text-white transition-all hover:bg-[#333] active:scale-[0.98] disabled:opacity-50"
              style={{ fontFamily: SANS }}
            >
              {status === "submitting" ? "..." : "Join beta"}
            </button>
          )}
        </div>
      </nav>

      {status === "error" && (
        <div className="bg-red-50 px-6 py-2 text-center text-[12px] text-red-600">
          {errorMsg}
        </div>
      )}

      {/* ── Intro hero ─────────────────────────────────────────── */}
      <section className="border-b border-[#e8e5e0] bg-[#faf9f7] pt-20 pb-16 lg:pt-24 lg:pb-20">
        <motion.div
          className="mx-auto max-w-4xl px-6 text-center sm:px-10"
          initial="hidden"
          animate="visible"
          variants={staggerContainer}
        >
          <motion.p
            variants={fadeInUp}
            className="mb-4 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]"
          >
            Your marketing department
          </motion.p>
          <motion.h1
            variants={fadeInUp}
            className="mb-6 text-[clamp(2.25rem,5.5vw,4rem)] leading-[1.05] tracking-tight text-[#1a1a1a]"
            style={{ fontFamily: SERIF }}
          >
            Your full-service ad team.
            <br />
            Running 24/7.
          </motion.h1>
          <motion.p
            variants={fadeInUp}
            className="mx-auto mb-8 max-w-xl text-[16px] leading-relaxed text-[#666]"
          >
            Kleiber is your always-on creative, analytics, and media-buying
            team — running Meta campaigns, testing new copy, flagging winners
            and losers. Every move comes to your desk for sign-off.
          </motion.p>

          {/* Trust pills */}
          <motion.div
            variants={fadeInUp}
            className="flex flex-wrap items-center justify-center gap-2 sm:gap-3"
          >
            {TRUST_PILLS.map((p) => (
              <span
                key={p.label}
                className="flex items-center gap-1.5 rounded-full border border-[#e8e5e0] bg-white px-3 py-1.5 text-[12px] font-medium text-[#555] shadow-sm"
              >
                <span className="text-[13px]">{p.icon}</span>
                {p.label}
              </span>
            ))}
          </motion.div>
        </motion.div>
      </section>

      {/* ── Stats strip ────────────────────────────────────────── */}
      <section className="border-b border-[#e8e5e0] bg-[#f6f5f3] py-14">
        <motion.div
          className="mx-auto grid max-w-5xl grid-cols-2 gap-8 px-6 sm:grid-cols-4 sm:px-10"
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.3 }}
          variants={staggerContainer}
        >
          {STATS.map((s) => (
            <motion.div
              key={s.label}
              variants={fadeInUp}
              className="flex flex-col items-center text-center"
            >
              <span
                className="mb-1 text-[clamp(1.75rem,3vw,2.5rem)] tracking-tight text-[#1a1a1a]"
                style={{ fontFamily: SERIF }}
              >
                {s.value}
              </span>
              <span className="text-[12px] text-[#888]">{s.label}</span>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ── Feature sections ───────────────────────────────────── */}
      <FeatureSection
        heading="Your media analyst, on shift 24/7"
        description="Kleiber pulls Meta metrics every few hours and builds a live picture of what's working across every campaign — so when you sit down for your morning review, the numbers are already current."
        figurePosition="left"
        background="cream"
        animation={<MonitorAnimation />}
      />
      <FeatureSection
        heading="Your creative team, shipping weekly"
        description="Your media stays on-brand — Kleiber's creative team rewrites headlines, subheads, and CTAs into fresh variants every week. Tired copy retires, new angles launch, brand visuals hold the line."
        figurePosition="right"
        background="white"
        animation={<CycleAnimation />}
      />

      {/* ── Daily loop (6-step timeline) ───────────────────────── */}
      <DailyLoop />

      <FeatureSection
        heading="Your strategist brings you the call"
        description="Every pause, scale, and launch lands on your desk with the data behind it — CTR trend, ROAS, confidence interval. You sign off in 60 seconds; the team ships it to Meta."
        figurePosition="left"
        background="cream"
        animation={<ApprovalAnimation />}
      />
      <FeatureSection
        heading="Your weekly stand-up, in your inbox"
        description="A 6 AM daily recap covers yesterday — CTR, ROAS, spend, and which creative element is carrying the campaign. Mondays bring the weekly review: trends, wins, and what to watch."
        figurePosition="right"
        background="white"
        animation={<ReportAnimation />}
      />

      {/* ── Control vs. automation split ───────────────────────── */}
      <ControlPanel />

      {/* ── FAQ ────────────────────────────────────────────────── */}
      <FAQ />

      {/* ── Bottom CTA ─────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-[#1a1816] py-24">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              "radial-gradient(circle at 1px 1px, white 1px, transparent 0)",
            backgroundSize: "40px 40px",
          }}
        />
        <div className="relative z-10 mx-auto max-w-2xl px-6 text-center sm:px-10">
          <h2
            className="mb-4 text-[clamp(1.75rem,4vw,2.75rem)] tracking-tight text-white"
            style={{ fontFamily: SERIF }}
          >
            Take the director's seat
          </h2>
          <p className="mb-8 text-[15px] leading-relaxed text-white/60">
            Join the beta. Hand your Meta campaign to the team. Approve your
            first round of decisions tomorrow morning.
          </p>
          <Link
            to="/"
            className="inline-flex h-12 items-center rounded-full bg-white px-7 text-[14px] font-medium text-[#1a1a1a] no-underline transition-all hover:bg-white/90 active:scale-[0.98]"
            style={{ fontFamily: SANS }}
          >
            Join the beta →
          </Link>
          <div className="mt-5 text-[12px] text-white/40">
            Free during beta · No credit card · Meta campaigns only (for now)
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────── */}
      <footer className="border-t border-[#e8e5e0] bg-[#faf9f7]">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-8 sm:px-10 lg:px-16">
          <p className="text-[12px] text-[#aaa]">&copy; 2026 Kleiber</p>
          <div className="flex gap-6 text-[12px] text-[#aaa]">
            <Link
              to="/"
              className="no-underline transition-colors hover:text-[#666]"
            >
              Home
            </Link>
            <Link
              to="/privacy"
              className="no-underline transition-colors hover:text-[#666]"
            >
              Privacy
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
