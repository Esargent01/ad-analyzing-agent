import { Navigate, useParams } from "react-router-dom";

import { BestVariantSpotlight } from "@/components/BestVariantSpotlight";
import { MetricCard } from "@/components/MetricCard";
import { DailyVariantTable } from "@/components/VariantTable";
import { DashPage } from "@/components/dashboard/DashPage";
import { EmptyState, StatusPill } from "@/components/dashboard/primitives";
import { SkeletonReportBody } from "@/components/ui/Skeleton";
import { useDailyReport, useMe } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import type { DailyReport, FatigueAlert, ReportCycleAction } from "@/lib/api/types";
import { formatDateLabel } from "@/lib/format";
import { topLineLabelFor } from "@/lib/objectives";

/**
 * Daily report detail page. Mirrors `daily_web.html` section-by-section:
 * header, 4-card top-line metrics, best-variant spotlight, "other active
 * variants" table, fatigue alerts, actions, next-cycle preview.
 *
 * Ported to the warm-editorial system: sections get eyebrow labels +
 * warm-paper card containers, action chips use the shared ``StatusPill``
 * primitive, and text colors map onto ``--ink`` / ``--muted`` rather
 * than the legacy ``--text-*`` tokens.
 */
export function DailyReportDetailRoute() {
  const { campaignId = "", reportDate = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const report = useDailyReport(campaignId, reportDate);

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
      label: "Daily",
      href: `/campaigns/${campaignId}/reports/daily`,
    },
    { label: reportDate },
  ];

  if (report.isError && report.error instanceof ApiError && report.error.status === 404) {
    return (
      <DashPage
        crumb={crumb}
        title={<>daily · <span className="serif">{reportDate}</span></>}
      >
        <EmptyState
          title={`No daily report for ${formatDateLabel(reportDate)}`}
          desc="The cycle may not have run that day, or the date is outside your campaign window. Pick another date from the index."
          icon="?"
        />
      </DashPage>
    );
  }

  const sub = report.data ? (
    <>
      {report.data.campaign_name ?? campaign?.name} ·{" "}
      <span
        style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}
      >
        day {report.data.day_number} · cycle {report.data.cycle_number}
      </span>
    </>
  ) : null;

  return (
    <DashPage
      crumb={crumb}
      title={<>daily · <span className="serif">{reportDate}</span></>}
      sub={sub}
    >
      {report.isLoading && !report.data ? <SkeletonReportBody /> : null}

      {report.data ? <DailyReportBody report={report.data} /> : null}
    </DashPage>
  );
}

function DailyReportBody({ report }: { report: DailyReport }) {
  // Per-objective top-line eyebrow label. Matches the design-system's
  // mono-uppercase treatment on campaign detail etc.
  const topLineLabel = topLineLabelFor(report.objective ?? "OUTCOME_SALES");

  return (
    <>
      {/* Top-line metric cards — data-driven. ``report.headline_metrics``
          is built server-side per the campaign's Meta objective so
          every screen renders the same cards with matching labels. */}
      <Section label={topLineLabel}>
        <div
          data-ds-grid
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 10,
          }}
        >
          {report.headline_metrics.map((card, i) => (
            <MetricCard
              key={`${card.label}-${i}`}
              label={card.label}
              value={card.value}
              trend={card.sub ?? null}
              tone={card.tone === "good" ? "up" : card.tone === "bad" ? "down" : "neutral"}
            />
          ))}
        </div>
      </Section>

      {/* Best-variant spotlight — the component emits its own eyebrow,
          so don't wrap it in a Section or the label renders twice. */}
      {report.best_variant ? (
        <div style={{ marginBottom: 32 }}>
          <BestVariantSpotlight
            variant={report.best_variant}
            funnel={report.best_variant_funnel}
            diagnostics={report.best_variant_diagnostics}
            projection={report.best_variant_projection}
            summaryNumbers={report.best_variant_summary}
            diagnosticTiles={report.best_variant_diagnostic_tiles}
          />
        </div>
      ) : null}

      {/* Other active variants — columns are objective-aware. */}
      <Section label="Other active variants">
        <DailyVariantTable
          variants={report.variants}
          columns={report.variant_table_columns}
        />
      </Section>

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
        <Section label="Next cycle preview">
          <div
            style={{
              border: "1px solid var(--border)",
              borderRadius: 12,
              background: "white",
              overflow: "hidden",
            }}
          >
            {report.next_cycle.map((n, i) => (
              <div
                key={i}
                style={{
                  padding: "14px 16px",
                  borderTop: i === 0 ? "none" : "1px solid var(--border-soft)",
                }}
              >
                <div
                  style={{
                    fontSize: 13.5,
                    fontWeight: 500,
                    color: "var(--ink)",
                    lineHeight: 1.45,
                  }}
                >
                  {n.hypothesis}
                </div>
                <div
                  style={{
                    marginTop: 4,
                    fontFamily: "var(--font-mono)",
                    fontSize: 11.5,
                    color: "var(--muted)",
                  }}
                >
                  {n.genome_summary}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ) : null}
    </>
  );
}

function FatigueAlertsSection({ alerts }: { alerts: FatigueAlert[] }) {
  return (
    <Section label="Fatigue alerts">
      <div
        style={{
          border: "1px solid oklch(88% 0.08 28)",
          borderRadius: 12,
          background: "oklch(98% 0.02 28)",
          overflow: "hidden",
        }}
      >
        {alerts.map((a, i) => (
          <div
            key={`${a.variant_code}-${i}`}
            data-ds-grid
            style={{
              display: "grid",
              gridTemplateColumns: "90px 1fr 1fr",
              gap: 16,
              padding: "12px 16px",
              borderTop: i === 0 ? "none" : "1px solid oklch(90% 0.06 28)",
              alignItems: "center",
              fontSize: 12.5,
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                fontSize: 13,
                color: "oklch(40% 0.16 28)",
              }}
            >
              {a.variant_code}
            </span>
            <span style={{ color: "var(--ink)" }}>{a.reason}</span>
            <span style={{ color: "var(--muted)" }}>{a.recommendation}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function ActionsSection({ actions }: { actions: ReportCycleAction[] }) {
  return (
    <Section label="Actions taken">
      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "white",
          overflow: "hidden",
        }}
      >
        {actions.map((a, i) => (
          <div
            key={`${a.variant_code}-${i}`}
            data-ds-grid
            style={{
              display: "grid",
              gridTemplateColumns: "110px 90px 1fr",
              gap: 16,
              padding: "12px 16px",
              borderTop: i === 0 ? "none" : "1px solid var(--border-soft)",
              alignItems: "center",
              fontSize: 12.5,
            }}
          >
            <StatusPill kind={actionKind(a.action_type)}>
              {a.action_type}
            </StatusPill>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                fontSize: 13,
                color: "var(--ink)",
              }}
            >
              {a.variant_code}
            </span>
            <span style={{ color: "var(--muted)" }}>{a.details ?? ""}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Section frame — eyebrow label + consistent vertical rhythm.
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function actionKind(
  actionType: string,
): "winner" | "paused" | "fatigue" | "new" | "steady" {
  const t = actionType.toLowerCase();
  if (t.includes("pause")) return "paused";
  if (t.includes("scale") || t.includes("winner")) return "winner";
  if (t.includes("launch") || t.includes("deploy") || t.includes("new")) return "new";
  if (t.includes("fatigue") || t.includes("retire")) return "fatigue";
  return "steady";
}
