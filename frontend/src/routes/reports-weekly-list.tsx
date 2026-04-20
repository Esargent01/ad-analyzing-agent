import { Navigate, useNavigate, useParams } from "react-router-dom";

import { DashPage } from "@/components/dashboard/DashPage";
import { EmptyState } from "@/components/dashboard/primitives";
import { useMe, useWeeklyIndex } from "@/lib/api/hooks";
import { formatDateLabel } from "@/lib/format";

/**
 * Weekly reports index — one row per week, using the pre-computed
 * `label` from the backend (e.g., "Mar 30 - Apr 5") so date ranges
 * read nicely without extra client math. URL uses week_start as the
 * stable path key to sidestep ISO-week ambiguity.
 *
 * Layout mirrors ``reports-daily-list.tsx`` for consistency.
 */
export function ReportsWeeklyListRoute() {
  const { campaignId = "" } = useParams();
  const navigate = useNavigate();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);
  const weeks = useWeeklyIndex(campaignId);

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  const rows = weeks.data?.weeks ?? [];

  return (
    <DashPage
      crumb={[
        { label: "Dashboard", href: "/dashboard" },
        {
          label: campaign?.name ?? "Campaign",
          href: `/campaigns/${campaignId}`,
        },
        { label: "Weekly reports" },
      ]}
      title="weekly reports"
      sub="one row per completed iso week. latest first."
    >
      {weeks.isLoading ? (
        <TableSkeleton rows={5} />
      ) : weeks.isError ? (
        <EmptyState
          title="Couldn't load weekly reports"
          desc="Something went wrong fetching the weekly index. Try refreshing in a moment."
          icon="!"
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No weekly reports yet"
          desc="Weekly reports generate once a full Mon–Sun week of metrics has landed. Keep a campaign running and one will appear here."
          icon="◎"
        />
      ) : (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 12,
            overflow: "hidden",
            background: "white",
          }}
        >
          {rows.map((week, i) => (
            <button
              key={week.week_start}
              type="button"
              onClick={() =>
                navigate(
                  `/campaigns/${campaignId}/reports/weekly/${week.week_start}`,
                )
              }
              style={{
                display: "grid",
                gridTemplateColumns: "280px 1fr 30px",
                alignItems: "center",
                padding: "16px 20px",
                width: "100%",
                textAlign: "left",
                borderBottom:
                  i < rows.length - 1
                    ? "1px solid var(--border-soft)"
                    : "none",
                cursor: "pointer",
                background: "white",
                fontFamily: "inherit",
                color: "inherit",
                border: "none",
                transition: "background 0.12s",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "var(--paper-2)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "white")
              }
            >
              <div>
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 500,
                    color: "var(--ink)",
                  }}
                >
                  {week.label}
                </div>
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "var(--muted)",
                    marginTop: 2,
                  }}
                >
                  {formatDateLabel(week.week_start)} –{" "}
                  {formatDateLabel(week.week_end)}
                </div>
              </div>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: "var(--muted)",
                }}
              >
                {week.week_start}
              </span>
              <span
                style={{ color: "var(--muted)", textAlign: "right" }}
                aria-hidden
              >
                →
              </span>
            </button>
          ))}
        </div>
      )}
    </DashPage>
  );
}

function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        overflow: "hidden",
        background: "white",
      }}
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            padding: "16px 20px",
            borderBottom:
              i < rows - 1 ? "1px solid var(--border-soft)" : "none",
            display: "grid",
            gridTemplateColumns: "280px 1fr",
            gap: 14,
          }}
        >
          <div>
            <div
              style={{
                height: 14,
                width: "70%",
                background: "var(--paper-2)",
                borderRadius: 4,
              }}
            />
            <div
              style={{
                height: 10,
                width: "50%",
                background: "var(--paper-2)",
                borderRadius: 4,
                marginTop: 6,
              }}
            />
          </div>
          <div
            style={{
              height: 12,
              width: "40%",
              background: "var(--paper-2)",
              borderRadius: 4,
              justifySelf: "end",
            }}
          />
        </div>
      ))}
    </div>
  );
}
