import type { ElementInsight } from "@/lib/api/types";
import { formatPct } from "@/lib/format";

interface ElementRankingProps {
  elements: ElementInsight[];
}

/**
 * Dual-column element leaderboard for the weekly report.
 *
 * Ported to match the warm-editorial palette — white-card columns
 * with warm-paper header bars, mono numerics, element values shown
 * inline with their slot label. Sorting is client-side so the
 * backend only has to serve one ``top_elements`` list.
 */
export function ElementRanking({ elements }: ElementRankingProps) {
  if (elements.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
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
    <div
      data-ds-grid
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 14,
      }}
    >
      <RankingColumn
        title="Attention ranking"
        subtitle="by average hook rate"
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
        subtitle="by CTR"
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
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--border)",
          background: "var(--paper-2)",
        }}
      >
        <div
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--ink)",
            letterSpacing: "-0.01em",
          }}
        >
          {title}
        </div>
        <div
          className="eyebrow"
          style={{ fontSize: 9.5, marginTop: 3 }}
        >
          {subtitle}
        </div>
      </div>
      {rows.length === 0 ? (
        <div
          style={{
            padding: "18px 16px",
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          No rows yet.
        </div>
      ) : (
        rows.map((row, i) => (
          <div
            key={row.key}
            style={{
              display: "grid",
              gridTemplateColumns: "32px 1fr auto",
              alignItems: "center",
              gap: 10,
              padding: "11px 16px",
              borderBottom:
                i < rows.length - 1
                  ? "1px solid var(--border-soft)"
                  : "none",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10.5,
                color: "var(--muted)",
              }}
            >
              #{row.rank}
            </span>
            <div style={{ minWidth: 0 }}>
              <div className="eyebrow" style={{ fontSize: 9.5 }}>
                {row.slot}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: "var(--ink)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={row.value}
              >
                {row.value}
              </div>
            </div>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                fontWeight: 500,
                color:
                  row.metric.startsWith("-") || row.metric === "—"
                    ? "var(--ink-2)"
                    : "oklch(40% 0.14 145)",
                textAlign: "right",
              }}
            >
              {row.metric}
            </span>
          </div>
        ))
      )}
    </div>
  );
}
