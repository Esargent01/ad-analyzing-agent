/**
 * "Connect Meta" card shown on the dashboard.
 *
 * Three visual states:
 * - Loading: skeleton while /api/me/meta/status resolves
 * - Not connected: big CTA that kicks off /api/me/meta/connect →
 *   redirects the window to the Facebook OAuth dialog
 * - Connected: shows the stored meta_user_id, when it was linked,
 *   when the 60-day token expires, and a "Disconnect" button
 *
 * The card listens for `?meta_connected=1` / `?meta_error=<code>` on
 * mount and invalidates the status query so post-callback state flips
 * instantly. The query param is stripped from the URL afterwards so a
 * refresh doesn't re-fire the toast.
 */

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import {
  qk,
  useConnectMeta,
  useDisconnectMeta,
  useMetaStatus,
} from "@/lib/api/hooks";

function formatRelative(isoDate: string | null): string {
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
  // Phase G: the callback fans out into ad account + Page enumeration.
  // A failure on either leaves the connection unusable for importing,
  // so we surface a dedicated reconnect nudge.
  enumeration_failed:
    "Connected, but couldn't read your ad accounts or Pages. Reconnect to retry.",
};

export function ConnectMetaCard() {
  const qc = useQueryClient();
  const status = useMetaStatus();
  const connect = useConnectMeta();
  const disconnect = useDisconnectMeta();
  const [banner, setBanner] = useState<
    { kind: "success" | "error"; text: string } | null
  >(null);

  // On mount, read the callback query params. Any value → show toast,
  // strip the params so a refresh doesn't replay them, then invalidate
  // the status query so the UI re-reads.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("meta_connected");
    const error = params.get("meta_error");
    if (!connected && !error) return;

    if (connected === "1") {
      setBanner({ kind: "success", text: "Connected to Meta." });
    } else if (error) {
      setBanner({
        kind: "error",
        text: META_ERROR_LABELS[error] ?? "Couldn't connect to Meta.",
      });
    }

    params.delete("meta_connected");
    params.delete("meta_error");
    const nextQs = params.toString();
    const nextUrl =
      window.location.pathname + (nextQs ? `?${nextQs}` : "") + window.location.hash;
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

  if (status.isLoading) {
    return (
      <Card className="mb-6">
        <p className="text-sm text-[var(--text-secondary)]">
          Checking Meta connection…
        </p>
      </Card>
    );
  }

  const connected = status.data?.connected ?? false;

  return (
    <Card className="mb-6">
      {banner && (
        <div
          className={
            banner.kind === "success"
              ? "mb-3 rounded border border-emerald-700/40 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-300"
              : "mb-3 rounded border border-red-700/40 bg-red-950/40 px-3 py-2 text-xs text-red-300"
          }
          role="status"
        >
          {banner.text}
        </div>
      )}

      <CardHeader>
        <div>
          <CardTitle>
            {connected ? "Meta connected" : "Connect your Meta ad account"}
          </CardTitle>
          <CardDescription>
            {connected
              ? "The agent runs cycles using your personal Meta token."
              : "Required before you can import campaigns."}
          </CardDescription>
        </div>
        {connected ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={handleDisconnect}
            loading={disconnect.isPending}
          >
            Disconnect
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={handleConnect}
            loading={connect.isPending}
          >
            Connect Meta
          </Button>
        )}
      </CardHeader>

      {connected && status.data && (
        <>
          <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
            <div>
              <dt className="text-[var(--text-tertiary)]">Meta user ID</dt>
              <dd className="mt-0.5 font-mono text-[var(--text)]">
                {status.data.meta_user_id ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Connected</dt>
              <dd className="mt-0.5 text-[var(--text)]">
                {formatRelative(status.data.connected_at)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Token expires</dt>
              <dd className="mt-0.5 text-[var(--text)]">
                {formatRelative(status.data.token_expires_at)}
              </dd>
            </div>
          </dl>
          {/* Phase G: surface the enumerated asset counts so the user
              knows their token has reachable accounts + Pages before
              they hit the import page. Defend with ?? [] because a
              Phase F-era backend (or a cached CDN response) may not
              include these fields yet — we don't want the dashboard
              to crash during a staggered deploy. */}
          {(() => {
            const accounts = status.data.available_ad_accounts ?? [];
            const pages = status.data.available_pages ?? [];
            return (
              <p className="mt-3 text-xs text-[var(--text-tertiary)]">
                {accounts.length} ad account
                {accounts.length === 1 ? "" : "s"},{" "}
                {pages.length} Page
                {pages.length === 1 ? "" : "s"}
                {accounts.length === 0 && (
                  <span className="ml-2 text-amber-300">
                    — create one in Meta Ads Manager before importing
                  </span>
                )}
              </p>
            );
          })()}
        </>
      )}

      {connect.isError && (
        <p className="mt-3 text-xs text-red-400">
          Couldn't start the Meta connect flow. Please try again.
        </p>
      )}
      {disconnect.isError && (
        <p className="mt-3 text-xs text-red-400">
          Couldn't disconnect — please try again.
        </p>
      )}
    </Card>
  );
}
