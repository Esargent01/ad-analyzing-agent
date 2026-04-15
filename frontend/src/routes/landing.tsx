import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";

import { api } from "@/lib/api/client";
import { FeatureSection } from "@/components/landing/FeatureSection";
import { DecomposeAnimation } from "@/components/landing/DecomposeAnimation";
import { GenomeAnimation } from "@/components/landing/GenomeAnimation";
import { TestingAnimation } from "@/components/landing/TestingAnimation";
import { CompoundAnimation } from "@/components/landing/CompoundAnimation";
import { fadeInUp, staggerContainer, viewportConfig } from "@/components/landing/animation-variants";

const SERIF = "'DM Serif Display', serif";
const SANS = "'Outfit', sans-serif";

export function LandingRoute() {
  const [email, setEmail] = useState("");
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

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submitEmail(email);
  };

  const onNavSubmit = (e: FormEvent) => {
    e.preventDefault();
    submitEmail(navEmail);
  };

  return (
    <div style={{ fontFamily: SANS }} className="min-h-screen bg-[#faf9f7]">
      {/* ── Nav ─────────────────────────────────────────────────── */}
      <nav className="absolute left-0 right-0 top-0 z-30 flex items-center justify-between px-6 py-5 sm:px-10 lg:px-16">
        {/* Logo — left */}
        <span
          className="text-[22px] tracking-tight text-white"
          style={{ fontFamily: SERIF }}
        >
          Kleiber
        </span>

        {/* Actions — right */}
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
                  className="h-9 w-48 rounded-full border border-white/20 bg-white/10 px-4 text-[13px] text-white placeholder:text-white/40 backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-white/30"
                  style={{ fontFamily: SANS }}
                />
              </motion.form>
            )}
          </AnimatePresence>
          {status === "success" ? (
            <span className="rounded-full bg-emerald-500/20 px-4 py-2 text-[13px] font-medium text-emerald-300 backdrop-blur-sm">
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
              className="h-9 whitespace-nowrap rounded-full bg-white px-5 text-[13px] font-medium text-[#1a1a1a] transition-all hover:bg-white/90 active:scale-[0.98] disabled:opacity-50"
              style={{ fontFamily: SANS }}
            >
              {status === "submitting" ? "..." : "Join beta"}
            </button>
          )}
        </div>
      </nav>

      {/* ── Hero — full viewport ────────────────────────────────── */}
      <section
        className="relative flex min-h-screen items-center bg-cover bg-right bg-no-repeat"
        style={{ backgroundImage: "url('/hero-creative-wall.png')" }}
      >
        {/* Dark overlay for legibility, heavier on left */}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(to right, rgba(15,12,10,0.82) 30%, rgba(15,12,10,0.55) 55%, rgba(15,12,10,0.25) 80%, rgba(15,12,10,0.15) 100%)",
          }}
        />

        <div className="relative z-10 mx-auto w-full max-w-7xl px-6 sm:px-10 lg:px-16">
          <motion.div
            className="max-w-2xl py-24"
            initial="hidden"
            animate="visible"
            variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.15 } } }}
          >
            {/* Badge */}
            <motion.div variants={fadeInUp} className="mb-8 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-2 backdrop-blur-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              <span className="text-[12px] font-medium tracking-wide text-white/80">
                Beta access opening soon
              </span>
            </motion.div>

            {/* Heading — large serif, Sierra style */}
            <motion.h1 variants={fadeInUp}
              className="mb-6 text-[clamp(2.5rem,6vw,4.5rem)] leading-[1.08] tracking-tight text-white"
              style={{ fontFamily: SERIF }}
            >
              Better ad performance.
              <br />
              Powered by AI agents.
            </motion.h1>

            <motion.p variants={fadeInUp} className="mb-10 max-w-lg text-[16px] leading-relaxed text-white/70">
              Kleiber decomposes your creatives into testable
              elements, runs autonomous optimization cycles, and compounds
              learnings over time. You approve — we execute.
            </motion.p>

            {/* CTA — pill-style buttons, Sierra aesthetic */}
            <motion.div variants={fadeInUp} id="join" className="flex flex-wrap items-center gap-4">
              {status === "success" ? (
                <div className="rounded-full bg-emerald-500/20 px-6 py-3 backdrop-blur-sm">
                  <span className="text-[15px] font-medium text-emerald-300">
                    You're on the list — we'll be in touch!
                  </span>
                </div>
              ) : (
                <form
                  onSubmit={onSubmit}
                  noValidate
                  className="flex flex-col gap-3 sm:flex-row sm:items-center"
                >
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (status === "error") setStatus("idle");
                    }}
                    className="h-12 w-64 rounded-full border border-white/20 bg-white/10 px-5 text-[14px] text-white placeholder:text-white/40 backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-white/30"
                    style={{ fontFamily: SANS }}
                  />
                  <button
                    type="submit"
                    disabled={status === "submitting"}
                    className="h-12 whitespace-nowrap rounded-full bg-white px-8 text-[14px] font-medium text-[#1a1a1a] transition-all hover:bg-white/90 active:scale-[0.98] disabled:opacity-50"
                    style={{ fontFamily: SANS }}
                  >
                    {status === "submitting"
                      ? "Joining..."
                      : "Join the beta"}
                  </button>
                </form>
              )}
            </motion.div>
            {status === "error" && (
              <p className="mt-3 text-[13px] text-red-300">{errorMsg}</p>
            )}
            {status !== "success" && (
              <p className="mt-4 text-[12px] text-white/40">
                No credit card required. We'll notify you when your access is
                ready.
              </p>
            )}
          </motion.div>
        </div>
      </section>

      {/* ── Social proof / metrics ──────────────────────────────── */}
      <section className="border-b border-[#e8e5e0] bg-[#faf9f7] py-20">
        <motion.div
          className="mx-auto max-w-5xl px-6 text-center sm:px-10"
          initial="hidden"
          whileInView="visible"
          viewport={viewportConfig}
          variants={staggerContainer}
        >
          <motion.p variants={fadeInUp} className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
            Built for performance marketers
          </motion.p>
          <motion.h2 variants={fadeInUp}
            className="mb-4 text-[clamp(1.5rem,3vw,2.25rem)] tracking-tight text-[#1a1a1a]"
            style={{ fontFamily: SERIF }}
          >
            The metrics that matter
          </motion.h2>
          <motion.p variants={fadeInUp} className="mx-auto mb-14 max-w-md text-[14px] leading-relaxed text-[#777]">
            Early beta results across campaigns of all sizes.
          </motion.p>
          <motion.div className="grid grid-cols-2 gap-8 sm:grid-cols-4" variants={staggerContainer}>
            {[
              { value: "4.2%", label: "Avg CTR lift" },
              { value: "3.8x", label: "ROAS improvement" },
              { value: "-62%", label: "Time to optimize" },
              { value: "12k+", label: "Variants tested" },
            ].map(({ value, label }) => (
              <motion.div key={label} variants={fadeInUp} className="flex flex-col items-center">
                <span
                  className="mb-1 text-[clamp(1.75rem,3vw,2.5rem)] tracking-tight text-[#1a1a1a]"
                  style={{ fontFamily: SERIF }}
                >
                  {value}
                </span>
                <span className="text-[13px] text-[#999]">{label}</span>
              </motion.div>
            ))}
          </motion.div>
        </motion.div>
      </section>

      {/* ── Feature sections (Sierra-style 2-column) ──────────── */}
      <FeatureSection
        heading="Decompose your creatives"
        description="Your ads are broken into swappable elements — headlines, CTAs, media, and audiences. Each component becomes an independent variable in a vast optimization space."
        figurePosition="left"
        background="cream"
        animation={<DecomposeAnimation />}
      />
      <FeatureSection
        heading="Build winning genomes"
        description="Elements recombine into ad genomes — unique variant configurations drawn from your gene pool. The system generates combinations humans would never think to test."
        figurePosition="right"
        background="white"
        animation={<GenomeAnimation />}
      />
      <FeatureSection
        heading="Test with statistical rigor"
        description="Two-proportion z-tests, minimum sample sizes, and fatigue detection ensure every decision is backed by real significance — not vibes."
        figurePosition="left"
        background="cream"
        animation={<TestingAnimation />}
      />
      <FeatureSection
        heading="Compound learnings over time"
        description="Winning elements are recombined. Losers are paused. Each cycle feeds the next, building an ever-growing knowledge base of what works for your brand."
        figurePosition="right"
        background="white"
        animation={<CompoundAnimation />}
      />

      {/* ── Bottom CTA ──────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-[#1a1816] py-32">
        <div className="pointer-events-none absolute inset-0 opacity-[0.04]" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)", backgroundSize: "40px 40px" }} />
        <motion.div
          className="relative z-10 mx-auto max-w-2xl px-6 text-center sm:px-10"
          initial="hidden"
          whileInView="visible"
          viewport={viewportConfig}
          variants={staggerContainer}
        >
          <motion.h2 variants={fadeInUp}
            className="mb-4 text-[clamp(1.75rem,4vw,3rem)] tracking-tight text-white"
            style={{ fontFamily: SERIF }}
          >
            Ready to optimize?
          </motion.h2>
          <motion.p variants={fadeInUp} className="mb-10 text-[15px] leading-relaxed text-white/60">
            Join the beta and let AI agents handle the grind of creative testing
            while you focus on strategy.
          </motion.p>
          {status === "success" ? (
            <span className="inline-block rounded-full bg-emerald-500/20 px-6 py-3 text-[15px] font-medium text-emerald-300">
              You're on the list — we'll be in touch!
            </span>
          ) : (
            <form
              onSubmit={onSubmit}
              noValidate
              className="mx-auto flex max-w-md flex-col items-center gap-3 sm:flex-row"
            >
              <input
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (status === "error") setStatus("idle");
                }}
                className="h-12 w-full rounded-full border border-white/20 bg-white/10 px-5 text-[14px] text-white placeholder:text-white/40 backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-white/30 sm:flex-1"
                style={{ fontFamily: SANS }}
              />
              <button
                type="submit"
                disabled={status === "submitting"}
                className="h-12 w-full whitespace-nowrap rounded-full bg-white px-8 text-[14px] font-medium text-[#1a1a1a] transition-all hover:bg-white/90 active:scale-[0.98] disabled:opacity-50 sm:w-auto"
                style={{ fontFamily: SANS }}
              >
                {status === "submitting" ? "..." : "Join beta"}
              </button>
            </form>
          )}
        </motion.div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="border-t border-[#e8e5e0] bg-[#faf9f7]">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-8 sm:px-10 lg:px-16">
          <p className="text-[12px] text-[#aaa]">
            &copy; 2026 Kleiber
          </p>
          <div className="flex gap-6 text-[12px] text-[#aaa]">
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
