import type { ReportFunnelStage, FunnelStage } from "@/lib/api/types";
import { formatIntComma, formatPct, formatCurrency } from "@/lib/format";

/**
 * Stage-color lookup for the weekly report's full-funnel view.
 * Taken verbatim from `src/reports/templates/weekly_web.html` so the
 * dashboard matches the static HTML reports pixel-for-pixel.
 */
const WEEKLY_STAGE_COLORS: Record<string, string> = {
  Impressions: "#534AB7",
  "Video views (3s)": "#7F77DD",
  "Video views (15s)": "#378ADD",
  "Link clicks": "#1D9E75",
  "Landing page views": "#4DAA57",
  "Add to carts": "#639922",
  Purchases: "#27500A",
};
const WEEKLY_DEFAULT_COLOR = "#534AB7";

interface FunnelChartDailyProps {
  /** Daily report stages (already contain `bar_color`). */
  stages: ReportFunnelStage[];
  variant: "daily";
}

interface FunnelChartWeeklyProps {
  /** Weekly report stages (we colour them here from the name). */
  stages: FunnelStage[];
  variant: "weekly";
}

type FunnelChartProps = FunnelChartDailyProps | FunnelChartWeeklyProps;

/**
 * Horizontal funnel visualization. We deliberately don't use Recharts:
 * the existing Jinja templates render the funnel as plain CSS bars with
 * widths proportional to the first-stage count, and the Recharts Funnel
 * chart uses a trapezoid shape that wouldn't match. Keeping this as a
 * styled div means 1:1 visual parity with the email/report HTML and
 * zero chart-lib overhead.
 */
export function FunnelChart(props: FunnelChartProps) {
  if (props.variant === "daily") {
    return <DailyFunnel stages={props.stages} />;
  }
  return <WeeklyFunnel stages={props.stages} />;
}

function DailyFunnel({ stages }: { stages: ReportFunnelStage[] }) {
  if (stages.length === 0) return null;
  const maxCount = stages[0].count || 1;

  return (
    <div className="mt-3">
      {stages.map((stage, idx) => {
        const rawPct = (stage.count / maxCount) * 100;
        const barWidth = Math.max(rawPct, 5);
        const next = stages[idx + 1];
        return (
          <div key={`${stage.label}-${idx}`}>
            <div className="mb-px flex items-center">
              <span className="w-[90px] flex-shrink-0 pr-2.5 text-right text-xs text-[var(--text-secondary)]">
                {stage.label}
              </span>
              <div
                className="flex h-7 min-w-[30px] items-center rounded px-2.5 text-[11px] font-medium text-white"
                style={{
                  width: `${barWidth}%`,
                  background: stage.bar_color,
                }}
              >
                {formatIntComma(stage.count)}
              </div>
              <span className="ml-2 whitespace-nowrap text-[11px] text-[var(--text-tertiary)]">
                {stage.rate_pct != null
                  ? `${stage.rate_pct.toFixed(1)}% ${stage.rate_label}`
                  : ""}
              </span>
            </div>
            {next && stage.dropoff_pct != null ? (
              <div className="my-px ml-[100px] text-center text-[10px] text-[var(--text-tertiary)]">
                ↓ {Math.round(stage.dropoff_pct)}% didn&apos;t{" "}
                {next.label.toLowerCase()}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function WeeklyFunnel({ stages }: { stages: FunnelStage[] }) {
  if (stages.length === 0) return null;
  const maxValue = stages[0].value || 1;

  return (
    <div className="mt-3">
      {stages.map((stage, idx) => {
        const rawPct = (stage.value / maxValue) * 100;
        const barWidth = Math.max(rawPct, 5);
        const color = WEEKLY_STAGE_COLORS[stage.stage_name] ?? WEEKLY_DEFAULT_COLOR;
        return (
          <div key={`${stage.stage_name}-${idx}`} className="mb-px flex items-center">
            <span className="w-[120px] flex-shrink-0 pr-2.5 text-right text-xs text-[var(--text-secondary)]">
              {stage.stage_name}
            </span>
            <div
              className="flex h-7 min-w-[30px] items-center rounded px-2.5 text-[11px] font-medium text-white"
              style={{ width: `${barWidth}%`, background: color }}
            >
              {formatIntComma(stage.value)}
            </div>
            <span className="ml-2 whitespace-nowrap text-[11px] text-[var(--text-tertiary)]">
              {stage.rate != null && stage.rate !== "" ? formatPct(stage.rate) : ""}
              {stage.cost_per != null && stage.cost_per !== ""
                ? ` · ${formatCurrency(stage.cost_per)}/ea`
                : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
