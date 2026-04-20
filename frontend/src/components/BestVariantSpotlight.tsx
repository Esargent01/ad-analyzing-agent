import { FunnelChart as LegacyFunnelChart } from "@/components/FunnelChart";
import {
  Diagnostic,
  GenomeSlots,
  MediaBadge,
  StatusPill,
  type StatusKind,
} from "@/components/dashboard/primitives";
import type {
  Diagnostic as DiagnosticType,
  ReportFunnelStage,
  VariantReport,
} from "@/lib/api/types";
import {
  formatCurrency,
  formatIntComma,
  formatOneDecimal,
} from "@/lib/format";

/**
 * "Best variant today" spotlight for daily report detail pages.
 *
 * Ported to match the warm-editorial system — white card, mono
 * numerics, element-chip genome, 3-up diagnostic tiles, split layout
 * with the funnel on the left and notes on the right. Matches the
 * design drop at
 * ``kleiber-agent-deign/project/src/dashboard/screens-a.jsx::DailyDetail``.
 *
 * Diagnostic lines flip between the video-funnel trio
 * (hook / hold / CTR) and the image-funnel trio (CTR / ATC rate /
 * checkout rate) based on ``variant.media_type`` — same behavior as
 * the email and public HTML templates.
 */

interface BestVariantSpotlightProps {
  variant: VariantReport;
  funnel: ReportFunnelStage[];
  diagnostics: DiagnosticType[];
  projection: string | null;
}

const VARIANT_STATUSES = new Set<StatusKind>([
  "winner",
  "active",
  "steady",
  "new",
  "fatigue",
  "paused",
  "draft",
  "danger",
]);

function toStatusKind(status: string): StatusKind {
  const s = status.toLowerCase();
  return VARIANT_STATUSES.has(s as StatusKind) ? (s as StatusKind) : "steady";
}

export function BestVariantSpotlight({
  variant,
  funnel,
  diagnostics,
  projection,
}: BestVariantSpotlightProps) {
  return (
    <>
      <div className="eyebrow" style={{ marginBottom: 12 }}>
        BEST VARIANT TODAY
      </div>
      <div
        style={{
          padding: 24,
          border: "1px solid var(--border)",
          borderRadius: 14,
          background: "white",
          marginBottom: 32,
        }}
      >
        {/* Header row: code · media badge · status + genome summary ·
            right-side CPA + ROAS numbers */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
            flexWrap: "wrap",
            marginBottom: 14,
          }}
        >
          <div>
            <div
              style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 15,
                  fontWeight: 500,
                  color: "var(--ink)",
                }}
              >
                {variant.variant_code}
              </span>
              <MediaBadge type={variant.media_type} />
              <StatusPill kind={toStatusKind(variant.status)}>
                {variant.status}
              </StatusPill>
            </div>
            <div
              style={{
                fontSize: 13,
                color: "var(--muted)",
                marginTop: 6,
                maxWidth: 520,
              }}
            >
              {variant.genome_summary}
            </div>
            {variant.hypothesis && (
              <div
                style={{
                  fontSize: 12.5,
                  color: "var(--muted-2)",
                  marginTop: 4,
                  fontStyle: "italic",
                  maxWidth: 520,
                  lineHeight: 1.5,
                }}
              >
                {variant.hypothesis}
              </div>
            )}
          </div>
          <div
            style={{
              display: "flex",
              gap: 24,
              alignItems: "flex-start",
              flexShrink: 0,
            }}
          >
            <SummaryNumber
              label="CPA"
              value={
                variant.cost_per_purchase != null &&
                variant.cost_per_purchase !== ""
                  ? formatCurrency(variant.cost_per_purchase)
                  : "—"
              }
            />
            <SummaryNumber
              label="ROAS"
              value={
                variant.roas != null && variant.roas !== ""
                  ? `${formatOneDecimal(variant.roas)}x`
                  : "N/A"
              }
              tone="good"
            />
            <SummaryNumber
              label="Purchases"
              value={formatIntComma(variant.purchases)}
            />
          </div>
        </div>

        {/* Three-up diagnostic tile row — media-type aware */}
        <div
          data-ds-grid
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 10,
            marginBottom: 20,
          }}
        >
          {variant.media_type === "image" ? (
            <>
              <DiagnosticTile
                label="CTR"
                value={
                  variant.ctr_pct != null
                    ? `${variant.ctr_pct.toFixed(1)}%`
                    : "N/A"
                }
                benchmark="benchmark 1.5%"
              />
              <DiagnosticTile
                label="ATC rate"
                value={
                  variant.atc_rate_pct != null
                    ? `${variant.atc_rate_pct.toFixed(1)}%`
                    : "N/A"
                }
                benchmark="benchmark 5–10%"
              />
              <DiagnosticTile
                label="Checkout rate"
                value={
                  variant.checkout_rate_pct != null
                    ? `${variant.checkout_rate_pct.toFixed(1)}%`
                    : "N/A"
                }
                benchmark="benchmark 30%"
              />
            </>
          ) : (
            <>
              <DiagnosticTile
                label="Hook rate"
                value={
                  variant.hook_rate_pct != null
                    ? `${variant.hook_rate_pct.toFixed(1)}%`
                    : "N/A"
                }
                benchmark="benchmark 30%"
              />
              <DiagnosticTile
                label="Hold rate"
                value={
                  variant.hold_rate_pct != null
                    ? `${variant.hold_rate_pct.toFixed(1)}%`
                    : "N/A"
                }
                benchmark="benchmark 25%"
              />
              <DiagnosticTile
                label="CTR"
                value={
                  variant.ctr_pct != null
                    ? `${variant.ctr_pct.toFixed(1)}%`
                    : "N/A"
                }
                benchmark="benchmark 1.5%"
              />
            </>
          )}
        </div>

        {/* Two-column split: funnel | notes + projection */}
        <div
          data-ds-grid
          style={{
            display: "grid",
            gridTemplateColumns: "1.5fr 1fr",
            gap: 28,
          }}
        >
          <div>
            <div className="eyebrow" style={{ marginBottom: 10 }}>
              FUNNEL
            </div>
            {funnel.length > 0 ? (
              <LegacyFunnelChart variant="daily" stages={funnel} />
            ) : (
              <p
                style={{
                  fontSize: 12,
                  color: "var(--muted)",
                  margin: 0,
                }}
              >
                Not enough data to render the funnel yet.
              </p>
            )}
          </div>
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              NOTES
            </div>
            {diagnostics.length > 0 ? (
              diagnostics.map((d, i) => (
                <Diagnostic
                  key={i}
                  severity={
                    d.severity === "good" || d.severity === "bad"
                      ? (d.severity as "good" | "bad")
                      : "warning"
                  }
                  text={d.text}
                />
              ))
            ) : (
              <p
                style={{
                  fontSize: 12.5,
                  color: "var(--muted)",
                  margin: "10px 0",
                }}
              >
                No diagnostic flags today.
              </p>
            )}
            {projection && (
              <div
                style={{
                  marginTop: 14,
                  padding: 14,
                  background: "var(--paper-2)",
                  borderRadius: 10,
                  fontSize: 13,
                  color: "var(--ink-2)",
                  lineHeight: 1.5,
                }}
              >
                <b style={{ color: "var(--ink)", fontWeight: 500 }}>
                  Projection.
                </b>{" "}
                {projection}
              </div>
            )}
          </div>
        </div>

        {/* Genome pills */}
        <div style={{ marginTop: 22 }}>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            GENOME
          </div>
          <GenomeSlots genome={variant.genome} />
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- */
/* Local helpers                                                    */
/* ---------------------------------------------------------------- */

function SummaryNumber({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good";
}) {
  return (
    <div style={{ textAlign: "right" }}>
      <div
        className="eyebrow"
        style={{ fontSize: 9.5 }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 18,
          fontWeight: 500,
          color: tone === "good" ? "oklch(40% 0.14 145)" : "var(--ink)",
          marginTop: 2,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function DiagnosticTile({
  label,
  value,
  benchmark,
}: {
  label: string;
  value: string;
  benchmark?: string | null;
}) {
  return (
    <div
      style={{
        padding: 12,
        background: "var(--paper-2)",
        borderRadius: 10,
      }}
    >
      <div className="eyebrow" style={{ fontSize: 9.5 }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 20,
          fontWeight: 500,
          marginTop: 3,
          color: "var(--ink)",
        }}
      >
        {value}
      </div>
      {benchmark && (
        <div
          style={{
            fontSize: 10.5,
            color: "var(--muted)",
            marginTop: 3,
          }}
        >
          {benchmark}
        </div>
      )}
    </div>
  );
}
