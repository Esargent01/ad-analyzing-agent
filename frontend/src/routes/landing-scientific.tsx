/**
 * A/B-test landing page variant, served at ``/b``.
 *
 * Ported from a Claude Design drop ("Kleiber Site.html") — warm
 * editorial palette with Geist + Instrument Serif italic accents, a
 * terracotta accent hue, and an element-genome chip language. The
 * original drop was a multi-page React prototype; this variant
 * flattens the Home + selected Features/Safety/Pricing sections onto
 * one page so every non-signup interaction is a page-anchor scroll.
 *
 * Contract with the rest of the app:
 * - Every tailwind class / CSS variable in this file is scoped under
 *   ``.kleiber-b-landing`` (see ``landing-scientific.css``) so the
 *   warm palette cannot leak into ``/`` or ``/dashboard``.
 * - The beta-signup form posts to the existing ``/api/beta-signup``
 *   endpoint, same contract as the original ``LandingRoute`` — one
 *   funnel, two landing variants.
 * - Every other link on this page resolves to an on-page ``#anchor``;
 *   no hash-routing, no cross-page jumps. A/B test clarity: whichever
 *   visit came in to ``/b`` stays on ``/b``.
 *
 * Copy audit (landed against the codebase on 2026-04-19):
 * - Removed the "118 ad accounts testing" social-proof line —
 *   lifetime signups were 1 when this shipped, so the claim is false.
 * - Removed the "Bonferroni correction" chip from the stats section
 *   — ``src/services/stats.py`` does not implement multi-test
 *   correction today.
 * - Replaced the speculative $49 / $129 pricing tiers with a
 *   "free during private beta" framing — no pricing has been
 *   committed yet.
 * - Dropped "14-day free trial" references — not a committed SKU.
 * Everything else (z-test, Thompson sampling, min-N 1000, fatigue
 * detection, Fernet, 6am CT cron, 6-step cycle, 5-campaign cap,
 * gene-pool-gated LLM) matches ``src/`` and ``CLAUDE.md`` verbatim.
 */

import { useEffect, useState, type FormEvent } from "react";

import { api } from "@/lib/api/client";

import "./landing-scientific.css";

/* ---------------------------------------------------------------- */
/* Page root                                                         */
/* ---------------------------------------------------------------- */

export function LandingScientificRoute() {
  useEffect(() => {
    const prev = document.title;
    document.title = "Kleiber — Autonomous ad-testing for Meta";
    return () => {
      document.title = prev;
    };
  }, []);

  return (
    <div className="kleiber-b-landing">
      <Nav />
      <main>
        <Hero />
        <TrustStrip />
        <ProblemSection />
        <FeatureReel />
        <StatsLanguageSection />
        <HowItWorksPreview />
        <SafetySection />
        <PricingSection />
        <SignupSection />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Nav                                                               */
/* ---------------------------------------------------------------- */

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 40,
        background: scrolled ? "oklch(98.5% 0.006 80 / 0.85)" : "transparent",
        backdropFilter: scrolled ? "blur(10px) saturate(1.2)" : "none",
        WebkitBackdropFilter: scrolled ? "blur(10px) saturate(1.2)" : "none",
        borderBottom: scrolled
          ? "1px solid var(--b-border-soft)"
          : "1px solid transparent",
        transition: "all .2s",
      }}
    >
      <div
        className="b-wrap"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          height: 68,
        }}
      >
        <a
          href="#top"
          style={{ display: "flex", alignItems: "center", gap: 9 }}
        >
          <KleiberMark size={22} />
          <span
            style={{
              fontSize: 18,
              letterSpacing: "-0.02em",
              fontWeight: 500,
              color: "var(--b-ink)",
            }}
          >
            Kleiber
          </span>
        </a>
        <div
          style={{ display: "flex", alignItems: "center", gap: 24 }}
          className="b-nav-links"
        >
          <NavAnchor href="#how-it-works">How it works</NavAnchor>
          <NavAnchor href="#safety">Safety</NavAnchor>
          <NavAnchor href="#pricing">Pricing</NavAnchor>
          <a
            href="#signup"
            className="b-btn b-btn-primary b-btn-sm"
            style={{ textDecoration: "none" }}
          >
            Request access
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d="M3 6h6m-3-3 3 3-3 3"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </a>
        </div>
      </div>
    </nav>
  );
}

function NavAnchor({ href, children }: { href: string; children: string }) {
  return (
    <a
      href={href}
      style={{
        fontSize: 14,
        color: "var(--b-muted)",
        fontWeight: 400,
        padding: "6px 2px",
        transition: "color .15s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.color = "var(--b-ink)")}
      onMouseLeave={(e) => (e.currentTarget.style.color = "var(--b-muted)")}
    >
      {children}
    </a>
  );
}

/* ---------------------------------------------------------------- */
/* Logo mark                                                         */
/* ---------------------------------------------------------------- */

function KleiberMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-label="Kleiber"
    >
      <rect x="4" y="4" width="3" height="24" rx="1.5" fill="currentColor" />
      <path
        d="M7 16 L22 6 L22 9 L11 16 L22 23 L22 26 Z"
        fill="currentColor"
      />
      <circle cx="26" cy="8" r="2" fill="currentColor" opacity="0.45" />
    </svg>
  );
}

/* ---------------------------------------------------------------- */
/* Hero                                                              */
/* ---------------------------------------------------------------- */

function Hero() {
  return (
    <section
      id="top"
      style={{
        paddingTop: 56,
        paddingBottom: 60,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        className="b-wrap"
        style={{ textAlign: "center", position: "relative", zIndex: 2 }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "5px 13px",
            borderRadius: 99,
            border: "1px solid var(--b-border)",
            background: "var(--b-paper-2)",
            fontSize: 12.5,
            color: "var(--b-ink-2)",
            marginBottom: 28,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 99,
              background: "var(--b-win)",
            }}
          />
          <span
            className="b-mono"
            style={{ fontSize: 11, letterSpacing: "0.05em" }}
          >
            Private beta · by invitation
          </span>
        </div>
        <h1
          className="b-h-display"
          style={{ margin: "0 auto", maxWidth: 980, textWrap: "balance" }}
        >
          Your Meta ads,
          <br />
          running <span className="b-serif">the scientific method</span>
          <br />
          on themselves.
        </h1>
        <p
          className="b-h-sub"
          style={{
            marginTop: 22,
            maxWidth: 640,
            marginLeft: "auto",
            marginRight: "auto",
            textWrap: "pretty",
          }}
        >
          Kleiber watches what you&apos;re already running, uses real
          statistics to decide what&apos;s winning, and remixes the winning
          elements into new variants — every night at 6 AM.
        </p>
        <div
          style={{
            display: "flex",
            gap: 10,
            justifyContent: "center",
            marginTop: 32,
            flexWrap: "wrap",
          }}
        >
          <a
            href="#signup"
            className="b-btn b-btn-primary b-btn-lg"
            style={{ textDecoration: "none" }}
          >
            Request access
          </a>
          <a
            href="#how-it-works"
            className="b-btn b-btn-ghost b-btn-lg"
            style={{ textDecoration: "none" }}
          >
            See how it works
          </a>
        </div>
        <div
          className="b-mono"
          style={{ fontSize: 11.5, color: "var(--b-muted)", marginTop: 18 }}
        >
          Connects via Meta OAuth · you own your data
        </div>
      </div>

      {/* Big product shot */}
      <div
        className="b-wrap"
        style={{ marginTop: 56, position: "relative" }}
      >
        <DashboardMock />
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Dashboard mock — simplified port                                  */
/* ---------------------------------------------------------------- */

const VARIANTS = [
  {
    name: "V-0041",
    genome: ["AI-Powered Ad Care", "Babysit your ads", "IMG_673", "LEARN_MORE"],
    roas: "4.81×",
    z: "+3.42",
    sig: "win" as const,
    pct: 38,
  },
  {
    name: "V-0039",
    genome: ["Stop wasting ad spend", "Stats-driven testing", "IMG_714", "SIGN_UP"],
    roas: "4.02×",
    z: "+2.18",
    sig: "win" as const,
    pct: 28,
  },
  {
    name: "V-0037",
    genome: ["Always-on optimization", "Babysit your ads", "IMG_673", "GET_OFFER"],
    roas: "3.10×",
    z: "+0.41",
    sig: "flat" as const,
    pct: 18,
  },
  {
    name: "V-0035",
    genome: ["Meta ads, on autopilot", "Autonomous testing", "IMG_602", "LEARN_MORE"],
    roas: "2.24×",
    z: "−0.84",
    sig: "flat" as const,
    pct: 12,
  },
  {
    name: "V-0033",
    genome: ["Test ads while you sleep", "Hands-off growth", "IMG_511", "SHOP_NOW"],
    roas: "1.12×",
    z: "−2.91",
    sig: "lose" as const,
    pct: 4,
  },
];

function AppWindow({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        borderRadius: 14,
        overflow: "hidden",
        border: "1px solid var(--b-border)",
        background: "white",
        boxShadow:
          "0 30px 80px oklch(30% 0.02 60 / 0.12), 0 6px 18px oklch(30% 0.02 60 / 0.06)",
      }}
    >
      <div
        style={{
          height: 38,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 14px",
          background: "var(--b-paper-2)",
          borderBottom: "1px solid var(--b-border)",
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 99,
              background: "oklch(87% 0.01 70)",
            }}
          />
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 99,
              background: "oklch(87% 0.01 70)",
            }}
          />
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 99,
              background: "oklch(87% 0.01 70)",
            }}
          />
        </div>
        <div
          style={{
            fontFamily: "var(--b-mono)",
            fontSize: 11,
            color: "var(--b-muted)",
          }}
        >
          {title}
        </div>
        <div style={{ width: 40 }} />
      </div>
      {children}
    </div>
  );
}

function DashboardMock() {
  return (
    <AppWindow title="app.kleiber.ai / campaigns / summer-sale">
      <div
        data-b-grid
        style={{
          display: "grid",
          gridTemplateColumns: "220px 1fr",
          minHeight: 560,
        }}
      >
        <DashboardSidebar />
        <DashboardMain />
      </div>
    </AppWindow>
  );
}

function DashboardSidebar() {
  return (
    <div
      style={{
        background: "var(--b-paper-2)",
        borderRight: "1px solid var(--b-border)",
        padding: "16px 12px",
        fontSize: 13,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 8px",
        }}
      >
        <KleiberMark size={18} />
        <span style={{ fontWeight: 500, letterSpacing: "-0.01em" }}>
          Acme Co.
        </span>
      </div>
      <div style={{ height: 14 }} />
      <SideItem active>Campaigns</SideItem>
      <SideItem>Gene pool</SideItem>
      <SideItem badge={3}>Approvals</SideItem>
      <SideItem>Reports</SideItem>
      <SideItem>Integrations</SideItem>
      <div style={{ height: 20 }} />
      <div
        style={{
          fontFamily: "var(--b-mono)",
          fontSize: 10,
          color: "var(--b-muted)",
          padding: "4px 8px",
          letterSpacing: "0.08em",
        }}
      >
        CAMPAIGNS
      </div>
      <SideItem subtle active>
        ● summer-sale
      </SideItem>
      <SideItem subtle>● brand-awareness</SideItem>
      <SideItem subtle>● winter-drop</SideItem>
      <SideItem subtle>○ launch-ctrl</SideItem>
      <div style={{ marginTop: 20 }}>
        <div
          style={{
            padding: 12,
            borderRadius: 10,
            background: "white",
            border: "1px solid var(--b-border)",
            fontSize: 11.5,
            lineHeight: 1.4,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 4,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: 99,
                background: "var(--b-win)",
              }}
            />
            <span
              style={{
                fontFamily: "var(--b-mono)",
                fontSize: 10,
                color: "var(--b-muted)",
              }}
            >
              NEXT CYCLE
            </span>
          </div>
          <div style={{ fontWeight: 500 }}>Tomorrow, 6:00 AM CT</div>
        </div>
      </div>
    </div>
  );
}

function SideItem({
  children,
  active,
  subtle,
  badge,
}: {
  children: React.ReactNode;
  active?: boolean;
  subtle?: boolean;
  badge?: number;
}) {
  return (
    <div
      style={{
        padding: "7px 10px",
        borderRadius: 7,
        background: active ? "white" : "transparent",
        border: active ? "1px solid var(--b-border)" : "1px solid transparent",
        color: subtle ? "var(--b-muted)" : "var(--b-ink-2)",
        fontSize: subtle ? 12.5 : 13,
        fontWeight: active && !subtle ? 500 : 400,
        display: "flex",
        alignItems: "center",
        gap: 6,
        marginBottom: 2,
      }}
    >
      {children}
      {badge ? (
        <span
          style={{
            marginLeft: "auto",
            background: "var(--b-accent)",
            color: "white",
            fontSize: 10,
            padding: "2px 6px",
            borderRadius: 99,
            fontFamily: "var(--b-mono)",
            fontWeight: 500,
          }}
        >
          {badge}
        </span>
      ) : null}
    </div>
  );
}

function DashboardMain() {
  return (
    <div style={{ padding: 26 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 18,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "var(--b-mono)",
              fontSize: 10.5,
              color: "var(--b-muted)",
              letterSpacing: "0.1em",
            }}
          >
            CAMPAIGN
          </div>
          <div
            style={{
              fontSize: 22,
              fontWeight: 500,
              letterSpacing: "-0.02em",
              marginTop: 2,
            }}
          >
            summer-sale
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            <span className="b-chip b-chip-win b-chip-dot">RUNNING</span>
            <span className="b-chip b-mono">12 variants active</span>
            <span className="b-chip b-mono">$847 spent · 30d</span>
          </div>
        </div>
      </div>

      <div
        data-b-grid
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 10,
          marginBottom: 18,
        }}
      >
        <Stat label="ROAS" value="3.42×" delta="+0.61" good />
        <Stat label="CPA" value="$14.20" delta="−$3.10" good />
        <Stat label="CTR" value="2.08%" delta="+0.42" good />
        <Stat label="SPEND" value="$847" delta="$28/day" />
      </div>

      <div
        style={{
          border: "1px solid var(--b-border)",
          borderRadius: 12,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "40px 1.6fr 1fr 1fr 90px 70px",
            padding: "9px 14px",
            fontFamily: "var(--b-mono)",
            fontSize: 10,
            color: "var(--b-muted)",
            letterSpacing: "0.1em",
            background: "var(--b-paper-2)",
            borderBottom: "1px solid var(--b-border)",
          }}
        >
          <span />
          <span>VARIANT · GENOME</span>
          <span>ROAS</span>
          <span>Z-SCORE</span>
          <span>STATUS</span>
          <span style={{ textAlign: "right" }}>BUDGET</span>
        </div>
        {VARIANTS.map((v, i) => (
          <VariantRow key={v.name} v={v} i={i} />
        ))}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  delta,
  good,
}: {
  label: string;
  value: string;
  delta: string;
  good?: boolean;
}) {
  return (
    <div
      style={{
        padding: 14,
        border: "1px solid var(--b-border)",
        borderRadius: 10,
        background: "white",
      }}
    >
      <div
        style={{
          fontFamily: "var(--b-mono)",
          fontSize: 10,
          color: "var(--b-muted)",
          letterSpacing: "0.1em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 500,
          letterSpacing: "-0.02em",
          marginTop: 3,
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontFamily: "var(--b-mono)",
          fontSize: 11,
          color: good ? "oklch(40% 0.14 145)" : "var(--b-muted)",
          marginTop: 2,
        }}
      >
        {delta}
      </div>
    </div>
  );
}

function VariantRow({ v, i }: { v: (typeof VARIANTS)[number]; i: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "40px 1.6fr 1fr 1fr 90px 70px",
        padding: "12px 14px",
        alignItems: "center",
        borderBottom:
          i < VARIANTS.length - 1 ? "1px solid var(--b-border-soft)" : "none",
        fontSize: 13,
        background:
          v.sig === "win" && i === 0 ? "oklch(98% 0.02 145 / 0.5)" : "white",
      }}
    >
      <span
        style={{
          fontFamily: "var(--b-mono)",
          fontSize: 11,
          color: "var(--b-muted)",
        }}
      >
        #{i + 1}
      </span>
      <div>
        <div
          style={{
            fontFamily: "var(--b-mono)",
            fontSize: 11.5,
            fontWeight: 500,
          }}
        >
          {v.name}
        </div>
        <div style={{ display: "flex", gap: 3, marginTop: 4, flexWrap: "wrap" }}>
          {v.genome.map((g) => (
            <span
              key={g}
              style={{
                fontSize: 10.5,
                padding: "1.5px 6px",
                background: "var(--b-paper-2)",
                borderRadius: 4,
                fontFamily: "var(--b-mono)",
                color: "var(--b-ink-2)",
                border: "1px solid var(--b-border-soft)",
                maxWidth: 130,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {g}
            </span>
          ))}
        </div>
      </div>
      <div
        style={{
          fontFamily: "var(--b-mono)",
          fontSize: 13,
          fontWeight: 500,
        }}
      >
        {v.roas}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ZBar z={v.z} sig={v.sig} />
        <span
          style={{
            fontFamily: "var(--b-mono)",
            fontSize: 11.5,
            color:
              v.sig === "win"
                ? "oklch(40% 0.14 145)"
                : v.sig === "lose"
                  ? "oklch(45% 0.16 28)"
                  : "var(--b-muted)",
          }}
        >
          {v.z}
        </span>
      </div>
      <div>
        {v.sig === "win" && (
          <span className="b-chip b-chip-win" style={{ fontSize: 10 }}>
            WINNING
          </span>
        )}
        {v.sig === "lose" && (
          <span className="b-chip b-chip-lose" style={{ fontSize: 10 }}>
            PAUSED
          </span>
        )}
        {v.sig === "flat" && (
          <span className="b-chip b-mono" style={{ fontSize: 10 }}>
            FLAT
          </span>
        )}
      </div>
      <div
        style={{
          textAlign: "right",
          fontFamily: "var(--b-mono)",
          fontSize: 12,
        }}
      >
        {v.pct}%
      </div>
    </div>
  );
}

function ZBar({ z, sig }: { z: string; sig: "win" | "lose" | "flat" }) {
  const val = parseFloat(z);
  const mag = Math.min(Math.abs(val) / 4, 1);
  const color =
    sig === "win"
      ? "oklch(58% 0.14 145)"
      : sig === "lose"
        ? "oklch(60% 0.16 28)"
        : "oklch(75% 0.01 70)";
  return (
    <div
      style={{
        width: 60,
        height: 6,
        background: "var(--b-paper-3)",
        borderRadius: 99,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: 0,
          bottom: 0,
          width: 1,
          background: "var(--b-border)",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: val > 0 ? "50%" : `${50 - 50 * mag}%`,
          width: `${50 * mag}%`,
          background: color,
          borderRadius: 99,
        }}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Trust strip                                                       */
/* ---------------------------------------------------------------- */

function TrustStrip() {
  const items = [
    { t: "Meta Marketing API", s: "OAuth · read + write" },
    { t: "scipy", s: "z-tests, not LLMs" },
    { t: "Claude", s: "variant generation" },
    { t: "PostgreSQL · TSDB", s: "time-series metrics" },
    { t: "Fernet", s: "encrypted tokens" },
  ];
  return (
    <section
      style={{
        padding: "40px 0",
        borderTop: "1px solid var(--b-border)",
        borderBottom: "1px solid var(--b-border)",
        background: "var(--b-paper-2)",
      }}
    >
      <div
        className="b-wrap"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 30,
        }}
      >
        <div className="b-eyebrow" style={{ flexShrink: 0 }}>
          THE STACK UNDERNEATH
        </div>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 28,
            alignItems: "center",
          }}
        >
          {items.map((it) => (
            <div key={it.t} style={{ fontSize: 13.5 }}>
              <div style={{ fontWeight: 500 }}>{it.t}</div>
              <div
                className="b-mono"
                style={{ fontSize: 10.5, color: "var(--b-muted)" }}
              >
                {it.s}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Problem section                                                   */
/* ---------------------------------------------------------------- */

function ProblemSection() {
  const items = [
    {
      t: "You run 3 ads. Which one is actually winning?",
      d: "Not which one has more sales — which one is winning by a margin the data can defend. Gut calls waste budget.",
    },
    {
      t: "You find a winner. Now what?",
      d: "You need new variants that build on it — but most new creative is random, unattributable, and disconnected from what worked.",
    },
    {
      t: "You blink. The winner is fatigued.",
      d: "Performance decays. By the time you notice, you've burned two weeks of spend on a variant that stopped working last Tuesday.",
    },
  ];
  return (
    <section id="problem" style={{ padding: "120px 0 80px" }}>
      <div className="b-wrap">
        <div className="b-eyebrow">THE PROBLEM</div>
        <h2
          className="b-h-section"
          style={{ maxWidth: 880, marginTop: 12, textWrap: "balance" }}
        >
          Great ads aren&apos;t found by staring at dashboards.{" "}
          <span className="b-serif" style={{ color: "var(--b-muted)" }}>
            They&apos;re found by testing every night for months.
          </span>
        </h2>
        <div
          data-b-grid
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 28,
            marginTop: 56,
          }}
        >
          {items.map((it, i) => (
            <div key={it.t}>
              <div
                style={{
                  fontFamily: "var(--b-mono)",
                  fontSize: 11,
                  color: "var(--b-muted)",
                }}
              >
                0{i + 1}
              </div>
              <h3
                style={{
                  fontSize: 19,
                  fontWeight: 500,
                  letterSpacing: "-0.015em",
                  marginTop: 10,
                  lineHeight: 1.3,
                }}
              >
                {it.t}
              </h3>
              <p
                style={{
                  fontSize: 14.5,
                  color: "var(--b-muted)",
                  lineHeight: 1.6,
                  marginTop: 10,
                }}
              >
                {it.d}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Feature reel                                                      */
/* ---------------------------------------------------------------- */

function FeatureReel() {
  const features = [
    {
      eyebrow: "THE DAILY CYCLE",
      title: (
        <>
          Six steps, <span className="b-serif">every night at 6 AM</span>
        </>
      ),
      body: (
        <>
          Poll → Analyze → Act → Generate → Deploy → Report. No buttons to
          push, no dashboards to babysit. By the time you&apos;re drinking
          coffee, decisions are made and variants are live.
        </>
      ),
      mock: <CycleDiagramMock />,
      side: "right" as const,
    },
    {
      eyebrow: "THE GENE POOL",
      title: (
        <>
          Every ad decomposes into{" "}
          <span className="b-serif">headline, body, image, CTA</span>
        </>
      ),
      body: (
        <>
          Kleiber tracks how each element performs across every variant that
          uses it. So when your CTR drops, you don&apos;t just know the ad is
          underperforming — you know your headline is the problem, and which
          one would do better.
        </>
      ),
      mock: <GenePoolMock />,
      side: "left" as const,
    },
    {
      eyebrow: "THE DAILY REPORT",
      title: (
        <>
          A morning email that actually{" "}
          <span className="b-serif">explains what happened</span>
        </>
      ),
      body: (
        <>
          Written in plain English. What moved, why it moved, and what Kleiber
          proposes next. One-click approve for anything destructive or
          high-spend.
        </>
      ),
      mock: <EmailReportMock />,
      side: "right" as const,
    },
  ];
  return (
    <section id="how-it-works" style={{ padding: "80px 0" }}>
      <div className="b-wrap">
        {features.map((f, i) => (
          <div
            key={i}
            data-b-grid
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1.3fr",
              gap: 64,
              alignItems: "center",
              marginBottom: 140,
              direction: f.side === "left" ? "rtl" : "ltr",
            }}
          >
            <div style={{ direction: "ltr" }}>
              <div className="b-eyebrow">{f.eyebrow}</div>
              <h2
                className="b-h-section"
                style={{ marginTop: 12, textWrap: "balance" }}
              >
                {f.title}
              </h2>
              <p
                style={{
                  fontSize: 17,
                  color: "var(--b-muted)",
                  lineHeight: 1.6,
                  marginTop: 16,
                  textWrap: "pretty",
                  maxWidth: 460,
                }}
              >
                {f.body}
              </p>
            </div>
            <div style={{ direction: "ltr" }}>{f.mock}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CycleDiagramMock() {
  const steps = [
    { k: "poll", t: "Poll", d: "Meta API → yesterday" },
    { k: "analyze", t: "Analyze", d: "2-proportion z-test" },
    { k: "act", t: "Act", d: "Pause + scale (Thompson)" },
    { k: "generate", t: "Generate", d: "Claude → 1–3 variants" },
    { k: "deploy", t: "Deploy", d: "Push to Ads Manager" },
    { k: "report", t: "Report", d: "Daily email digest" },
  ];
  return (
    <AppWindow title="daily cycle · 06:00 CT">
      <div style={{ padding: 28 }}>
        <div
          style={{
            fontFamily: "var(--b-mono)",
            fontSize: 10.5,
            color: "var(--b-muted)",
            letterSpacing: "0.1em",
          }}
        >
          CRON · EVERY DAY · 06:00 CT
        </div>
        <div
          style={{
            fontSize: 20,
            fontWeight: 500,
            letterSpacing: "-0.02em",
            marginTop: 4,
            marginBottom: 18,
          }}
        >
          Six steps, fully automated
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {steps.map((s, i) => (
            <div
              key={s.k}
              style={{
                display: "grid",
                gridTemplateColumns: "28px 1fr auto",
                alignItems: "center",
                gap: 14,
                padding: "10px 14px",
                background: "var(--b-paper-2)",
                borderRadius: 10,
                border: "1px solid var(--b-border-soft)",
              }}
            >
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 99,
                  background: "white",
                  border: "1px solid var(--b-border)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "var(--b-mono)",
                  fontSize: 11,
                  fontWeight: 500,
                }}
              >
                {i + 1}
              </div>
              <div>
                <div style={{ fontWeight: 500, fontSize: 14 }}>{s.t}</div>
                <div style={{ fontSize: 12, color: "var(--b-muted)" }}>
                  {s.d}
                </div>
              </div>
              <span
                className="b-chip b-chip-win b-chip-dot"
                style={{ fontSize: 9.5 }}
              >
                DONE · {String(i * 3 + 2).padStart(2, "0")}s
              </span>
            </div>
          ))}
        </div>
      </div>
    </AppWindow>
  );
}

function GenePoolMock() {
  const headlines = [
    { t: "AI-Powered Ad Care", l: "+41%", positive: true },
    { t: "Stop wasting ad spend", l: "+28%", positive: true },
    { t: "Meta ads, on autopilot", l: "−4%", positive: false },
    { t: "Always-on optimization", l: "+12%", positive: true },
    { t: "Test ads while you sleep", l: "−18%", positive: false },
  ];
  return (
    <AppWindow title="gene pool · summer-sale">
      <div style={{ padding: 24 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 18,
          }}
        >
          <div>
            <div className="b-eyebrow">GENE POOL · HUMAN-APPROVED</div>
            <div style={{ fontSize: 18, fontWeight: 500, marginTop: 2 }}>
              34 elements · 7 slots
            </div>
          </div>
        </div>
        <div
          style={{
            border: "1px solid var(--b-border)",
            borderRadius: 10,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "8px 12px",
              background: "var(--b-paper-2)",
              fontFamily: "var(--b-mono)",
              fontSize: 10.5,
              letterSpacing: "0.1em",
              color: "var(--b-muted)",
              borderBottom: "1px solid var(--b-border)",
            }}
          >
            <span>HEADLINES</span>
            <span>5</span>
          </div>
          {headlines.map((h) => (
            <div
              key={h.t}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "10px 14px",
                borderBottom: "1px solid var(--b-border-soft)",
                fontSize: 13,
              }}
            >
              <span>{h.t}</span>
              <span
                style={{
                  fontFamily: "var(--b-mono)",
                  fontSize: 11.5,
                  color: h.positive
                    ? "oklch(40% 0.14 145)"
                    : "oklch(48% 0.16 28)",
                  fontWeight: 500,
                }}
              >
                {h.l}
              </span>
            </div>
          ))}
        </div>
      </div>
    </AppWindow>
  );
}

function EmailReportMock() {
  return (
    <AppWindow title="mail.kleiber.ai">
      <div style={{ padding: 28, background: "white" }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontFamily: "var(--b-mono)",
            fontSize: 11,
            color: "var(--b-muted)",
            marginBottom: 4,
          }}
        >
          <span>From: kleiber &lt;reports@kleiber.ai&gt;</span>
          <span>Apr 18 · 06:14</span>
        </div>
        <h3
          style={{
            fontSize: 22,
            fontWeight: 500,
            letterSpacing: "-0.02em",
            margin: "8px 0 18px",
          }}
        >
          Your daily cycle:{" "}
          <span className="b-serif">3 wins, 2 pauses, 2 new variants</span>
        </h3>
        <div
          style={{ height: 1, background: "var(--b-border)", marginBottom: 20 }}
        />
        <div
          style={{ fontSize: 14, lineHeight: 1.6, color: "var(--b-ink-2)" }}
        >
          <p style={{ margin: 0 }}>
            Good morning. Overnight, summer-sale added <b>$28 in spend</b> and
            pulled a 3.42× ROAS — up from 2.81× last week.
          </p>
          <p>
            V-0041 (&quot;AI-Powered Ad Care&quot; × IMG_673) is now
            significantly winning (
            <span className="b-mono">z=+3.42</span>, p&lt;0.001) and scaled to
            38% of daily budget.
          </p>
          <div
            style={{
              background: "var(--b-paper-2)",
              borderRadius: 10,
              padding: 14,
              marginTop: 16,
            }}
          >
            <div className="b-eyebrow" style={{ marginBottom: 8 }}>
              Proposed new variants · awaiting approval
            </div>
            <div
              style={{ display: "flex", flexDirection: "column", gap: 6 }}
            >
              <span
                className="b-chip b-mono"
                style={{ fontSize: 11, alignSelf: "flex-start" }}
              >
                V-0042 · headline swap → &quot;Stop wasting ad spend&quot;
              </span>
              <span
                className="b-chip b-mono"
                style={{ fontSize: 11, alignSelf: "flex-start" }}
              >
                V-0043 · image swap → IMG_714
              </span>
            </div>
          </div>
        </div>
      </div>
    </AppWindow>
  );
}

/* ---------------------------------------------------------------- */
/* Stats language (dark section)                                     */
/* ---------------------------------------------------------------- */

function StatsLanguageSection() {
  return (
    <section
      id="stats"
      style={{
        background: "var(--b-ink)",
        color: "var(--b-paper)",
        padding: "100px 0",
        margin: "40px 0",
      }}
    >
      <div className="b-wrap">
        <div
          data-b-grid
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 80,
            alignItems: "center",
          }}
        >
          <div>
            <div className="b-eyebrow" style={{ color: "oklch(65% 0.01 70)" }}>
              NO LLM DOES MATH HERE
            </div>
            <h2
              className="b-h-section"
              style={{ marginTop: 12, textWrap: "balance" }}
            >
              Statistics decide.{" "}
              <span
                className="b-serif"
                style={{ color: "oklch(75% 0.1 55)" }}
              >
                Claude just writes the email.
              </span>
            </h2>
            <p
              style={{
                fontSize: 17,
                color: "oklch(75% 0.01 70)",
                lineHeight: 1.6,
                marginTop: 18,
                maxWidth: 460,
              }}
            >
              Every action Kleiber takes is gated by a two-proportion z-test
              against your campaign baseline, with a minimum sample size of
              1,000 impressions. The LLM only does two things: propose new
              variants from your approved gene pool, and write the narrative
              summary. It never touches the math.
            </p>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                marginTop: 24,
              }}
            >
              {["z-test", "Thompson sampling", "fatigue detection", "min-N gate"].map(
                (t) => (
                  <span
                    key={t}
                    className="b-chip"
                    style={{
                      background: "oklch(25% 0.02 60)",
                      border: "1px solid oklch(32% 0.02 60)",
                      color: "oklch(85% 0.01 70)",
                    }}
                  >
                    {t}
                  </span>
                ),
              )}
            </div>
          </div>
          <div
            style={{
              background: "oklch(17% 0.02 60)",
              borderRadius: 14,
              padding: 28,
              fontFamily: "var(--b-mono)",
              fontSize: 12.5,
              lineHeight: 1.75,
              color: "oklch(80% 0.01 70)",
              border: "1px solid oklch(26% 0.02 60)",
            }}
          >
            <div style={{ color: "oklch(55% 0.01 70)" }}>
              # campaigns/summer-sale/cycle.py
            </div>
            <div>
              <span style={{ color: "oklch(70% 0.08 55)" }}>def</span>{" "}
              <span style={{ color: "white" }}>analyze</span>(variant,
              baseline):
            </div>
            <div style={{ paddingLeft: 16 }}>
              p1, n1 = variant.ctr, variant.impressions
              <br />
              p0, n0 = baseline.ctr, baseline.impressions
              <br />
              <span style={{ color: "oklch(55% 0.01 70)" }}>
                # scipy — not an LLM
              </span>
              <br />
              z, p_val ={" "}
              <span style={{ color: "oklch(80% 0.1 140)" }}>
                stats.proportions_ztest
              </span>
              (
              <br />
              <span style={{ paddingLeft: 16 }}>
                [p1*n1, p0*n0], [n1, n0]
              </span>
              <br />)
              <br />
              <span style={{ color: "oklch(70% 0.08 55)" }}>if</span> p_val
              &lt; <span style={{ color: "oklch(80% 0.14 55)" }}>0.05</span>{" "}
              <span style={{ color: "oklch(70% 0.08 55)" }}>and</span> n1 &gt;{" "}
              <span style={{ color: "oklch(80% 0.14 55)" }}>1000</span>:
              <br />
              <span style={{ paddingLeft: 16, color: "oklch(80% 0.1 140)" }}>
                scale_variant
              </span>
              (variant, z)
              <br />
              <span style={{ color: "oklch(70% 0.08 55)" }}>else</span>:
              <br />
              <span style={{ paddingLeft: 16, color: "oklch(55% 0.01 70)" }}>
                # not enough signal — hold
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Weekly preview                                                    */
/* ---------------------------------------------------------------- */

function HowItWorksPreview() {
  const rows = [
    { day: "Mon", action: "3 variants active. One pulling a +1.8 z-score on CTR.", delta: "$128 spent" },
    { day: "Tue", action: "Kleiber proposes V-0012 (body swap). Auto-approved under your rules.", delta: "+1 variant" },
    { day: "Wed", action: "V-0011 crosses significance. Scaled from 20% → 35% of budget.", delta: "ROAS 2.8× → 3.4×", good: true },
    { day: "Thu", action: "V-0007 fatigue detected (declining CTR across 4 days). Paused.", delta: "−$14/day savings", good: true },
    { day: "Fri", action: "Element attribution updated: 'IMG_673' carries +14% lift across all uses.", delta: "new insight" },
    { day: "Sat", action: "2 new variants generated, both inherit IMG_673.", delta: "+2 variants" },
    { day: "Sun", action: "Weekly report: leaderboard, element rankings, pairwise interactions.", delta: "1 email" },
  ];
  return (
    <section style={{ padding: "100px 0" }}>
      <div className="b-wrap" style={{ textAlign: "center" }}>
        <div className="b-eyebrow">A TYPICAL WEEK</div>
        <h2
          className="b-h-section"
          style={{
            marginTop: 12,
            maxWidth: 760,
            marginLeft: "auto",
            marginRight: "auto",
          }}
        >
          The winning combinations{" "}
          <span className="b-serif">compound.</span>
        </h2>
      </div>
      <div className="b-wrap" style={{ marginTop: 56 }}>
        <div
          style={{
            border: "1px solid var(--b-border)",
            borderRadius: 16,
            overflow: "hidden",
          }}
        >
          {rows.map((r, i) => (
            <div
              key={r.day}
              style={{
                display: "grid",
                gridTemplateColumns: "90px 1fr 200px",
                alignItems: "center",
                padding: "18px 24px",
                borderBottom:
                  i < rows.length - 1
                    ? "1px solid var(--b-border-soft)"
                    : "none",
                background: "white",
              }}
            >
              <div
                className="b-mono"
                style={{
                  fontSize: 12,
                  color: "var(--b-muted)",
                  letterSpacing: "0.08em",
                }}
              >
                {r.day.toUpperCase()}
              </div>
              <div style={{ fontSize: 15 }}>{r.action}</div>
              <div
                className="b-mono"
                style={{
                  fontSize: 12,
                  textAlign: "right",
                  color: r.good ? "oklch(40% 0.14 145)" : "var(--b-muted)",
                }}
              >
                {r.delta}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Safety grid                                                       */
/* ---------------------------------------------------------------- */

function SafetySection() {
  const items = [
    { t: "Daily budget cap", d: "Per-campaign + per-variant. Kleiber physically cannot spend beyond it." },
    { t: "Approval queue", d: "Gate any destructive action — pauses, scale-ups, new launches — on a weekly review." },
    { t: "Gene pool is source of truth", d: "The LLM can only recombine elements you've approved. It never invents copy." },
    { t: "Encrypted at rest", d: "Meta tokens are Fernet-encrypted. Each account lives in its own tenant." },
    { t: "Pausable, always", d: "One click and everything freezes exactly where it is. No cleanup required." },
    { t: "Full audit log", d: "Every action — pause, scale, generate — is recorded with the z-score and sample size that triggered it." },
  ];
  return (
    <section id="safety" style={{ padding: "100px 0" }}>
      <div className="b-wrap">
        <div
          data-b-grid
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 2fr",
            gap: 64,
            alignItems: "start",
          }}
        >
          <div style={{ position: "sticky", top: 100 }}>
            <div className="b-eyebrow">SAFETY & CONTROL</div>
            <h2 className="b-h-section" style={{ marginTop: 12 }}>
              Autonomous, <span className="b-serif">not out of hand.</span>
            </h2>
            <p
              style={{
                fontSize: 16,
                color: "var(--b-muted)",
                lineHeight: 1.6,
                marginTop: 16,
              }}
            >
              We built Kleiber for the person spending $100–$1K/mo on ads, not
              a hedge fund. Every move has a brake.
            </p>
          </div>
          <div
            data-b-grid
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 2,
              background: "var(--b-border)",
              borderRadius: 14,
              overflow: "hidden",
            }}
          >
            {items.map((it) => (
              <div
                key={it.t}
                style={{ background: "white", padding: 24 }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 10,
                  }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 99,
                      background: "var(--b-accent)",
                    }}
                  />
                  <span style={{ fontSize: 15, fontWeight: 500 }}>{it.t}</span>
                </div>
                <p
                  style={{
                    fontSize: 13.5,
                    color: "var(--b-muted)",
                    margin: 0,
                    lineHeight: 1.55,
                  }}
                >
                  {it.d}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Pricing                                                           */
/* ---------------------------------------------------------------- */

function PricingSection() {
  return (
    <section
      id="pricing"
      style={{
        padding: "80px 0",
        background: "var(--b-paper-2)",
        borderTop: "1px solid var(--b-border)",
        borderBottom: "1px solid var(--b-border)",
      }}
    >
      <div
        className="b-wrap"
        style={{ textAlign: "center", marginBottom: 48 }}
      >
        <div className="b-eyebrow">PRICING</div>
        <h2 className="b-h-section" style={{ marginTop: 12 }}>
          Built for the{" "}
          <span className="b-serif">$100–$1K/mo</span> spender.
        </h2>
        <p
          className="b-h-sub"
          style={{
            marginTop: 14,
            maxWidth: 560,
            marginLeft: "auto",
            marginRight: "auto",
          }}
        >
          Free during the private beta. Tiered pricing will be announced at
          public launch — no enterprise-sales call, no &quot;contact us.&quot;
        </p>
      </div>
      <div
        className="b-wrap"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr",
          gap: 18,
          maxWidth: 540,
          margin: "0 auto",
        }}
      >
        <div
          style={{
            background: "var(--b-ink)",
            color: "var(--b-paper)",
            border: "1px solid var(--b-ink)",
            borderRadius: 16,
            padding: 32,
            textAlign: "center",
          }}
        >
          <div
            style={{
              fontSize: 13,
              fontWeight: 500,
              letterSpacing: "-0.01em",
              marginBottom: 18,
            }}
          >
            PRIVATE BETA
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 4,
              justifyContent: "center",
            }}
          >
            <span
              style={{
                fontSize: 48,
                fontWeight: 500,
                letterSpacing: "-0.03em",
              }}
            >
              Free
            </span>
          </div>
          <div
            style={{
              height: 1,
              background: "oklch(30% 0.02 60)",
              margin: "20px 0",
            }}
          />
          <ul
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "flex",
              flexDirection: "column",
              gap: 10,
              textAlign: "left",
            }}
          >
            {[
              "Full daily cycle — all six steps",
              "Up to 5 campaigns per account",
              "Approval queue for every destructive action",
              "Daily + weekly email reports",
              "Element attribution + interaction tracking",
            ].map((p) => (
              <li
                key={p}
                style={{
                  fontSize: 14,
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 99,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: "oklch(30% 0.02 60)",
                    flexShrink: 0,
                  }}
                >
                  <svg width="8" height="8" viewBox="0 0 8 8">
                    <path
                      d="M1.5 4L3.5 6L6.5 2"
                      stroke="oklch(80% 0.1 140)"
                      strokeWidth="1.5"
                      fill="none"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                {p}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Signup section                                                    */
/* ---------------------------------------------------------------- */

function SignupSection() {
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
    <section id="signup" style={{ padding: "120px 0 40px" }}>
      <div className="b-wrap-narrow" style={{ textAlign: "center" }}>
        <div className="b-eyebrow">REQUEST ACCESS</div>
        <h2
          className="b-h-section"
          style={{
            marginTop: 12,
            maxWidth: 720,
            marginLeft: "auto",
            marginRight: "auto",
            textWrap: "balance",
          }}
        >
          Put me on the <span className="b-serif">waitlist.</span>
        </h2>
        <p
          className="b-h-sub"
          style={{
            marginTop: 14,
            maxWidth: 540,
            marginLeft: "auto",
            marginRight: "auto",
          }}
        >
          Private beta — we&apos;re onboarding a handful of advertisers at a
          time so we can shadow every cycle. Drop your email and we&apos;ll
          reach out within a few days.
        </p>

        {status === "success" ? (
          <div
            style={{
              marginTop: 40,
              maxWidth: 420,
              marginLeft: "auto",
              marginRight: "auto",
              padding: 24,
              background: "var(--b-win-soft)",
              borderRadius: 14,
              border: "1px solid var(--b-border-soft)",
            }}
          >
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 99,
                background: "white",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 12px",
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M6 12l4 4 8-9"
                  stroke="oklch(42% 0.14 145)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <h3
              style={{
                fontSize: 19,
                fontWeight: 500,
                letterSpacing: "-0.02em",
                margin: "0 0 6px",
                color: "oklch(32% 0.14 145)",
              }}
            >
              You&apos;re on the list.
            </h3>
            <p
              style={{
                fontSize: 14,
                color: "var(--b-ink-2)",
                margin: 0,
              }}
            >
              We&apos;ll email <b>{email}</b> within a few days.
            </p>
          </div>
        ) : (
          <form
            onSubmit={onSubmit}
            noValidate
            style={{
              marginTop: 32,
              maxWidth: 440,
              marginLeft: "auto",
              marginRight: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <input
              type="email"
              placeholder="you@company.co"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (status === "error") setStatus("idle");
              }}
              className="b-input"
              aria-invalid={status === "error"}
            />
            <button
              type="submit"
              className="b-btn b-btn-primary b-btn-lg"
              disabled={status === "submitting" || !email.includes("@")}
              style={{ width: "100%" }}
            >
              {status === "submitting" ? "Submitting…" : "Request access"}
            </button>
            {status === "error" && (
              <p
                role="alert"
                style={{
                  fontSize: 13,
                  color: "oklch(42% 0.16 28)",
                  margin: 0,
                }}
              >
                {errorMsg}
              </p>
            )}
            <div
              className="b-mono"
              style={{
                fontSize: 11.5,
                color: "var(--b-muted)",
                textAlign: "center",
                marginTop: 4,
              }}
            >
              · no credit card · connects via Meta OAuth ·
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Final CTA                                                         */
/* ---------------------------------------------------------------- */

function FinalCTA() {
  return (
    <section style={{ padding: "80px 0 80px", textAlign: "center" }}>
      <div className="b-wrap-narrow">
        <h2
          style={{
            fontSize: "clamp(48px, 7vw, 96px)",
            fontWeight: 500,
            letterSpacing: "-0.035em",
            lineHeight: 0.98,
            textWrap: "balance",
            margin: 0,
          }}
        >
          Let the <span className="b-serif">math</span> do the digging.
          <br />
          You focus on <span className="b-serif">making</span> the ads.
        </h2>
        <div
          style={{
            display: "flex",
            gap: 10,
            justifyContent: "center",
            marginTop: 36,
            flexWrap: "wrap",
          }}
        >
          <a
            href="#signup"
            className="b-btn b-btn-primary b-btn-lg"
            style={{ textDecoration: "none" }}
          >
            Request access
          </a>
          <a
            href="#how-it-works"
            className="b-btn b-btn-ghost b-btn-lg"
            style={{ textDecoration: "none" }}
          >
            How it works
          </a>
        </div>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- */
/* Footer                                                            */
/* ---------------------------------------------------------------- */

function Footer() {
  return (
    <footer
      style={{
        borderTop: "1px solid var(--b-border)",
        marginTop: 120,
        paddingTop: 56,
        paddingBottom: 48,
        background: "var(--b-paper-2)",
      }}
    >
      <div
        className="b-wrap"
        data-b-grid
        style={{
          display: "grid",
          gridTemplateColumns: "1.4fr 1fr 1fr",
          gap: 48,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <KleiberMark size={22} />
            <span
              style={{
                fontSize: 18,
                letterSpacing: "-0.02em",
                fontWeight: 500,
              }}
            >
              Kleiber
            </span>
          </div>
          <p
            style={{
              marginTop: 16,
              color: "var(--b-muted)",
              fontSize: 14,
              maxWidth: 300,
              lineHeight: 1.55,
            }}
          >
            Autonomous ad-testing for Meta.
            <br />
            Runs the scientific method on your creative, every night.
          </p>
        </div>
        <div>
          <div className="b-eyebrow" style={{ marginBottom: 14 }}>
            Product
          </div>
          <FootLink href="#how-it-works">How it works</FootLink>
          <FootLink href="#safety">Safety</FootLink>
          <FootLink href="#pricing">Pricing</FootLink>
        </div>
        <div>
          <div className="b-eyebrow" style={{ marginBottom: 14 }}>
            Connect
          </div>
          <FootLink href="#signup">Request access</FootLink>
          <FootLink href="mailto:hi@kleiber.ai">hi@kleiber.ai</FootLink>
        </div>
      </div>
      <div
        className="b-wrap"
        style={{
          marginTop: 56,
          paddingTop: 20,
          borderTop: "1px solid var(--b-border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--b-mono)",
          fontSize: 11.5,
          color: "var(--b-muted)",
        }}
      >
        <span>© 2026 Kleiber Labs — All rights reserved</span>
        <span>built in CT</span>
      </div>
    </footer>
  );
}

function FootLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      style={{
        display: "block",
        padding: "5px 0",
        color: "var(--b-ink-2)",
        fontSize: 14,
        transition: "color .15s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.color = "var(--b-accent)")}
      onMouseLeave={(e) => (e.currentTarget.style.color = "var(--b-ink-2)")}
    >
      {children}
    </a>
  );
}
