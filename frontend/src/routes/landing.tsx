import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api/client";

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
    <div
      className="min-h-screen"
      style={{ fontFamily: "'Outfit', sans-serif" }}
    >
      {/* Nav */}
      <nav className="flex items-center justify-between px-6 py-5 sm:px-10 lg:px-16">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="inline-block h-7 w-7 rounded-lg bg-[var(--accent)]"
          />
          <span className="text-[15px] font-semibold tracking-tight">
            Ad Creative Agent
          </span>
        </div>
        <Link
          to="/sign-in"
          className="text-[13px] font-medium text-[var(--text-secondary)] no-underline transition-colors hover:text-[var(--text)]"
        >
          Sign in
        </Link>
      </nav>

      {/* Hero — image as full background, form over the left empty space */}
      <main
        className="relative min-h-[calc(100vh-88px)] bg-cover bg-right bg-no-repeat"
        style={{ backgroundImage: "url('/hero-creative-wall.png')" }}
      >
        {/* Gradient overlay — solid on the left for legibility, fading to transparent on the right to reveal the image */}
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(to right, var(--bg) 35%, color-mix(in srgb, var(--bg) 85%, transparent) 50%, color-mix(in srgb, var(--bg) 20%, transparent) 70%, transparent 85%)",
          }}
        />

        <div className="relative mx-auto flex min-h-[calc(100vh-88px)] max-w-7xl items-center px-6 sm:px-10 lg:px-16">
          <div className="max-w-lg py-16">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] px-3.5 py-1.5">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--green)] opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--green)]" />
              </span>
              <span className="text-[12px] font-medium tracking-wide text-[var(--text-secondary)]">
                Beta access opening soon
              </span>
            </div>

            <h1 className="mb-4 text-[clamp(2rem,5vw,3.25rem)] font-semibold leading-[1.1] tracking-tight">
              Your ads, optimized
              <br />
              <span className="text-[var(--accent)]">by AI agents</span>
            </h1>

            <p className="mb-8 max-w-md text-[15px] leading-relaxed text-[var(--text-secondary)]">
              Ad Creative Agent decomposes your creatives into testable
              elements, runs autonomous optimization cycles, and compounds
              learnings over time. You approve — we execute.
            </p>

            {status === "success" ? (
              <div className="rounded-xl border border-[var(--green)]/30 bg-[var(--green)]/5 px-5 py-4">
                <p className="text-[15px] font-medium text-[var(--green)]">
                  You&apos;re on the list!
                </p>
                <p className="mt-1 text-[13px] text-[var(--text-secondary)]">
                  We&apos;ll reach out when your spot is ready.
                </p>
              </div>
            ) : (
              <form onSubmit={onSubmit} noValidate>
                <div className="flex gap-3 sm:max-w-md">
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (status === "error") setStatus("idle");
                    }}
                    className="h-12 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 text-[14px] text-[var(--text)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:ring-offset-2 focus:ring-offset-[var(--bg)]"
                    style={{ fontFamily: "'Outfit', sans-serif" }}
                  />
                  <button
                    type="submit"
                    disabled={status === "submitting"}
                    className="h-12 whitespace-nowrap rounded-lg bg-[var(--accent)] px-6 text-[14px] font-medium text-white transition-all hover:brightness-110 active:brightness-95 disabled:opacity-50"
                    style={{ fontFamily: "'Outfit', sans-serif" }}
                  >
                    {status === "submitting" ? "Joining..." : "Join the beta"}
                  </button>
                </div>
                {status === "error" && (
                  <p className="mt-2.5 text-[13px] text-[var(--red)]">
                    {errorMsg}
                  </p>
                )}
                <p className="mt-3 text-[12px] text-[var(--text-tertiary)]">
                  No credit card required. We&apos;ll notify you when your
                  access is ready.
                </p>
              </form>
            )}

            {/* Social proof */}
            <div className="mt-10 flex flex-wrap gap-x-8 gap-y-3 border-t border-[var(--border)] pt-6">
              {[
                ["4.2%", "Avg CTR lift"],
                ["3.8x", "ROAS improvement"],
                ["-62%", "Time to optimize"],
              ].map(([value, label]) => (
                <div key={label}>
                  <p className="text-lg font-semibold tracking-tight">
                    {value}
                  </p>
                  <p className="text-[12px] text-[var(--text-tertiary)]">
                    {label}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* How it works */}
      <section className="border-t border-[var(--border)] bg-[var(--bg-secondary)]">
        <div className="mx-auto max-w-7xl px-6 py-20 sm:px-10 lg:px-16">
          <h2 className="mb-2 text-center text-[12px] font-semibold uppercase tracking-widest text-[var(--accent)]">
            How it works
          </h2>
          <p className="mb-12 text-center text-2xl font-semibold tracking-tight">
            Autonomous optimization, human approval
          </p>
          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                step: "01",
                title: "Decompose",
                desc: "Your creatives are broken into swappable elements — headlines, CTAs, media, audiences.",
              },
              {
                step: "02",
                title: "Test",
                desc: "The system generates variant combinations and deploys them across your ad platforms.",
              },
              {
                step: "03",
                title: "Analyze",
                desc: "Statistical significance tests and element-level attribution identify what actually works.",
              },
              {
                step: "04",
                title: "Compound",
                desc: "Winning elements are recombined. Losers are paused. Learnings accumulate over time.",
              },
            ].map(({ step, title, desc }) => (
              <div
                key={step}
                className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-6"
              >
                <span className="mb-3 inline-block text-[12px] font-semibold text-[var(--accent)]">
                  {step}
                </span>
                <h3 className="mb-2 text-[15px] font-semibold">{title}</h3>
                <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
                  {desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto max-w-7xl px-6 py-20 sm:px-10 lg:px-16">
          <div className="grid gap-12 lg:grid-cols-3">
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
              <div key={title}>
                <h3 className="mb-2 text-[15px] font-semibold">{title}</h3>
                <p className="text-[13px] leading-relaxed text-[var(--text-secondary)]">
                  {desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="border-t border-[var(--border)] bg-[var(--bg-secondary)]">
        <div className="mx-auto max-w-2xl px-6 py-20 text-center sm:px-10">
          <h2 className="mb-3 text-2xl font-semibold tracking-tight">
            Ready to optimize?
          </h2>
          <p className="mb-8 text-[14px] text-[var(--text-secondary)]">
            Join the beta and let AI agents handle the grind of creative
            testing while you focus on strategy.
          </p>
          {status === "success" ? (
            <p className="text-[15px] font-medium text-[var(--green)]">
              You&apos;re on the list — we&apos;ll be in touch!
            </p>
          ) : (
            <form
              onSubmit={onSubmit}
              noValidate
              className="mx-auto flex max-w-sm gap-3"
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
                className="h-12 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 text-[14px] text-[var(--text)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
                style={{ fontFamily: "'Outfit', sans-serif" }}
              />
              <button
                type="submit"
                disabled={status === "submitting"}
                className="h-12 whitespace-nowrap rounded-lg bg-[var(--accent)] px-6 text-[14px] font-medium text-white transition-all hover:brightness-110 active:brightness-95 disabled:opacity-50"
                style={{ fontFamily: "'Outfit', sans-serif" }}
              >
                {status === "submitting" ? "..." : "Join beta"}
              </button>
            </form>
          )}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-[var(--border)]">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6 sm:px-10 lg:px-16">
          <p className="text-[12px] text-[var(--text-tertiary)]">
            &copy; 2026 Ad Creative Agent
          </p>
          <div className="flex gap-6 text-[12px] text-[var(--text-tertiary)]">
            <Link to="/privacy" className="hover:text-[var(--text)] no-underline">
              Privacy
            </Link>
            <Link to="/sign-in" className="hover:text-[var(--text)] no-underline">
              Sign in
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
