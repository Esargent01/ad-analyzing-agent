import type { ElementInsight } from "@/lib/api/types";
import { formatPct } from "@/lib/format";

interface ElementRankingProps {
  elements: ElementInsight[];
}

/**
 * Dual-column element leaderboard matching the weekly report's
 * "Element performance" section. One column ranks by hook rate
 * (attention), the other by CTR (efficiency). Top 8 in each.
 *
 * Sorting happens client-side so we don't need two separate backend
 * responses — the /api/campaigns/{id}/reports/weekly/{w} endpoint
 * returns one `top_elements` list and we slice it here.
 */
export function ElementRanking({ elements }: ElementRankingProps) {
  if (elements.length === 0) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        No element-level data yet — run a few cycles first.
      </p>
    );
  }

  const byHook = [...elements]
    .filter((e) => e.avg_hook_rate != null && e.avg_hook_rate !== "")
    .sort(
      (a, b) => Number(b.avg_hook_rate ?? 0) - Number(a.avg_hook_rate ?? 0),
    )
    .slice(0, 8);

  const byCtr = [...elements]
    .sort((a, b) => Number(b.avg_ctr ?? 0) - Number(a.avg_ctr ?? 0))
    .slice(0, 8);

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <RankingColumn
        title="Attention ranking"
        subtitle="By average hook rate"
        rows={byHook.map((e, i) => ({
          key: `${e.slot_name}-${e.slot_value}-${i}`,
          rank: i + 1,
          slot: e.slot_name,
          value: e.slot_value,
          metric:
            e.avg_hook_rate != null && e.avg_hook_rate !== ""
              ? formatPct(e.avg_hook_rate)
              : "—",
        }))}
      />
      <RankingColumn
        title="Efficiency ranking"
        subtitle="By CTR"
        rows={byCtr.map((e, i) => ({
          key: `${e.slot_name}-${e.slot_value}-ctr-${i}`,
          rank: i + 1,
          slot: e.slot_name,
          value: e.slot_value,
          metric: formatPct(e.avg_ctr),
        }))}
      />
    </div>
  );
}

interface RankingRow {
  key: string;
  rank: number;
  slot: string;
  value: string;
  metric: string;
}

function RankingColumn({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle: string;
  rows: RankingRow[];
}) {
  return (
    <div>
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mb-2 text-[11px] text-[var(--text-tertiary)]">{subtitle}</p>
      <div className="divide-y divide-[var(--border)] border-y border-[var(--border)]">
        {rows.map((row) => (
          <div
            key={row.key}
            className="grid grid-cols-[28px_1fr_auto] items-baseline gap-2 py-1.5 text-xs"
          >
            <span className="text-[var(--text-tertiary)]">#{row.rank}</span>
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-[0.3px] text-[var(--text-tertiary)]">
                {row.slot}
              </div>
              <div
                className="truncate text-[var(--text)]"
                title={row.value}
              >
                {row.value}
              </div>
            </div>
            <span className="text-right font-medium text-[var(--text)]">
              {row.metric}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
