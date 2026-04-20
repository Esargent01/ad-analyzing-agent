import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";

import { DashShell } from "@/components/dashboard/DashShell";
import { useMe } from "@/lib/api/hooks";

/**
 * Authed layout — wraps every route that requires a session cookie.
 *
 * The `useMe` query is the source of truth for "am I signed in": if it
 * returns null (from a 401) we redirect to /sign-in and forward the
 * requested path so the user can come back after verifying their link.
 *
 * We also subscribe to the global `auth:unauthenticated` event emitted
 * by the API client so background queries that 401 kick the user back.
 *
 * Chrome is now ``DashShell`` (warm-paper palette, sticky nav with
 * Kleiber wordmark + user menu) — every authed route renders inside
 * it. Individual pages use ``DashPage`` to get the standard
 * breadcrumb / title / actions frame.
 */
export function AuthedLayout() {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const handler = () => {
      navigate("/sign-in", { replace: true });
    };
    window.addEventListener("auth:unauthenticated", handler);
    return () => window.removeEventListener("auth:unauthenticated", handler);
  }, [navigate]);

  if (me.isLoading) {
    return (
      <div
        style={{
          display: "flex",
          minHeight: "100vh",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--paper)",
          fontFamily: "var(--font-sans)",
        }}
      >
        <p
          style={{
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

  if (!me.data) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/sign-in?redirect=${redirect}`} replace />;
  }

  return (
    <DashShell>
      <Outlet />
    </DashShell>
  );
}
