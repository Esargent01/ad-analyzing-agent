/**
 * Shared dashboard primitives used across every authed screen.
 *
 * Mirrors the design drop at ``kleiber-agent-deign/project/src/dashboard/primitives.jsx``.
 * All styling assumes the component renders inside a ``.kleiber-dash``
 * wrapper (see ``frontend/src/styles/dashboard.css``), which is applied
 * by ``AuthedLayout``.
 *
 * Intentionally colocated in one file so the pieces stay visually
 * consistent and are easy to find when tuning the look-and-feel.
 */

import type { ReactNode } from "react";
import { useState } from "react";

/* ----------------------------------------------------------------
 * StatusPill — one pill for every variant / campaign status value.
 * Five colored variants plus a neutral default. Matches the visual
 * language used in email reports and the public HTML reports.
 * ---------------------------------------------------------------- */

export type StatusKind =
  | "winner"
  | "active"
  | "steady"
  | "new"
  | "fatigue"
  | "paused"
  | "draft"
  | "danger";

const STATUS_STYLES: Record<StatusKind, { bg: string; fg: string }> = {
  winner: { bg: "var(--win-soft)", fg: "oklch(32% 0.14 145)" },
  active: { bg: "var(--win-soft)", fg: "oklch(32% 0.14 145)" },
  steady: { bg: "var(--paper-2)", fg: "var(--ink-2)" },
  new: { bg: "oklch(94% 0.04 250)", fg: "oklch(38% 0.13 250)" },
  fatigue: { bg: "oklch(95% 0.06 75)", fg: "oklch(42% 0.15 65)" },
  paused: { bg: "oklch(95% 0.06 75)", fg: "oklch(42% 0.15 65)" },
  draft: { bg: "var(--paper-2)", fg: "var(--muted)" },
  danger: { bg: "var(--lose-soft)", fg: "oklch(40% 0.16 28)" },
};

export function StatusPill({
  kind,
  children,
}: {
  kind: StatusKind;
  children?: ReactNode;
}) {
  const s = STATUS_STYLES[kind] ?? STATUS_STYLES.steady;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2.5px 9px",
        borderRadius: 99,
        fontFamily: "var(--font-mono)",
        fontSize: 10.5,
        letterSpacing: "0.03em",
        textTransform: "uppercase",
        background: s.bg,
        color: s.fg,
        fontWeight: 500,
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: 99,
          background: "currentColor",
        }}
      />
      {children ?? kind}
    </span>
  );
}

/* ----------------------------------------------------------------
 * MediaBadge — compact pill ("IMG" / "VID" / "MIX") that tags a
 * variant's creative format. Pairs with the media-type-aware report
 * rendering shipped in commit a029fc6.
 * ---------------------------------------------------------------- */

export function MediaBadge({
  type,
}: {
  type: "image" | "video" | "mixed" | "unknown" | string;
}) {
  const label =
    type === "image"
      ? "IMG"
      : type === "video"
        ? "VID"
        : type === "mixed"
          ? "MIX"
          : "?";
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 9.5,
        padding: "2px 6px",
        borderRadius: 4,
        background: "var(--paper-2)",
        border: "1px solid var(--border)",
        color: "var(--muted)",
        letterSpacing: "0.05em",
      }}
    >
      {label}
    </span>
  );
}

/* ----------------------------------------------------------------
 * StatTile — primary KPI card. Big value, optional delta + sub copy,
 * tone (good/bad/flat) colors the delta text.
 * ---------------------------------------------------------------- */

export function StatTile({
  label,
  value,
  delta,
  good,
  bad,
  sub,
}: {
  label: string;
  value: ReactNode;
  delta?: string;
  good?: boolean;
  bad?: boolean;
  sub?: string;
}) {
  const dColor = good
    ? "oklch(40% 0.14 145)"
    : bad
      ? "oklch(48% 0.16 28)"
      : "var(--muted)";
  return (
    <div
      style={{
        padding: 18,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
      }}
    >
      <div className="eyebrow" style={{ fontSize: 10 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 28,
          fontWeight: 500,
          letterSpacing: "-0.025em",
          marginTop: 4,
        }}
      >
        {value}
      </div>
      {delta !== undefined && (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: dColor,
            marginTop: 3,
          }}
        >
          {delta}
        </div>
      )}
      {sub && (
        <div
          style={{
            fontSize: 12,
            color: "var(--muted)",
            marginTop: 3,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------
 * EmptyState — dashed-border card for "no data yet" paths.
 * ---------------------------------------------------------------- */

export function EmptyState({
  title,
  desc,
  action,
  icon,
}: {
  title: string;
  desc: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div
      style={{
        padding: "56px 32px",
        border: "1px dashed var(--border)",
        borderRadius: 14,
        background: "var(--paper-2)",
        textAlign: "center",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          background: "white",
          border: "1px solid var(--border)",
          margin: "0 auto 18px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--muted)",
        }}
      >
        {icon ?? "◌"}
      </div>
      <h3
        style={{
          fontSize: 18,
          fontWeight: 500,
          margin: 0,
          letterSpacing: "-0.015em",
        }}
      >
        {title}
      </h3>
      <p
        style={{
          color: "var(--muted)",
          fontSize: 14,
          margin: "8px auto 20px",
          maxWidth: 420,
          lineHeight: 1.55,
        }}
      >
        {desc}
      </p>
      {action}
    </div>
  );
}

/* ----------------------------------------------------------------
 * DangerZone — two-stage confirmation for destructive actions.
 * Requires the user to type the campaign name exactly before the
 * confirm button enables. Used by the campaign-delete flow.
 * ---------------------------------------------------------------- */

export function DangerZone({
  campaignName,
  onDelete,
  isPending,
  errorMessage,
}: {
  campaignName: string;
  onDelete: () => void | Promise<void>;
  isPending?: boolean;
  errorMessage?: string | null;
}) {
  const [armed, setArmed] = useState(false);
  const [typed, setTyped] = useState("");
  const canDelete = typed === campaignName && !isPending;

  return (
    <div
      style={{
        marginTop: 56,
        padding: 24,
        border: "1px solid oklch(88% 0.08 28)",
        borderRadius: 12,
        background: "oklch(98% 0.02 28)",
      }}
    >
      <div className="eyebrow" style={{ color: "oklch(45% 0.16 28)" }}>
        DANGER ZONE
      </div>
      <h3 style={{ fontSize: 17, fontWeight: 500, margin: "8px 0 6px" }}>
        Delete this campaign
      </h3>
      <p
        style={{
          fontSize: 13.5,
          color: "var(--ink-2)",
          margin: "0 0 16px",
          lineHeight: 1.55,
          maxWidth: 580,
        }}
      >
        Removes Kleiber's records — cycles, variants, gene pool, reports.{" "}
        <b>Your Meta ads stay live.</b> Reconnect by re-importing.
      </p>
      {!armed ? (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setArmed(true)}
          style={{
            borderColor: "oklch(70% 0.1 28)",
            color: "oklch(40% 0.16 28)",
          }}
        >
          Delete campaign…
        </button>
      ) : (
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 13 }}>
            Type{" "}
            <code
              style={{
                fontFamily: "var(--font-mono)",
                background: "white",
                padding: "2px 6px",
                borderRadius: 4,
                border: "1px solid var(--border)",
              }}
            >
              {campaignName}
            </code>{" "}
            to confirm:
          </span>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="input"
            style={{ width: 220 }}
            placeholder={campaignName}
            autoFocus
          />
          <button
            type="button"
            disabled={!canDelete}
            onClick={onDelete}
            className="btn btn-sm btn-danger"
          >
            {isPending ? "Deleting…" : "Permanently delete"}
          </button>
          <button
            type="button"
            onClick={() => {
              setArmed(false);
              setTyped("");
            }}
            className="btn btn-ghost btn-sm"
          >
            Cancel
          </button>
          {errorMessage && (
            <p
              role="alert"
              style={{
                flexBasis: "100%",
                fontSize: 12.5,
                color: "oklch(42% 0.16 28)",
                marginTop: 6,
              }}
            >
              {errorMessage}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------
 * GenomeSlots — pill row representing a variant's genome
 * (headline / body / image / cta). Optional highlight slot.
 * ---------------------------------------------------------------- */

export function GenomeSlots({
  genome,
  highlight,
}: {
  genome: Record<string, string>;
  highlight?: string;
}) {
  const order = ["headline", "body", "image_url", "cta_text"];
  const labelFor = (k: string) =>
    k === "image_url" ? "image" : k === "cta_text" ? "cta" : k;
  const normalize = (k: string, v: string) => {
    // Image URLs are long + ugly in the UI — show "IMG_NNN" style tag
    // if we can pull one out, else the filename.
    if (k === "image_url") {
      const m = v.match(/IMG_[A-Za-z0-9]+/);
      if (m) return m[0];
      const last = v.split("/").pop() ?? v;
      return last.length > 18 ? `${last.slice(0, 16)}…` : last;
    }
    return v.length > 40 ? `${v.slice(0, 38)}…` : v;
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {order
        .filter((k) => genome[k])
        .map((k) => {
          const isHighlight = highlight === k || highlight === labelFor(k);
          return (
            <span
              key={k}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "4px 9px",
                borderRadius: 6,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                background: isHighlight
                  ? "var(--accent-soft)"
                  : "var(--paper-2)",
                border: isHighlight
                  ? "1px solid transparent"
                  : "1px solid var(--border-soft)",
                color: isHighlight ? "var(--accent-ink)" : "var(--ink-2)",
              }}
            >
              <span
                style={{
                  color: isHighlight ? "var(--accent-ink)" : "var(--muted)",
                  fontSize: 9.5,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                {labelFor(k)}
              </span>
              <span>{normalize(k, genome[k])}</span>
            </span>
          );
        })}
    </div>
  );
}

/* ----------------------------------------------------------------
 * FunnelChart — horizontal bar chart of funnel stages with counts +
 * step-over-step conversion rates.
 * ---------------------------------------------------------------- */

export interface FunnelStage {
  step: string;
  n: number;
}

export function FunnelChart({ funnel }: { funnel: FunnelStage[] }) {
  if (funnel.length === 0) return null;
  const max = Math.max(funnel[0].n, 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {funnel.map((f, i) => {
        const pct = (f.n / max) * 100;
        const prev = i > 0 ? funnel[i - 1].n : null;
        const stepRate =
          prev && prev > 0 ? ((f.n / prev) * 100).toFixed(1) : null;
        return (
          <div
            key={`${f.step}-${i}`}
            style={{
              display: "grid",
              gridTemplateColumns: "130px 1fr 70px 56px",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
              {f.step}
            </span>
            <div
              style={{
                height: 20,
                background: "var(--paper-2)",
                borderRadius: 5,
                overflow: "hidden",
                border: "1px solid var(--border-soft)",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: "oklch(85% 0.04 55)",
                  borderRight: "1px solid oklch(70% 0.1 55)",
                }}
              />
            </div>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                textAlign: "right",
              }}
            >
              {f.n.toLocaleString()}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--muted)",
                textAlign: "right",
              }}
            >
              {stepRate ? `${stepRate}%` : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ----------------------------------------------------------------
 * Diagnostic — single row of severity + body text.
 * ---------------------------------------------------------------- */

export function Diagnostic({
  severity,
  text,
}: {
  severity: "good" | "warning" | "bad";
  text: string;
}) {
  const c =
    severity === "good"
      ? { bg: "var(--win-soft)", fg: "oklch(40% 0.14 145)" }
      : severity === "bad"
        ? { bg: "var(--lose-soft)", fg: "oklch(48% 0.16 28)" }
        : { bg: "oklch(95% 0.06 75)", fg: "oklch(42% 0.15 65)" };
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 0",
        borderBottom: "1px solid var(--border-soft)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9.5,
          padding: "2px 7px",
          borderRadius: 4,
          background: c.bg,
          color: c.fg,
          fontWeight: 500,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          marginTop: 1,
        }}
      >
        {severity}
      </span>
      <span style={{ fontSize: 13.5, lineHeight: 1.5 }}>{text}</span>
    </div>
  );
}

/* ----------------------------------------------------------------
 * QuickLink — large navigation card used on campaign overview to
 * send the user to daily / weekly / experiments.
 * ---------------------------------------------------------------- */

export function QuickLink({
  label,
  desc,
  onClick,
  badge,
}: {
  label: string;
  desc: string;
  onClick: () => void;
  badge?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        textAlign: "left",
        padding: 18,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
        cursor: "pointer",
        width: "100%",
        transition: "all 0.15s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--ink)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--border)";
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 500 }}>{label}</span>
        {badge !== undefined && badge > 0 ? (
          <span
            style={{
              background: "var(--accent)",
              color: "white",
              fontSize: 10.5,
              padding: "2px 7px",
              borderRadius: 99,
              fontWeight: 500,
            }}
          >
            {badge}
          </span>
        ) : (
          <span style={{ color: "var(--muted)" }}>→</span>
        )}
      </div>
      <p
        style={{
          fontSize: 12.5,
          color: "var(--muted)",
          margin: "6px 0 0",
          lineHeight: 1.5,
        }}
      >
        {desc}
      </p>
    </button>
  );
}
