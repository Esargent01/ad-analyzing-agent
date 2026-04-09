import { useEffect } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Header } from "@/components/layout/Header";
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
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-xs text-[var(--text-tertiary)]">Loading…</p>
      </div>
    );
  }

  if (!me.data) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/sign-in?redirect=${redirect}`} replace />;
  }

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      <Header />
      <main className="mx-auto max-w-5xl px-5 py-8">
        <Outlet />
      </main>
    </div>
  );
}
