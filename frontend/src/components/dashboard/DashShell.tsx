/**
 * Dashboard chrome — sticky nav at the top, main content below.
 *
 * Matches the design drop at
 * ``kleiber-agent-deign/project/src/dashboard/primitives.jsx::DashNav``.
 * Layout: serif "Kleiber" wordmark on the left with a tenant pill,
 * three top-level nav links in the middle, user avatar + dropdown
 * on the right.
 *
 * The wordmark uses DM Serif Display (already loaded by
 * ``index.html``) to stay consistent with the marketing landings.
 */

import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { qk, useLogout, useMe } from "@/lib/api/hooks";

function initials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}

export function DashShell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", background: "var(--paper)", color: "var(--ink)", fontFamily: "var(--font-sans)" }}>
      <DashNav />
      <main>{children}</main>
    </div>
  );
}

function DashNav() {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close the dropdown on any outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const email = me.data?.email ?? "";
  const avatarInitials = email ? initials(email) : "··";

  const onSignOut = async () => {
    try {
      await logout.mutateAsync();
    } finally {
      queryClient.setQueryData(qk.me, null);
      queryClient.invalidateQueries({ queryKey: qk.me });
      navigate("/sign-in", { replace: true });
    }
  };

  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 40,
        background: scrolled
          ? "oklch(98.5% 0.006 80 / 0.92)"
          : "var(--paper)",
        backdropFilter: scrolled ? "blur(10px) saturate(1.2)" : "none",
        WebkitBackdropFilter: scrolled ? "blur(10px) saturate(1.2)" : "none",
        borderBottom: "1px solid var(--border-soft)",
        transition: "background 0.15s",
      }}
    >
      <div
        style={{
          maxWidth: 1320,
          margin: "0 auto",
          padding: "0 28px",
          height: 60,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, minWidth: 0 }}>
          <Link
            to="/dashboard"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              textDecoration: "none",
            }}
          >
            <span
              style={{
                fontFamily: "'DM Serif Display', serif",
                fontSize: 22,
                letterSpacing: "-0.01em",
                color: "var(--ink)",
                lineHeight: 1,
              }}
            >
              Kleiber
            </span>
          </Link>
          {email && (
            <>
              <span
                aria-hidden
                style={{
                  width: 1,
                  height: 20,
                  background: "var(--border)",
                  display: "inline-block",
                }}
              />
              <span
                style={{
                  fontSize: 13.5,
                  color: "var(--ink-2)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 220,
                }}
                className="dash-nav-tenant"
              >
                {email}
              </span>
            </>
          )}
        </div>

        <div
          className="dash-nav-links"
          style={{ display: "flex", alignItems: "center", gap: 22 }}
        >
          <NavLink to="/dashboard" active={location.pathname === "/dashboard"}>
            Campaigns
          </NavLink>
          <div ref={menuRef} style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-haspopup="menu"
              aria-expanded={open}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 10px 4px 4px",
                borderRadius: 99,
                border: "1px solid var(--border)",
                background: "white",
                cursor: "pointer",
              }}
            >
              <span
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: 99,
                  background: "var(--accent-soft)",
                  color: "var(--accent-ink)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11.5,
                  fontWeight: 500,
                }}
              >
                {avatarInitials}
              </span>
              <span style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
                {email || "Sign in"}
              </span>
            </button>
            {open && (
              <div
                role="menu"
                style={{
                  position: "absolute",
                  right: 0,
                  top: 44,
                  width: 220,
                  background: "white",
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  boxShadow: "var(--shadow-md)",
                  overflow: "hidden",
                }}
              >
                <MenuItem href="/">Back to site</MenuItem>
                <div style={{ height: 1, background: "var(--border)" }} />
                <MenuButton onClick={onSignOut} disabled={logout.isPending}>
                  {logout.isPending ? "Signing out…" : "Sign out"}
                </MenuButton>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}

function NavLink({
  to,
  active,
  children,
}: {
  to: string;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      style={{
        fontSize: 13.5,
        color: active ? "var(--ink)" : "var(--muted)",
        fontWeight: active ? 500 : 400,
        textDecoration: "none",
        padding: "4px 2px",
        transition: "color 0.15s",
      }}
    >
      {children}
    </Link>
  );
}

function MenuItem({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      to={href}
      style={{
        display: "block",
        padding: "10px 14px",
        fontSize: 13,
        color: "var(--ink-2)",
        textAlign: "left",
        width: "100%",
        textDecoration: "none",
      }}
    >
      {children}
    </Link>
  );
}

function MenuButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        display: "block",
        padding: "10px 14px",
        fontSize: 13,
        color: "var(--ink-2)",
        textAlign: "left",
        width: "100%",
        background: "transparent",
        border: 0,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {children}
    </button>
  );
}
