import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { DashPage } from "@/components/dashboard/DashPage";
import {
  EmptyState,
  StatusPill,
} from "@/components/dashboard/primitives";
import {
  qk,
  useConnectMeta,
  useDisconnectMeta,
  useMe,
  useMetaStatus,
  useMyUsage,
} from "@/lib/api/hooks";
import type { MetaConnectionStatus } from "@/lib/api/types";

function formatRelativeDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const d = new Date(isoDate);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const META_ERROR_LABELS: Record<string, string> = {
  declined: "You declined the Meta permissions prompt.",
  missing_params: "Meta didn't return the expected parameters.",
  invalid_state: "The OAuth session expired — please try again.",
  exchange_failed: "Meta rejected the authorization code.",
  crypto_error: "Couldn't securely store your Meta token.",
  enumeration_failed:
    "Connected, but couldn't read your ad accounts or Pages. Reconnect to retry.",
};

/**
 * Dashboard home — campaign list + Meta connection state + usage tile.
 *
 * Port of the design at
 * ``kleiber-agent-deign/project/src/dashboard/screens-a.jsx::DashboardHome``.
 * Shape:
 *
 * 1. Page header: "campaigns" lowercase editorial heading, signed-in
 *    email subtitle, actions (Import campaigns button, shown only
 *    when Meta is connected).
 * 2. Meta connection banner — full-width card. "not connected"
 *    variant is warmer-toned with a primary Connect button; the
 *    connected variant is a compact success row with a disconnect
 *    button.
 * 3. Two-column layout:
 *    - Left: 2/3 width — grid of campaign cards (each card links
 *      into /campaigns/:id)
 *    - Right: 1/3 width — the UsageTile (30-day cost + service
 *      breakdown + top spender)
 * 4. Empty-state card when there are no campaigns yet — variant
 *    depends on whether Meta is connected or not.
 */
export function DashboardRoute() {
  const me = useMe();
  const metaStatus = useMetaStatus();
  const usage = useMyUsage();

  const campaigns = me.data?.campaigns ?? [];
  const metaConnected = metaStatus.data?.connected ?? false;
  const isLoadingCampaigns = me.isLoading;

  return (
    <DashPage
      title="campaigns"
      sub={
        me.data?.email ? (
          <>
            signed in as{" "}
            <b style={{ color: "var(--ink)", fontWeight: 500 }}>
              {me.data.email}
            </b>
          </>
        ) : null
      }
      actions={
        metaConnected ? (
          <Link
            to="/campaigns/import"
            className="btn btn-primary btn-sm"
            style={{ textDecoration: "none" }}
          >
            + Import campaigns
          </Link>
        ) : null
      }
    >
      <MetaConnection
        connected={metaConnected}
        status={metaStatus.data}
        isLoading={metaStatus.isLoading}
      />

      <div
        data-ds-grid
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 20,
          marginTop: 24,
          alignItems: "start",
        }}
      >
        <div>
          <div className="eyebrow" style={{ marginBottom: 14 }}>
            YOUR CAMPAIGNS
            {campaigns.length > 0 ? ` · ${campaigns.length} / 5` : ""}
          </div>
          {isLoadingCampaigns ? (
            <CampaignGridSkeleton />
          ) : campaigns.length === 0 ? (
            <EmptyState
              title={
                metaConnected
                  ? "No campaigns yet"
                  : "Connect Meta to get started"
              }
              desc={
                metaConnected
                  ? "Import campaigns from your connected Meta ad account. Kleiber will pull their last 60 days of metrics and start watching them overnight."
                  : "Kleiber needs read + write access to your Meta ad account and page so it can pull metrics and deploy variants. Connect above, then import."
              }
              action={
                metaConnected ? (
                  <Link
                    to="/campaigns/import"
                    className="btn btn-primary btn-sm"
                    style={{ textDecoration: "none" }}
                  >
                    Import campaigns →
                  </Link>
                ) : null
              }
              icon="◎"
            />
          ) : (
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(280px, 1fr))",
                gap: 14,
              }}
            >
              {campaigns.map((c) => (
                <CampaignCard key={c.id} campaign={c} />
              ))}
            </div>
          )}
        </div>

        <UsageTile
          isLoading={usage.isLoading}
          isError={usage.isError}
          data={usage.data ?? null}
        />
      </div>
    </DashPage>
  );
}

/* ---------------------------------------------------------------- */
/* Meta connection banner                                           */
/* ---------------------------------------------------------------- */

function MetaConnection({
  connected,
  status,
  isLoading,
}: {
  connected: boolean;
  status: MetaConnectionStatus | null | undefined;
  isLoading: boolean;
}) {
  const qc = useQueryClient();
  const connect = useConnectMeta();
  const disconnect = useDisconnectMeta();
  const [banner, setBanner] = useState<
    { kind: "success" | "error"; text: string } | null
  >(null);

  // Read meta_connected / meta_error callback params on mount — same
  // behaviour as the legacy ConnectMetaCard. Strips them from the URL
  // so a refresh doesn't replay the toast, then re-fetches status.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const connectedParam = params.get("meta_connected");
    const errorParam = params.get("meta_error");
    if (!connectedParam && !errorParam) return;

    if (connectedParam === "1") {
      setBanner({ kind: "success", text: "Connected to Meta." });
    } else if (errorParam) {
      setBanner({
        kind: "error",
        text: META_ERROR_LABELS[errorParam] ?? "Couldn't connect to Meta.",
      });
    }

    params.delete("meta_connected");
    params.delete("meta_error");
    const nextQs = params.toString();
    const nextUrl =
      window.location.pathname +
      (nextQs ? `?${nextQs}` : "") +
      window.location.hash;
    window.history.replaceState({}, "", nextUrl);

    qc.invalidateQueries({ queryKey: qk.metaStatus });
  }, [qc]);

  const handleConnect = () => {
    connect.mutate(undefined, {
      onSuccess: (data) => {
        window.location.href = data.auth_url;
      },
    });
  };

  const handleDisconnect = () => {
    if (
      typeof window !== "undefined" &&
      !window.confirm(
        "Disconnect Meta? The system will stop being able to run cycles for your campaigns until you reconnect.",
      )
    ) {
      return;
    }
    disconnect.mutate();
  };

  const connectError = connect.isError
    ? "Couldn't start the Meta OAuth flow — please try again."
    : null;
  const disconnectError = disconnect.isError
    ? "Couldn't disconnect — please try again."
    : null;

  // Pre-resolution: avoid flashing the "NOT CONNECTED" banner on first
  // paint for users who are in fact connected. Render a neutral
  // placeholder until /api/me/meta/status resolves.
  if (isLoading && !status) {
    return (
      <div
        style={{
          padding: 18,
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "var(--paper-2)",
          fontSize: 13,
          color: "var(--muted)",
        }}
      >
        Checking Meta connection…
      </div>
    );
  }

  if (!connected) {
    return (
      <div
        data-ds-grid
        style={{
          padding: 22,
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "var(--paper-2)",
          display: "grid",
          gridTemplateColumns: "1fr auto",
          alignItems: "center",
          gap: 20,
        }}
      >
        <div>
          <div
            className="eyebrow"
            style={{ color: "oklch(48% 0.16 28)" }}
          >
            NOT CONNECTED
          </div>
          <h3
            style={{
              fontSize: 17,
              fontWeight: 500,
              margin: "6px 0 4px",
              color: "var(--ink)",
            }}
          >
            Connect your Meta account
          </h3>
          <p
            style={{
              fontSize: 13,
              color: "var(--muted)",
              margin: 0,
              maxWidth: 460,
            }}
          >
            Kleiber needs read / write on your ad account and Page to pull
            metrics and deploy variants.
          </p>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: 6,
          }}
        >
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={handleConnect}
            disabled={connect.isPending}
          >
            {connect.isPending ? "Redirecting…" : "Connect Meta →"}
          </button>
          {(banner || connectError) && (
            <BannerLine
              kind={banner?.kind ?? "error"}
              text={banner?.text ?? connectError ?? ""}
            />
          )}
        </div>
      </div>
    );
  }
  const adAccountCount = status?.available_ad_accounts?.length ?? 0;
  const pageCount = status?.available_pages?.length ?? 0;
  return (
    <div
      style={{
        padding: 18,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
      }}
    >
      <div
        data-ds-grid
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          alignItems: "center",
          gap: 20,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              background: "var(--win-soft)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path
                d="M4 9l3 3 7-7"
                stroke="oklch(40% 0.14 145)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
          </div>
          <div>
            <div
              style={{ fontSize: 14, fontWeight: 500, color: "var(--ink)" }}
            >
              Meta connected
            </div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11.5,
                color: "var(--muted)",
              }}
            >
              {adAccountCount} ad account{adAccountCount === 1 ? "" : "s"} ·{" "}
              {pageCount} page{pageCount === 1 ? "" : "s"}
            </div>
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: 6,
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleDisconnect}
            disabled={disconnect.isPending}
          >
            {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
          </button>
          {(banner || disconnectError) && (
            <BannerLine
              kind={banner?.kind ?? "error"}
              text={banner?.text ?? disconnectError ?? ""}
            />
          )}
        </div>
      </div>

      {status && (
        <dl
          data-ds-grid
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 16,
            margin: "14px 0 0",
            paddingTop: 14,
            borderTop: "1px solid var(--border-soft)",
          }}
        >
          <MetaFact label="Meta user ID" value={status.meta_user_id ?? "—"} mono />
          <MetaFact
            label="Connected"
            value={formatRelativeDate(status.connected_at)}
          />
          <MetaFact
            label="Token expires"
            value={formatRelativeDate(status.token_expires_at)}
          />
        </dl>
      )}
    </div>
  );
}

function MetaFact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="eyebrow" style={{ fontSize: 9.5 }}>
        {label}
      </dt>
      <dd
        style={{
          margin: "4px 0 0",
          fontSize: 12.5,
          color: "var(--ink)",
          fontFamily: mono ? "var(--font-mono)" : undefined,
        }}
      >
        {value}
      </dd>
    </div>
  );
}

function BannerLine({
  kind,
  text,
}: {
  kind: "success" | "error";
  text: string;
}) {
  return (
    <span
      style={{
        fontSize: 11.5,
        color:
          kind === "success" ? "oklch(40% 0.14 145)" : "oklch(48% 0.16 28)",
      }}
    >
      {text}
    </span>
  );
}

/* ---------------------------------------------------------------- */
/* Campaign card + skeleton                                          */
/* ---------------------------------------------------------------- */

function CampaignCard({
  campaign,
}: {
  campaign: { id: string; name: string; is_active: boolean };
}) {
  return (
    <Link
      to={`/campaigns/${campaign.id}`}
      style={{
        textAlign: "left",
        display: "block",
        padding: 18,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
        textDecoration: "none",
        transition: "all 0.15s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-md)";
        e.currentTarget.style.transform = "translateY(-1px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "none";
        e.currentTarget.style.transform = "none";
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
        }}
      >
        <div
          style={{
            fontSize: 16,
            fontWeight: 500,
            letterSpacing: "-0.015em",
            color: "var(--ink)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {campaign.name}
        </div>
        <StatusPill kind={campaign.is_active ? "active" : "paused"}>
          {campaign.is_active ? "active" : "paused"}
        </StatusPill>
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "var(--muted)",
          marginTop: 3,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {campaign.id}
      </div>
      <div
        style={{
          marginTop: 14,
          paddingTop: 14,
          borderTop: "1px solid var(--border-soft)",
          fontSize: 12,
          color: "var(--muted)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>View reports & experiments</span>
        <span>→</span>
      </div>
    </Link>
  );
}

function CampaignGridSkeleton() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 14,
      }}
    >
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          style={{
            padding: 18,
            border: "1px solid var(--border)",
            borderRadius: 12,
            background: "white",
            minHeight: 120,
          }}
        >
          <div
            style={{
              height: 18,
              width: "55%",
              background: "var(--paper-2)",
              borderRadius: 4,
            }}
          />
          <div
            style={{
              height: 10,
              width: "35%",
              background: "var(--paper-2)",
              borderRadius: 4,
              marginTop: 10,
            }}
          />
          <div
            style={{
              height: 1,
              background: "var(--border-soft)",
              margin: "18px 0 12px",
            }}
          />
          <div
            style={{
              height: 12,
              width: "70%",
              background: "var(--paper-2)",
              borderRadius: 4,
            }}
          />
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Usage tile                                                        */
/* ---------------------------------------------------------------- */

function formatUsdPrecise(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "$0.00";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "$0.00";
  if (n === 0) return "$0.00";
  if (Math.abs(n) >= 1) {
    return `$${n.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
  if (Math.abs(n) >= 0.01) {
    return `$${n.toFixed(2)}`;
  }
  return `$${n.toFixed(4)}`;
}

function formatIntComma(n: number | string): string {
  const v = typeof n === "number" ? n : Number(n);
  if (!Number.isFinite(v)) return String(n);
  return v.toLocaleString("en-US");
}

function UsageTile({
  isLoading,
  isError,
  data,
}: {
  isLoading: boolean;
  isError: boolean;
  data:
    | {
        total_cost_usd: string;
        total_calls: number;
        by_service: { service: string; cost_usd: string; calls: number }[];
        by_campaign: { campaign_name?: string | null; cost_usd: string }[];
        from_date: string;
        to_date: string;
      }
    | null;
}) {
  const frame: React.CSSProperties = {
    padding: 22,
    border: "1px solid var(--border)",
    borderRadius: 12,
    background: "white",
    minWidth: 0,
  };
  if (isLoading) {
    return (
      <div style={frame}>
        <div className="eyebrow">USAGE · LAST 30 DAYS</div>
        <p
          style={{
            marginTop: 12,
            fontSize: 12,
            color: "var(--muted)",
            fontFamily: "var(--font-mono)",
          }}
        >
          Loading…
        </p>
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div style={frame}>
        <div className="eyebrow">USAGE · LAST 30 DAYS</div>
        <p
          style={{
            marginTop: 12,
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          Couldn&apos;t load usage data.
        </p>
      </div>
    );
  }
  const topCampaign = data.by_campaign[0];
  return (
    <div style={frame}>
      <div
        className="eyebrow"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <span>USAGE · LAST 30 DAYS</span>
        <span style={{ fontSize: 9.5, color: "var(--muted-2)" }}>
          {data.from_date} → {data.to_date}
        </span>
      </div>
      <div
        style={{
          fontSize: 36,
          fontWeight: 500,
          letterSpacing: "-0.03em",
          marginTop: 6,
          color: "var(--ink)",
        }}
      >
        {formatUsdPrecise(data.total_cost_usd)}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11.5,
          color: "var(--muted)",
        }}
      >
        {formatIntComma(data.total_calls)} API call
        {data.total_calls === 1 ? "" : "s"}
      </div>

      {data.by_service.length > 0 && (
        <div
          style={{
            marginTop: 18,
            borderTop: "1px solid var(--border-soft)",
            paddingTop: 14,
          }}
        >
          {data.by_service.map((row) => (
            <div
              key={row.service}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "7px 0",
                fontSize: 13,
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: "var(--muted)",
                }}
              >
                {row.service === "llm"
                  ? "llm"
                  : row.service === "meta_api"
                    ? "meta_api"
                    : row.service}
              </span>
              <span style={{ fontFamily: "var(--font-mono)" }}>
                {formatUsdPrecise(row.cost_usd)}{" "}
                <span style={{ color: "var(--muted)" }}>
                  · {formatIntComma(row.calls)}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}

      {topCampaign?.campaign_name && (
        <div
          style={{
            marginTop: 14,
            padding: 10,
            background: "var(--paper-2)",
            borderRadius: 8,
            fontSize: 12,
            color: "var(--ink-2)",
          }}
        >
          Top spender:{" "}
          <b style={{ color: "var(--ink)", fontWeight: 500 }}>
            {topCampaign.campaign_name}
          </b>{" "}
          <span style={{ color: "var(--muted)" }}>
            ({formatUsdPrecise(topCampaign.cost_usd)})
          </span>
        </div>
      )}

      {data.by_service.length === 0 && !topCampaign && (
        <p
          style={{
            marginTop: 14,
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          No activity yet — run a cycle to start tracking usage.
        </p>
      )}
    </div>
  );
}
