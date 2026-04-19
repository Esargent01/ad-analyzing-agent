import { Link, Navigate, useParams } from "react-router-dom";

import { FunnelChart } from "@/components/FunnelChart";
import { ElementRanking } from "@/components/ElementRanking";
import { InteractionList } from "@/components/InteractionList";
import { MetricCard } from "@/components/MetricCard";
import { WeeklyVariantTable } from "@/components/VariantTable";
import { Card, CardContent } from "@/components/ui/Card";
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
 */
export function WeeklyReportDetailRoute() {
  const { campaignId = "", weekStart = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const report = useWeeklyReport(campaignId, weekStart);

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  if (
    report.isError &&
    report.error instanceof ApiError &&
    report.error.status === 404
  ) {
    return (
      <NotFound
        campaignId={campaignId}
        campaignName={campaign?.name}
        weekStart={weekStart}
      />
    );
  }

  return (
    <div>
      <Breadcrumb campaignId={campaignId} campaignName={campaign?.name} />

      <div className="mb-6">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="rounded-xl bg-[var(--accent)] px-2.5 py-0.5 font-medium text-white">
            Weekly report
          </span>
          <time className="text-[var(--text-tertiary)]">
            {report.data
              ? `${formatDateLabel(report.data.week_start)} – ${formatDateLabel(
                  report.data.week_end,
                )}`
              : formatDateLabel(weekStart)}
          </time>
        </div>
        <h1 className="mt-2 text-xl font-medium">
          {report.data?.campaign_name ?? campaign?.name ?? "Weekly report"}
        </h1>
        {report.data ? (
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            {report.data.cycles_run} cycles ·{" "}
            {report.data.variants_launched} launched ·{" "}
            {report.data.variants_retired} retired
          </p>
        ) : null}
      </div>

      {report.isLoading && !report.data ? <SkeletonReportBody /> : null}

      {report.data ? <WeeklyReportBody report={report.data} /> : null}
    </div>
  );
}

function WeeklyReportBody({ report }: { report: WeeklyReport }) {
  return (
    <>
      {/* Row 1 — Purchase metrics */}
      <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
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
      </div>

      {/* Row 2 — Engagement metrics. Image-only campaigns swap Hook/Hold
          for Frequency/ATC rate; the video-specific tiles would read 0%
          on static creatives. */}
      <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
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
      </div>

      {/* Row 3 — Volume metrics */}
      <div className="mb-8 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricCard
          label="Impressions"
          value={formatIntComma(report.total_impressions)}
        />
        <MetricCard
          label="Reach"
          value={formatIntComma(report.total_reach)}
        />
        <MetricCard
          label="Revenue"
          value={formatCurrency(report.total_purchase_value)}
        />
        <MetricCard
          label="Frequency"
          value={formatOneDecimal(report.avg_frequency)}
        />
      </div>

      {/* Full funnel breakdown */}
      {report.funnel_stages.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[15px] font-medium">
            Full funnel breakdown
          </h2>
          <FunnelChart variant="weekly" stages={report.funnel_stages} />
        </section>
      ) : null}

      {/* Next week's experiments */}
      {report.proposed_variants.length > 0 ||
      report.generation_paused ||
      report.expired_count > 0 ? (
        <NextWeekExperiments report={report} />
      ) : null}

      {/* Variant leaderboard */}
      {report.all_variants.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[15px] font-medium">Variant leaderboard</h2>
          <WeeklyVariantTable variants={report.all_variants} />
        </section>
      ) : null}

      {/* Element performance */}
      {report.top_elements.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[15px] font-medium">Element performance</h2>
          <ElementRanking elements={report.top_elements} />
        </section>
      ) : null}

      {/* Top element interactions */}
      {report.top_interactions.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[15px] font-medium">
            Top element interactions
          </h2>
          <InteractionList interactions={report.top_interactions} />
        </section>
      ) : null}

      {/* Budget & efficiency summary */}
      <BudgetSummary report={report} />
    </>
  );
}

function NextWeekExperiments({ report }: { report: WeeklyReport }) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 flex items-center gap-2 text-[15px] font-medium">
        Next week&rsquo;s experiments
        {report.proposed_variants.length > 0 ? (
          <span className="text-xs font-normal text-[var(--text-tertiary)]">
            · {report.proposed_variants.length} proposed
          </span>
        ) : null}
      </h2>

      {report.expired_count > 0 ? (
        <p className="mb-1.5 text-xs text-[var(--text-tertiary)]">
          {report.expired_count} older proposal
          {report.expired_count === 1 ? "" : "s"} expired without review and
          were auto-rejected.
        </p>
      ) : null}

      {report.generation_paused ? (
        <p className="mb-1.5 text-xs text-[var(--amber)]">
          {report.proposed_variants.length > 0
            ? "⚠ New variant generation paused — clear the review queue to resume."
            : "⚠ New variant generation paused — your active variants are at capacity. Retire a variant to make room for new experiments."}
        </p>
      ) : null}

      <div className="mt-2 divide-y divide-[var(--border)]">
        {report.proposed_variants.map((pv) => (
          <ProposedVariantRow key={pv.approval_id} variant={pv} />
        ))}
      </div>
    </section>
  );
}

function ProposedVariantRow({ variant }: { variant: ProposedVariant }) {
  const media = variant.genome.media_asset;
  const ext = media && media.includes(".")
    ? media.split(".").pop()?.toLowerCase() ?? ""
    : "";
  const isVideo = ["mov", "mp4", "webm", "avi", "m4v", "mkv"].includes(ext);

  return (
    <div className="flex flex-col gap-1 py-3">
      <div className="flex items-center justify-between gap-2.5">
        <div className="text-[13px]">
          <span className="font-mono font-medium text-[var(--accent)]">
            {variant.variant_code}
          </span>
          <span className="text-[var(--text-tertiary)]"> · </span>
          <span className="text-[var(--text)]">{variant.genome_summary}</span>
        </div>
        {variant.classification === "expiring_soon" ? (
          <span className="inline-block whitespace-nowrap rounded-[10px] bg-[#FFF4D6] px-2 py-0.5 text-[10px] text-[#B07C1A]">
            Expires in {variant.days_until_expiry} day
            {variant.days_until_expiry === 1 ? "" : "s"}
          </span>
        ) : (
          <span className="inline-block whitespace-nowrap rounded-[10px] bg-[#EDF4EC] px-2 py-0.5 text-[10px] text-[#2B6B30]">
            New
          </span>
        )}
      </div>
      {media ? (
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <span
            className="inline-block whitespace-nowrap rounded-[3px] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.04em]"
            style={{
              backgroundColor: isVideo ? "#e0e7ff" : "#f4f3f0",
              color: isVideo ? "#3730a3" : "#475569",
            }}
          >
            {isVideo ? "Video" : "Image"}
          </span>
          <span className="truncate font-mono text-[var(--text-secondary)]">
            {truncate(media, 70)}
          </span>
        </div>
      ) : null}
      {variant.hypothesis ? (
        <div className="text-xs text-[var(--text-secondary)]">
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

  return (
    <section className="mb-8">
      <h2 className="mb-3 text-[15px] font-medium">
        Budget &amp; efficiency summary
      </h2>
      <table className="w-full border-collapse text-xs">
        <tbody>
          <BudgetRow label="Total spend" value={formatCurrency(report.total_spend)} />
          <BudgetRow
            label="Total revenue"
            value={formatCurrency(report.total_purchase_value)}
          />
          <BudgetRow
            label="Net return"
            value={formatCurrency(netReturn)}
            valueClassName={
              netIsPositive ? "text-[var(--green)]" : "text-[var(--red)]"
            }
          />
          <BudgetRow
            label="CPA"
            value={
              report.avg_cost_per_purchase != null &&
              report.avg_cost_per_purchase !== ""
                ? formatCurrency(report.avg_cost_per_purchase)
                : "N/A"
            }
          />
          <BudgetRow
            label="ROAS"
            value={
              report.avg_roas != null && report.avg_roas !== ""
                ? `${formatOneDecimal(report.avg_roas)}x`
                : "N/A"
            }
          />
          <BudgetRow
            label="Variants launched"
            value={String(report.variants_launched)}
          />
          <BudgetRow
            label="Variants retired"
            value={String(report.variants_retired)}
          />
        </tbody>
      </table>
    </section>
  );
}

function BudgetRow({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <tr className="border-b border-[var(--border)]">
      <td className="p-2 text-[var(--text-secondary)]">{label}</td>
      <td className={`p-2 text-right font-medium ${valueClassName ?? ""}`}>
        {value}
      </td>
    </tr>
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

function Breadcrumb({
  campaignId,
  campaignName,
}: {
  campaignId: string;
  campaignName?: string;
}) {
  return (
    <div className="mb-4 text-xs">
      <Link
        to={`/campaigns/${campaignId}/reports/weekly`}
        className="text-[var(--accent)] no-underline hover:underline"
      >
        ← Weekly reports
      </Link>
      {campaignName ? (
        <>
          <span className="mx-1 text-[var(--text-tertiary)]">·</span>
          <Link
            to={`/campaigns/${campaignId}`}
            className="text-[var(--text-tertiary)] no-underline hover:underline"
          >
            {campaignName}
          </Link>
        </>
      ) : null}
    </div>
  );
}

function NotFound({
  campaignId,
  campaignName,
  weekStart,
}: {
  campaignId: string;
  campaignName?: string;
  weekStart: string;
}) {
  return (
    <div>
      <Breadcrumb campaignId={campaignId} campaignName={campaignName} />
      <Card>
        <CardContent>
          <p className="text-sm text-[var(--text)]">
            No weekly report for the week of {formatDateLabel(weekStart)}.
          </p>
          <p className="mt-2 text-xs text-[var(--text-tertiary)]">
            The week may not have any completed cycles, or the date is outside
            your campaign window.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
