/**
 * Standard page frame for every dashboard route.
 *
 * Provides breadcrumb · lowercase editorial title · optional subtitle ·
 * optional action row · divider · content area. The ``children`` region
 * is whatever the route wants — usually a grid of ``StatTile``s plus
 * deeper content blocks.
 *
 * Matches ``kleiber-agent-deign/project/src/dashboard/primitives.jsx::DashPage``.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export interface DashPageCrumb {
  label: string;
  /** If omitted, renders as plain text (current page). */
  href?: string;
}

export function DashPage({
  crumb,
  title,
  sub,
  actions,
  children,
}: {
  crumb?: DashPageCrumb[];
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        maxWidth: 1320,
        margin: "0 auto",
        padding: "32px 28px 120px",
      }}
    >
      {crumb && crumb.length > 0 && (
        <div
          style={{
            marginBottom: 16,
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12.5,
            color: "var(--muted)",
            flexWrap: "wrap",
          }}
        >
          {crumb.map((c, i) => (
            <div
              key={`${c.label}-${i}`}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              {i > 0 && <span style={{ opacity: 0.5 }}>/</span>}
              {c.href ? (
                <Link
                  to={c.href}
                  style={{ color: "var(--ink-2)", textDecoration: "none" }}
                >
                  {c.label}
                </Link>
              ) : (
                <span>{c.label}</span>
              )}
            </div>
          ))}
        </div>
      )}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 20,
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0, flex: "1 1 auto" }}>
          <h1 className="h-display">{title}</h1>
          {sub && (
            <div
              style={{
                color: "var(--muted)",
                fontSize: 15,
                marginTop: 8,
              }}
            >
              {sub}
            </div>
          )}
        </div>
        {actions && (
          <div
            style={{
              display: "flex",
              gap: 8,
              flexWrap: "wrap",
              flexShrink: 0,
            }}
          >
            {actions}
          </div>
        )}
      </div>
      <div
        style={{
          height: 1,
          background: "var(--border)",
          margin: "28px 0 32px",
        }}
      />
      {children}
    </div>
  );
}
