import { Link, Navigate, useParams } from "react-router-dom";

import { BestVariantSpotlight } from "@/components/BestVariantSpotlight";
import { MetricCard } from "@/components/MetricCard";
import { DailyVariantTable } from "@/components/VariantTable";
import { Card, CardContent } from "@/components/ui/Card";
import { SkeletonReportBody } from "@/components/ui/Skeleton";
import { useDailyReport, useMe } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import type { DailyReport, FatigueAlert, ReportCycleAction } from "@/lib/api/types";
import { formatCurrency, formatDateLabel, formatIntComma, formatOneDecimal } from "@/lib/format";

/**
 * Daily report detail page. Mirrors `daily_web.html` section-by-section:
 * header, 4-card top-line metrics, best-variant spotlight, "other active
 * variants" table, fatigue alerts, actions, next-cycle preview.
 */
export function DailyReportDetailRoute() {
  const { campaignId = "", reportDate = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const report = useDailyReport(campaignId, reportDate);

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  if (report.isError && report.error instanceof ApiError && report.error.status === 404) {
    return (
      <NotFound
        campaignId={campaignId}
        campaignName={campaign?.name}
        reportDate={reportDate}
      />
    );
  }

  return (
    <div>
      <Breadcrumb campaignId={campaignId} campaignName={campaign?.name} />

      <div className="mb-6">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="rounded-xl bg-[var(--accent)] px-2.5 py-0.5 font-medium text-white">
            Daily report
          </span>
          <time className="text-[var(--text-tertiary)]">
            {formatDateLabel(reportDate)}
          </time>
        </div>
        <h1 className="mt-2 text-xl font-medium">
          {report.data?.campaign_name ?? campaign?.name ?? "Daily report"}
        </h1>
        {report.data ? (
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            Day {report.data.day_number} · Cycle {report.data.cycle_number}
          </p>
        ) : null}
      </div>

      {report.isLoading && !report.data ? <SkeletonReportBody /> : null}

      {report.data ? (
        <DailyReportBody report={report.data} />
      ) : null}
    </div>
  );
}

function DailyReportBody({ report }: { report: DailyReport }) {
  return (
    <>
      {/* Top-line metric cards */}
      <div className="mb-8 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricCard
          label="Spend"
          value={formatCurrency(report.total_spend)}
          trend={renderDelta(report.total_spend, report.prev_spend)}
          tone="neutral"
        />
        <MetricCard
          label="Purchases"
          value={formatIntComma(report.total_purchases)}
          trend={renderDelta(report.total_purchases, report.prev_purchases)}
          tone={
            changeTone(report.total_purchases, report.prev_purchases, "higher-is-better")
          }
        />
        <MetricCard
          label="Avg. CPA"
          value={
            report.avg_cost_per_purchase != null && report.avg_cost_per_purchase !== ""
              ? formatCurrency(report.avg_cost_per_purchase)
              : "—"
          }
          trend={renderDelta(report.avg_cost_per_purchase, report.prev_avg_cpa)}
          tone={
            changeTone(report.avg_cost_per_purchase, report.prev_avg_cpa, "lower-is-better")
          }
        />
        <MetricCard
          label="ROAS"
          value={
            report.avg_roas != null && report.avg_roas !== ""
              ? `${formatOneDecimal(report.avg_roas)}x`
              : "N/A"
          }
          trend={renderDelta(report.avg_roas, report.prev_avg_roas)}
          tone={
            changeTone(report.avg_roas, report.prev_avg_roas, "higher-is-better")
          }
        />
      </div>

      {/* Best-variant spotlight */}
      {report.best_variant ? (
        <BestVariantSpotlight
          variant={report.best_variant}
          funnel={report.best_variant_funnel}
          diagnostics={report.best_variant_diagnostics}
          projection={report.best_variant_projection}
        />
      ) : null}

      {/* Other active variants */}
      <section className="mb-8">
        <h2 className="mb-3 text-[15px] font-medium">Other active variants</h2>
        <DailyVariantTable variants={report.variants} />
      </section>

      {/* Fatigue alerts */}
      {report.fatigue_alerts.length > 0 ? (
        <FatigueAlertsSection alerts={report.fatigue_alerts} />
      ) : null}

      {/* Actions taken */}
      {report.actions.length > 0 ? (
        <ActionsSection actions={report.actions} />
      ) : null}

      {/* Next cycle preview */}
      {report.next_cycle.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-[15px] font-medium">Next cycle preview</h2>
          <div className="divide-y divide-[var(--border)]">
            {report.next_cycle.map((n, i) => (
              <div key={i} className="py-2">
                <div className="text-sm font-medium text-[var(--text)]">
                  {n.hypothesis}
                </div>
                <div className="text-xs text-[var(--text-secondary)]">
                  {n.genome_summary}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

function FatigueAlertsSection({ alerts }: { alerts: FatigueAlert[] }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-[15px] font-medium">Fatigue alerts</h2>
      <div className="divide-y divide-[var(--border)]">
        {alerts.map((a, i) => (
          <div
            key={`${a.variant_code}-${i}`}
            className="grid gap-1 py-2 text-xs sm:grid-cols-[100px_1fr_1fr] sm:gap-3"
          >
            <strong className="font-mono text-[var(--text)]">
              {a.variant_code}
            </strong>
            <span className="text-[var(--text)]">{a.reason}</span>
            <span className="text-[var(--text-secondary)]">
              {a.recommendation}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ActionsSection({ actions }: { actions: ReportCycleAction[] }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-[15px] font-medium">Actions taken</h2>
      <div className="divide-y divide-[var(--border)]">
        {actions.map((a, i) => (
          <div
            key={`${a.variant_code}-${i}`}
            className="grid items-center gap-2 py-2 text-xs sm:grid-cols-[100px_100px_1fr] sm:gap-3"
          >
            <span className="rounded bg-[var(--bg-secondary)] px-2 py-0.5 text-center text-[10px] uppercase tracking-[0.3px] text-[var(--text-tertiary)]">
              {a.action_type}
            </span>
            <strong className="font-mono text-[var(--text)]">
              {a.variant_code}
            </strong>
            <span className="text-[var(--text-secondary)]">
              {a.details ?? ""}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type DeltaDirection = "higher-is-better" | "lower-is-better";

function toNumOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function renderDelta(
  current: number | string | null | undefined,
  previous: number | string | null | undefined,
): string | null {
  const curr = toNumOrNull(current);
  const prev = toNumOrNull(previous);
  if (curr == null || prev == null || prev === 0) return null;
  const delta = ((curr - prev) / prev) * 100;
  const arrow = delta > 0.05 ? "↑" : delta < -0.05 ? "↓" : "→";
  return `${arrow} ${delta.toFixed(1)}%`;
}

function changeTone(
  current: number | string | null | undefined,
  previous: number | string | null | undefined,
  direction: DeltaDirection,
): "up" | "down" | "flat" | "neutral" {
  const curr = toNumOrNull(current);
  const prev = toNumOrNull(previous);
  if (curr == null || prev == null || prev === 0) return "neutral";
  const delta = curr - prev;
  if (Math.abs(delta) < 1e-9) return "flat";
  const better = direction === "higher-is-better" ? delta > 0 : delta < 0;
  return better ? "up" : "down";
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
        to={`/campaigns/${campaignId}/reports/daily`}
        className="text-[var(--accent)] no-underline hover:underline"
      >
        ← Daily reports
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
  reportDate,
}: {
  campaignId: string;
  campaignName?: string;
  reportDate: string;
}) {
  return (
    <div>
      <Breadcrumb campaignId={campaignId} campaignName={campaignName} />
      <Card>
        <CardContent>
          <p className="text-sm text-[var(--text)]">
            No daily report for {formatDateLabel(reportDate)}.
          </p>
          <p className="mt-2 text-xs text-[var(--text-tertiary)]">
            The cycle may not have run that day, or the date is outside your
            campaign window.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
