import { Navigate, useNavigate, useParams } from "react-router-dom";

import { DashPage } from "@/components/dashboard/DashPage";
import { EmptyState } from "@/components/dashboard/primitives";
import { useDailyDates, useMe } from "@/lib/api/hooks";
import { formatDateLabel } from "@/lib/format";

/**
 * Daily reports index — one row per report date. Excludes today
 * (incomplete) at the API level.
 *
 * Port of ``kleiber-agent-deign/project/src/dashboard/screens-a.jsx::DailyList``.
 */
export function ReportsDailyListRoute() {
  const { campaignId = "" } = useParams();
  const navigate = useNavigate();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);
  const dates = useDailyDates(campaignId);

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  const rows = dates.data?.dates ?? [];

  return (
    <DashPage
      crumb={[
        { label: "Dashboard", href: "/dashboard" },
        {
          label: campaign?.name ?? "Campaign",
          href: `/campaigns/${campaignId}`,
        },
        { label: "Daily reports" },
      ]}
      title="daily reports"
      sub="one row per day, excluding today (incomplete)."
    >
      {dates.isLoading ? (
        <TableSkeleton rows={5} />
      ) : dates.isError ? (
        <EmptyState
          title="Couldn't load daily reports"
          desc="Something went wrong fetching the report index. Try refreshing, or come back in a few minutes."
          icon="!"
        />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No daily reports yet"
          desc="Reports are generated after a full daily cycle runs. Connect Meta, import a campaign, then wait for tomorrow morning's email."
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
          {rows.map((iso, i) => (
            <button
              key={iso}
              type="button"
              onClick={() =>
                navigate(`/campaigns/${campaignId}/reports/daily/${iso}`)
              }
              style={{
                display: "grid",
                gridTemplateColumns: "220px 1fr 30px",
                alignItems: "center",
                padding: "14px 20px",
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
                borderTop: "none",
                transition: "background 0.12s",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "var(--paper-2)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "white")
              }
            >
              <span
                style={{ fontSize: 14, fontWeight: 500, color: "var(--ink)" }}
              >
                {formatDateLabel(iso)}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: "var(--muted)",
                }}
              >
                {iso}
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
            padding: "14px 20px",
            borderBottom:
              i < rows - 1 ? "1px solid var(--border-soft)" : "none",
            display: "grid",
            gridTemplateColumns: "220px 1fr",
            gap: 14,
          }}
        >
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
              height: 12,
              width: "40%",
              background: "var(--paper-2)",
              borderRadius: 4,
            }}
          />
        </div>
      ))}
    </div>
  );
}
