import { FunnelChart } from "@/components/FunnelChart";
import { GenomePills } from "@/components/GenomePills";
import type {
  Diagnostic,
  ReportFunnelStage,
  VariantReport,
} from "@/lib/api/types";
import { cn } from "@/lib/cn";
import {
  formatCurrency,
  formatIntComma,
  formatOneDecimal,
} from "@/lib/format";

interface BestVariantSpotlightProps {
  variant: VariantReport;
  funnel: ReportFunnelStage[];
  diagnostics: Diagnostic[];
  projection: string | null;
}

/**
 * "Best ad today" spotlight for the daily report detail page. Renders
 * the 6-tile metric grid, the funnel visualization, the diagnostics
 * box, and the genome pills — matches the `.spotlight` section in
 * `daily_web.html` one-for-one.
 */
export function BestVariantSpotlight({
  variant,
  funnel,
  diagnostics,
  projection,
}: BestVariantSpotlightProps) {
  return (
    <section className="mb-8 rounded-lg border border-[var(--border)] p-5">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-base font-medium text-[var(--text)]">
          {variant.variant_code} · {variant.genome_summary}
        </div>
        <span className="status-pill status-winner">Best CPA today</span>
      </div>
      {variant.hypothesis ? (
        <div className="mb-3 text-xs italic leading-relaxed text-[var(--text-secondary)]">
          {variant.hypothesis}
        </div>
      ) : null}

      {/* 6-tile grid */}
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Tile
          label="Cost per purchase"
          value={
            variant.cost_per_purchase != null && variant.cost_per_purchase !== ""
              ? formatCurrency(variant.cost_per_purchase)
              : "—"
          }
          benchmark={
            variant.cost_per_purchase != null && variant.cost_per_purchase !== ""
              ? `target: < $${Math.round(Number(variant.cost_per_purchase) * 1.2)}`
              : null
          }
        />
        <Tile
          label="ROAS"
          value={
            variant.roas != null && variant.roas !== ""
              ? `${formatOneDecimal(variant.roas)}x`
              : "N/A"
          }
        />
        <Tile
          label="Purchases"
          value={formatIntComma(variant.purchases)}
        />
        <Tile
          label="Hook rate"
          value={
            variant.hook_rate_pct != null
              ? `${variant.hook_rate_pct.toFixed(1)}%`
              : "N/A"
          }
          benchmark="benchmark 30%"
        />
        <Tile
          label="Hold rate"
          value={
            variant.hold_rate_pct != null
              ? `${variant.hold_rate_pct.toFixed(1)}%`
              : "N/A"
          }
          benchmark="benchmark 25%"
        />
        <Tile
          label="CTR"
          value={
            variant.ctr_pct != null
              ? `${variant.ctr_pct.toFixed(1)}%`
              : "N/A"
          }
          benchmark="benchmark 1.5%"
        />
      </div>

      {/* Funnel */}
      {funnel.length > 0 ? (
        <FunnelChart variant="daily" stages={funnel} />
      ) : null}

      {/* Diagnostics */}
      {diagnostics.length > 0 || projection ? (
        <div className="mt-4 rounded bg-[var(--bg-secondary)] px-4 py-3">
          <div className="mb-1 text-xs font-medium">Diagnostics</div>
          {diagnostics.map((d, i) => (
            <div
              key={i}
              className={cn("py-0.5 text-xs leading-relaxed", severityClass(d))}
            >
              {d.text}
            </div>
          ))}
          {projection ? (
            <div className="mt-1 text-xs text-[var(--text-secondary)]">
              {projection}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* Creative DNA pills */}
      <GenomePills genome={variant.genome} />
    </section>
  );
}

function severityClass(d: Diagnostic): string {
  switch (d.severity) {
    case "good":
      return "text-[var(--green)]";
    case "warning":
      return "text-[var(--amber)]";
    case "bad":
      return "text-[var(--red)]";
    default:
      return "text-[var(--text-secondary)]";
  }
}

function Tile({
  label,
  value,
  benchmark,
}: {
  label: string;
  value: string;
  benchmark?: string | null;
}) {
  return (
    <div className="rounded bg-[var(--bg-secondary)] px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.3px] text-[var(--text-tertiary)]">
        {label}
      </div>
      <div className="text-base font-medium text-[var(--text)]">{value}</div>
      {benchmark ? (
        <div className="text-[10px] text-[var(--text-tertiary)]">
          {benchmark}
        </div>
      ) : null}
    </div>
  );
}
