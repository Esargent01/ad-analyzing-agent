import { Navigate, useParams } from "react-router-dom";

import { FunnelChart } from "@/components/FunnelChart";
import { ElementRanking } from "@/components/ElementRanking";
import { InteractionList } from "@/components/InteractionList";
import { MetricCard } from "@/components/MetricCard";
import { WeeklyVariantTable } from "@/components/VariantTable";
import { DashPage } from "@/components/dashboard/DashPage";
import {
  EmptyState,
  MediaBadge,
  StatusPill,
} from "@/components/dashboard/primitives";
import { SkeletonReportBody } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api/client";
import { useMe, useWeeklyReport } from "@/lib/api/hooks";
import type { ProposedVariant, WeeklyReport } from "@/lib/api/types";
import {
  formatCurrency,
  formatDateLabel,
  formatIntComma,
  formatOneDecimal,
  formatPct,
} from "@/lib/format";

/**
 * Weekly report detail page. Mirrors `weekly_web.html` section-by-section:
 * header, 3 rows of metric cards, full funnel, next week's experiments,
 * variant leaderboard, element rankings, interactions, and budget summary.
 *
 * Ported to the warm-editorial system: eyebrow section labels, warm-paper
 * card containers, and the shared ``StatusPill`` / ``MediaBadge``
 * primitives replace the legacy tailwind class soup.
 */
export function WeeklyReportDetailRoute() {
  const { campaignId = "", weekStart = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const report = useWeeklyReport(campaignId, weekStart);

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  const crumb = [
    { label: "Dashboard", href: "/dashboard" },
    {
      label: campaign?.name ?? "Campaign",
      href: `/campaigns/${campaignId}`,
    },
    {
      label: "Weekly",
      href: `/campaigns/${campaignId}/reports/weekly`,
    },
    { label: weekStart },
  ];

  if (
    report.isError &&
    report.error instanceof ApiError &&
    report.error.status === 404
  ) {
    return (
      <DashPage
        crumb={crumb}
        title={<>weekly · <span className="serif">{weekStart}</span></>}
      >
        <EmptyState
          title={`No weekly report for ${formatDateLabel(weekStart)}`}
          desc="The week may not have any completed cycles, or the date is outside your campaign window. Pick another week from the index."
          icon="?"
        />
      </DashPage>
    );
  }

  const rangeLabel = report.data
    ? `${formatDateLabel(report.data.week_start)} – ${formatDateLabel(report.data.week_end)}`
    : formatDateLabel(weekStart);

  const sub = report.data ? (
    <>
      {report.data.campaign_name ?? campaign?.name} ·{" "}
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        {report.data.cycles_run} cycles · {report.data.variants_launched} launched
        · {report.data.variants_retired} retired
      </span>
    </>
  ) : null;

  return (
    <DashPage
      crumb={crumb}
      title={<>weekly · <span className="serif">{rangeLabel}</span></>}
      sub={sub}
    >
      {report.isLoading && !report.data ? <SkeletonReportBody /> : null}

      {report.data ? <WeeklyReportBody report={report.data} /> : null}
    </DashPage>
  );
}

function WeeklyReportBody({ report }: { report: WeeklyReport }) {
  return (
    <>
      {/* Row 1 — Purchase metrics */}
      <Section label="Purchase metrics">
        <MetricGrid>
          <MetricCard label="Spend" value={formatCurrency(report.total_spend)} />
          <MetricCard
            label="Purchases"
            value={formatIntComma(report.total_purchases)}
          />
          <MetricCard
            label="CPA"
            value={
              report.avg_cost_per_purchase != null &&
              report.avg_cost_per_purchase !== ""
                ? formatCurrency(report.avg_cost_per_purchase)
                : "N/A"
            }
          />
          <MetricCard
            label="ROAS"
            value={
              report.avg_roas != null && report.avg_roas !== ""
                ? `${formatOneDecimal(report.avg_roas)}x`
                : "N/A"
            }
          />
        </MetricGrid>
      </Section>

      {/* Row 2 — Engagement metrics. Image-only campaigns swap Hook/Hold
          for Frequency/ATC rate; the video-specific tiles would read 0%
          on static creatives. */}
      <Section label="Engagement metrics">
        <MetricGrid>
          {report.best_variant?.media_type === "image" ? (
            <>
              <MetricCard
                label="Frequency"
                value={`${formatOneDecimal(report.avg_frequency)}x`}
              />
              <MetricCard
                label="ATC rate"
                value={
                  report.total_link_clicks > 0
                    ? formatPct(
                        Number(report.total_add_to_carts) /
                          Number(report.total_link_clicks),
                      )
                    : "N/A"
                }
              />
            </>
          ) : (
            <>
              <MetricCard label="Hook rate" value={formatPct(report.avg_hook_rate)} />
              <MetricCard label="Hold rate" value={formatPct(report.avg_hold_rate)} />
            </>
          )}
          <MetricCard label="CTR" value={formatPct(report.avg_ctr)} />
          <MetricCard label="CPM" value={formatCurrency(report.avg_cpm)} />
        </MetricGrid>
      </Section>

      {/* Row 3 — Volume metrics */}
      <Section label="Volume metrics">
        <MetricGrid>
          <MetricCard
            label="Impressions"
            value={formatIntComma(report.total_impressions)}
          />
          <MetricCard label="Reach" value={formatIntComma(report.total_reach)} />
          <MetricCard
            label="Revenue"
            value={formatCurrency(report.total_purchase_value)}
          />
          <MetricCard
            label="Frequency"
            value={formatOneDecimal(report.avg_frequency)}
          />
        </MetricGrid>
      </Section>

      {/* Full funnel breakdown */}
      {report.funnel_stages.length > 0 ? (
        <Section label="Full funnel breakdown">
          <FunnelChart variant="weekly" stages={report.funnel_stages} />
        </Section>
      ) : null}

      {/* Next week's experiments */}
      {report.proposed_variants.length > 0 ||
      report.generation_paused ||
      report.expired_count > 0 ? (
        <NextWeekExperiments report={report} />
      ) : null}

      {/* Variant leaderboard */}
      {report.all_variants.length > 0 ? (
        <Section label="Variant leaderboard">
          <WeeklyVariantTable variants={report.all_variants} />
        </Section>
      ) : null}

      {/* Element performance */}
      {report.top_elements.length > 0 ? (
        <Section label="Element performance">
          <ElementRanking elements={report.top_elements} />
        </Section>
      ) : null}

      {/* Top element interactions */}
      {report.top_interactions.length > 0 ? (
        <Section label="Top element interactions">
          <InteractionList interactions={report.top_interactions} />
        </Section>
      ) : null}

      {/* Budget & efficiency summary */}
      <BudgetSummary report={report} />
    </>
  );
}

function NextWeekExperiments({ report }: { report: WeeklyReport }) {
  const count = report.proposed_variants.length;
  return (
    <Section
      label={
        count > 0 ? `Next week's experiments · ${count} proposed` : "Next week's experiments"
      }
    >
      {report.expired_count > 0 ? (
        <p
          style={{
            margin: "0 0 8px",
            fontSize: 12.5,
            color: "var(--muted)",
          }}
        >
          {report.expired_count} older proposal
          {report.expired_count === 1 ? "" : "s"} expired without review and were
          auto-rejected.
        </p>
      ) : null}

      {report.generation_paused ? (
        <div
          style={{
            marginBottom: 10,
            padding: "10px 14px",
            borderRadius: 10,
            border: "1px solid oklch(88% 0.08 70)",
            background: "oklch(97% 0.03 70)",
            fontSize: 12.5,
            color: "oklch(40% 0.14 70)",
          }}
        >
          {report.proposed_variants.length > 0
            ? "⚠ New variant generation paused — clear the review queue to resume."
            : "⚠ New variant generation paused — your active variants are at capacity. Retire a variant to make room for new experiments."}
        </div>
      ) : null}

      {count > 0 ? (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 12,
            background: "white",
            overflow: "hidden",
          }}
        >
          {report.proposed_variants.map((pv, i) => (
            <ProposedVariantRow key={pv.approval_id} variant={pv} isFirst={i === 0} />
          ))}
        </div>
      ) : null}
    </Section>
  );
}

function ProposedVariantRow({
  variant,
  isFirst,
}: {
  variant: ProposedVariant;
  isFirst: boolean;
}) {
  const media = variant.genome.media_asset;
  const ext = media && media.includes(".")
    ? media.split(".").pop()?.toLowerCase() ?? ""
    : "";
  const isVideo = ["mov", "mp4", "webm", "avi", "m4v", "mkv"].includes(ext);

  return (
    <div
      style={{
        padding: "14px 16px",
        borderTop: isFirst ? "none" : "1px solid var(--border-soft)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
        }}
      >
        <div style={{ fontSize: 13.5, minWidth: 0 }}>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontWeight: 500,
              color: "var(--accent)",
            }}
          >
            {variant.variant_code}
          </span>
          <span style={{ color: "var(--muted-2)" }}> · </span>
          <span style={{ color: "var(--ink)" }}>{variant.genome_summary}</span>
        </div>
        {variant.classification === "expiring_soon" ? (
          <StatusPill kind="fatigue">
            Expires in {variant.days_until_expiry} day
            {variant.days_until_expiry === 1 ? "" : "s"}
          </StatusPill>
        ) : (
          <StatusPill kind="new">New</StatusPill>
        )}
      </div>
      {media ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          <MediaBadge type={isVideo ? "video" : "image"} />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              color: "var(--muted)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {truncate(media, 70)}
          </span>
        </div>
      ) : null}
      {variant.hypothesis ? (
        <div style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.45 }}>
          {variant.hypothesis}
        </div>
      ) : null}
    </div>
  );
}

function BudgetSummary({ report }: { report: WeeklyReport }) {
  const revenue = toNum(report.total_purchase_value) ?? 0;
  const spend = toNum(report.total_spend) ?? 0;
  const netReturn = revenue - spend;
  const netIsPositive = netReturn >= 0;

  const rows: Array<{
    label: string;
    value: string;
    tone?: "good" | "bad";
  }> = [
    { label: "Total spend", value: formatCurrency(report.total_spend) },
    { label: "Total revenue", value: formatCurrency(report.total_purchase_value) },
    {
      label: "Net return",
      value: formatCurrency(netReturn),
      tone: netIsPositive ? "good" : "bad",
    },
    {
      label: "CPA",
      value:
        report.avg_cost_per_purchase != null && report.avg_cost_per_purchase !== ""
          ? formatCurrency(report.avg_cost_per_purchase)
          : "N/A",
    },
    {
      label: "ROAS",
      value:
        report.avg_roas != null && report.avg_roas !== ""
          ? `${formatOneDecimal(report.avg_roas)}x`
          : "N/A",
    },
    { label: "Variants launched", value: String(report.variants_launched) },
    { label: "Variants retired", value: String(report.variants_retired) },
  ];

  return (
    <Section label="Budget & efficiency summary">
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "white",
          overflow: "hidden",
        }}
      >
        {rows.map((r, i) => (
          <div
            key={r.label}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              padding: "10px 16px",
              borderTop: i === 0 ? "none" : "1px solid var(--border-soft)",
              alignItems: "baseline",
              fontSize: 13,
            }}
          >
            <span style={{ color: "var(--muted)" }}>{r.label}</span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                color:
                  r.tone === "good"
                    ? "oklch(40% 0.14 145)"
                    : r.tone === "bad"
                      ? "oklch(48% 0.16 28)"
                      : "var(--ink)",
              }}
            >
              {r.value}
            </span>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Section frame + metric grid
// ---------------------------------------------------------------------------

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 32 }}>
      <div className="eyebrow" style={{ marginBottom: 12 }}>
        {label}
      </div>
      {children}
    </section>
  );
}

function MetricGrid({ children }: { children: React.ReactNode }) {
  return (
    <div
      data-ds-grid
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 10,
      }}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}
