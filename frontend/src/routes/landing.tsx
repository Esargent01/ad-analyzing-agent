import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api/client";

/* ------------------------------------------------------------------ */
/*  Sierra-inspired landing page                                       */
/*  Full-bleed hero, serif display heading, pill CTAs, logo wall,      */
/*  rounded-corner feature cards, generous whitespace.                  */
/* ------------------------------------------------------------------ */

const SERIF = "'DM Serif Display', serif";
const SANS = "'Outfit', sans-serif";

export function LandingRoute() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const normalized = email.trim().toLowerCase();
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

  return (
    <div style={{ fontFamily: SANS }} className="min-h-screen bg-[#faf9f7]">
      {/* ── Nav ─────────────────────────────────────────────────── */}
      <nav className="absolute left-0 right-0 top-0 z-30 flex items-center justify-between px-6 py-5 sm:px-10 lg:px-16">
        {/* Logo — left */}
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="inline-block h-7 w-7 rounded-lg bg-white/90"
          />
          <span className="text-[15px] font-semibold tracking-tight text-white">
            Ad Creative Agent
          </span>
        </div>

        {/* Actions — right */}
        <div className="flex items-center gap-4">
          <Link
            to="/sign-in"
            className="text-[13px] font-medium text-white/80 no-underline transition-colors hover:text-white"
          >
            Sign in
          </Link>
          <a
            href="#join"
            className="rounded-full bg-white px-5 py-2 text-[13px] font-medium text-[#1a1a1a] no-underline transition-all hover:bg-white/90"
          >
            Join beta
          </a>
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
          <div className="max-w-2xl py-24">
            {/* Badge */}
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-2 backdrop-blur-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              <span className="text-[12px] font-medium tracking-wide text-white/80">
                Beta access opening soon
              </span>
            </div>

            {/* Heading — large serif, Sierra style */}
            <h1
              className="mb-6 text-[clamp(2.5rem,6vw,4.5rem)] leading-[1.08] tracking-tight text-white"
              style={{ fontFamily: SERIF }}
            >
              Better ad performance.
              <br />
              Powered by AI agents.
            </h1>

            <p className="mb-10 max-w-lg text-[16px] leading-relaxed text-white/70">
              Ad Creative Agent decomposes your creatives into testable
              elements, runs autonomous optimization cycles, and compounds
              learnings over time. You approve — we execute.
            </p>

            {/* CTA — pill-style buttons, Sierra aesthetic */}
            <div id="join" className="flex flex-wrap items-center gap-4">
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
            </div>
            {status === "error" && (
              <p className="mt-3 text-[13px] text-red-300">{errorMsg}</p>
            )}
            {status !== "success" && (
              <p className="mt-4 text-[12px] text-white/40">
                No credit card required. We'll notify you when your access is
                ready.
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ── Social proof / logo wall ────────────────────────────── */}
      <section className="border-b border-[#e8e5e0] bg-[#faf9f7] py-20">
        <div className="mx-auto max-w-5xl px-6 text-center sm:px-10">
          <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
            Built for performance marketers
          </p>
          <h2
            className="mb-4 text-[clamp(1.5rem,3vw,2.25rem)] tracking-tight text-[#1a1a1a]"
            style={{ fontFamily: SERIF }}
          >
            The metrics that matter
          </h2>
          <p className="mx-auto mb-14 max-w-md text-[14px] leading-relaxed text-[#777]">
            Early beta results across campaigns of all sizes.
          </p>
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            {[
              { value: "4.2%", label: "Avg CTR lift" },
              { value: "3.8x", label: "ROAS improvement" },
              { value: "-62%", label: "Time to optimize" },
              { value: "12k+", label: "Variants tested" },
            ].map(({ value, label }) => (
              <div key={label} className="flex flex-col items-center">
                <span
                  className="mb-1 text-[clamp(1.75rem,3vw,2.5rem)] tracking-tight text-[#1a1a1a]"
                  style={{ fontFamily: SERIF }}
                >
                  {value}
                </span>
                <span className="text-[13px] text-[#999]">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ────────────────────────────────────────── */}
      <section className="bg-[#faf9f7] py-24">
        <div className="mx-auto max-w-7xl px-6 sm:px-10 lg:px-16">
          <div className="mb-16 text-center">
            <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
              How it works
            </p>
            <h2
              className="mb-4 text-[clamp(1.5rem,3vw,2.5rem)] tracking-tight text-[#1a1a1a]"
              style={{ fontFamily: SERIF }}
            >
              Autonomous optimization, human approval
            </h2>
          </div>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                step: "01",
                title: "Decompose",
                desc: "Your creatives are broken into swappable elements — headlines, CTAs, media, audiences.",
                color: "#f5ebe0",
              },
              {
                step: "02",
                title: "Test",
                desc: "The system generates variant combinations and deploys them across your ad platforms.",
                color: "#e8f0e8",
              },
              {
                step: "03",
                title: "Analyze",
                desc: "Statistical significance tests and element-level attribution identify what actually works.",
                color: "#e0eaf5",
              },
              {
                step: "04",
                title: "Compound",
                desc: "Winning elements are recombined. Losers are paused. Learnings accumulate over time.",
                color: "#f5e8f0",
              },
            ].map(({ step, title, desc, color }) => (
              <div
                key={step}
                className="rounded-2xl p-8 transition-transform hover:scale-[1.02]"
                style={{ backgroundColor: color }}
              >
                <span className="mb-4 inline-block text-[12px] font-semibold tracking-wide text-[#999]">
                  {step}
                </span>
                <h3
                  className="mb-3 text-[20px] text-[#1a1a1a]"
                  style={{ fontFamily: SERIF }}
                >
                  {title}
                </h3>
                <p className="text-[13px] leading-relaxed text-[#666]">
                  {desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ────────────────────────────────────────────── */}
      <section className="border-t border-[#e8e5e0] bg-white py-24">
        <div className="mx-auto max-w-7xl px-6 sm:px-10 lg:px-16">
          <div className="mb-16 text-center">
            <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.15em] text-[#999]">
              Capabilities
            </p>
            <h2
              className="mb-4 text-[clamp(1.5rem,3vw,2.5rem)] tracking-tight text-[#1a1a1a]"
              style={{ fontFamily: SERIF }}
            >
              Transform your creative testing
            </h2>
          </div>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                title: "Element-level insights",
                desc: "Know exactly which headline, CTA, or audience drives performance — not just which ad variant won.",
              },
              {
                title: "Interaction effects",
                desc: "Discover which element combinations create synergy or conflict. The most valuable long-term data asset.",
              },
              {
                title: "Human in the loop",
                desc: "Every pause, scale, and launch requires your approval. Review proposals from Slack, email, or the dashboard.",
              },
              {
                title: "Statistical rigor",
                desc: "Two-proportion z-tests, minimum sample sizes, and fatigue detection. No vibes — real significance.",
              },
              {
                title: "Thompson sampling",
                desc: "Budget automatically flows to the best-performing variants using Bayesian allocation.",
              },
              {
                title: "Daily + weekly reports",
                desc: "Automated performance summaries delivered to your inbox with actionable insights.",
              },
            ].map(({ title, desc }) => (
              <div
                key={title}
                className="rounded-2xl border border-[#e8e5e0] bg-[#faf9f7] p-8 transition-colors hover:border-[#d4d0ca]"
              >
                <h3
                  className="mb-3 text-[18px] text-[#1a1a1a]"
                  style={{ fontFamily: SERIF }}
                >
                  {title}
                </h3>
                <p className="text-[13px] leading-relaxed text-[#777]">
                  {desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Bottom CTA ──────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-[#1a1816] py-32">
        <div className="pointer-events-none absolute inset-0 opacity-[0.04]" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)", backgroundSize: "40px 40px" }} />
        <div className="relative z-10 mx-auto max-w-2xl px-6 text-center sm:px-10">
          <h2
            className="mb-4 text-[clamp(1.75rem,4vw,3rem)] tracking-tight text-white"
            style={{ fontFamily: SERIF }}
          >
            Ready to optimize?
          </h2>
          <p className="mb-10 text-[15px] leading-relaxed text-white/60">
            Join the beta and let AI agents handle the grind of creative testing
            while you focus on strategy.
          </p>
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
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="border-t border-[#e8e5e0] bg-[#faf9f7]">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-8 sm:px-10 lg:px-16">
          <p className="text-[12px] text-[#aaa]">
            &copy; 2026 Ad Creative Agent
          </p>
          <div className="flex gap-6 text-[12px] text-[#aaa]">
            <Link
              to="/privacy"
              className="no-underline transition-colors hover:text-[#666]"
            >
              Privacy
            </Link>
            <Link
              to="/sign-in"
              className="no-underline transition-colors hover:text-[#666]"
            >
              Sign in
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
